from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from time import monotonic, time
from typing import Any, cast
from uuid import uuid4

from PIL import Image
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.bootstrap.library import (
    effective_book_cover_paths,
)
from app.bootstrap.media import versioned_cover_url
from app.bootstrap.metadata_recognition import (
    recognition_cover_downloader,
    recognition_patches,
    recognition_writeback,
)
from app.core.config import Settings
from app.core.database_errors import (
    is_database_busy_error,
    is_database_operation_timeout,
)
from app.core.exception_diagnostics import (
    exception_diagnostic_boundary,
    record_exception,
)
from app.core.i18n import configured_locale
from app.models.common import db_timestamp
from app.modules.library.public import (
    MetadataChange,
    MetadataPatchActor,
    MetadataTarget,
    MetadataValue,
)
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.application.field_proposals import (
    propose_fields,
    supplement_fields,
)
from app.modules.metadata.application.queries import recognition_queries
from app.modules.metadata.application.rate_limits import (
    AutomaticMetadataRequestGate,
    RecognitionRequestBudget,
    RecognitionRequestStopped,
)
from app.modules.metadata.application.recognition import (
    assess_candidates,
    candidate_summary,
    match_view,
)
from app.modules.metadata.domain.recognition import recognition_fingerprint
from app.modules.metadata.infrastructure import lookup_queue as lookup_persist
from app.modules.metadata.infrastructure.http import provider_error_code
from app.modules.metadata.infrastructure.recognition_context import (
    load_recognition_context,
    provider_context,
)
from app.services.metadata_file_writeback import (
    maintain_metadata_writebacks,
    process_next_metadata_writeback,
    recover_interrupted_metadata_writebacks,
)
from app.services.metadata_provider_registry import (
    metadata_provider_registry,
    search_with_metadata_provider,
)
from app.services.organize_service import (
    metadata_candidate_title_exact_match,
    metadata_context_for_book,
)
from app.services.queue_runtime import QueueHeartbeatPump

LOGGER = logging.getLogger(__name__)
RETRY_DELAYS_SECONDS = (60, 300, 1800)
DATABASE_BUSY_RETRY_DELAYS_SECONDS = (0.25, 1.0)
STALE_RUNNING_MINUTES = lookup_persist.STALE_RUNNING_MINUTES
ORPHAN_COVER_PART_MAX_AGE_SECONDS = 24 * 60 * 60


class MetadataLookupRuleFailure(RuntimeError):
    """An observed lookup precondition failed without a lower exception."""


class MetadataLookupRetryLimitReached(RuntimeError):
    """The recorded lookup attempt count exhausted its configured retry budget."""


def _now() -> datetime:
    return db_timestamp()


def recover_stale_metadata_lookup_tasks(db: Session) -> int:
    now = _now()
    with MetadataWriteTransaction(db):
        recovered = lookup_persist.recover_stale_lookup_tasks(db, now=now)
    return recovered


def claim_next_metadata_lookup_task(
    db: Session, *, owner_id: str = "metadata-lookup-compat"
) -> dict[str, Any] | None:
    db.close()
    now = _now()
    lease_expires_at = now + timedelta(seconds=lookup_persist.LOOKUP_LEASE_SECONDS)
    with MetadataWriteTransaction(db):
        task = lookup_persist.claim_next_lookup_task(
            db,
            owner_id=owner_id,
            now=now,
            lease_expires_at=lease_expires_at,
            organize_job_ready=True,
        )
    return task


def _provider_order(task: dict[str, Any]) -> list[str]:
    try:
        parsed = json.loads(str(task.get("providerOrder") or "[]"))
    except json.JSONDecodeError as error:
        record_exception(logging.getLogger(__name__), "services.metadata_lookup_queue._provider_order.failed", error,
                         context={"step": "_provider_order", "task_id": str(task.get("id") or ""), "attempt": int(task.get("attempts") or 0) + 1})
        parsed = []
    registered = metadata_provider_registry().ids()
    return [str(item) for item in parsed if str(item) in registered and str(item) != "ai"]


def _search_provider(
    db: Session,
    context: dict[str, Any],
    provider: str,
    query: str | None,
    automatic_request_gate: AutomaticMetadataRequestGate | None,
) -> dict[str, Any]:
    return search_with_metadata_provider(
        db,
        context,
        provider,
        query,
        force=False,
        use_cache=True,
        automatic_request_gate=automatic_request_gate,
    )


def _start_provider_execution(
    db: Session, task: dict[str, Any], provider: str
) -> str | None:
    execution_id = f"py_{uuid4().hex}"
    attempts = int(task.get("attempts") or 0) + 1
    now = _now()
    db.close()
    prepared = lookup_persist.prepare_provider_execution_start(
        task,
        provider,
        execution_id=execution_id,
        attempts=attempts,
        now=now,
    )
    with MetadataWriteTransaction(db):
        persisted_id = lookup_persist.write_prepared_provider_execution(db, prepared)
    return persisted_id


def _finish_provider_execution(
    db: Session,
    execution_id: str | None,
    *,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> None:
    raw_result_json = (
        json.dumps({**result, "candidates": [candidate_summary(item) for item in result.get("candidates", [])[:10]]} if isinstance(result, dict) else result, ensure_ascii=False) if result is not None else None
    )
    now = _now()
    db.close()
    prepared = lookup_persist.prepare_provider_execution_finish(
        execution_id,
        status=status,
        raw_result_json=raw_result_json,
        error=error,
        now=now,
    )
    with MetadataWriteTransaction(db):
        lookup_persist.write_prepared_provider_execution(db, prepared)


def _parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            record_exception(logging.getLogger(__name__), "services.metadata_lookup_queue._parse_tags.failed", error,
                             context={"step": "_parse_tags"})
            return []
        return _parse_tags(parsed)
    return []


def _local_cover_exists(
    db: Session, book: dict[str, Any], resource_id: str | None, settings: Settings
) -> bool:
    del resource_id
    book_id = str(book.get("id") or "").strip()
    return bool(
        versioned_cover_url(
            "/api/books/cover",
            effective_book_cover_paths(db, (book_id,)).get(book_id),
            settings,
        )
    )


@dataclass(frozen=True, slots=True)
class _PreparedRemoteCover:
    temporary_path: Path
    final_path: Path
    relative_final_path: str


def _cleanup_orphan_remote_cover_parts(
    target_dir: Path,
    *,
    book_id: str,
    current_time: float | None = None,
) -> int:
    cutoff = (time() if current_time is None else current_time) - (
        ORPHAN_COVER_PART_MAX_AGE_SECONDS
    )
    removed = 0
    for part_path in target_dir.glob(f".{book_id}-remote-*.part"):
        try:
            if part_path.stat().st_mtime > cutoff:
                continue
            part_path.unlink(missing_ok=True)
            removed += 1
        except OSError as error:
            record_exception(logging.getLogger(__name__), "services.metadata_lookup_queue._cleanup_orphan_remote_cover_parts.failed", error,
                             context={"step": "_cleanup_orphan_remote_cover_parts"})
    return removed


def _validated_remote_cover_suffix(data: bytes) -> str:
    with Image.open(BytesIO(data)) as cover:
        suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(str(cover.format))
        cover.verify()
    if suffix is None:
        raise ValueError("REMOTE_COVER_INVALID")
    return suffix


def _download_remote_cover(
    book_id: str, cover_url: str, settings: Settings
) -> _PreparedRemoteCover | None:
    if not cover_url.startswith(("http://", "https://")):
        return None
    data = recognition_cover_downloader().download(cover_url)
    suffix = _validated_remote_cover_suffix(data)
    target_dir = settings.resolved_storage_root / "covers"
    target_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_orphan_remote_cover_parts(target_dir, book_id=book_id)
    final_path = target_dir / f"{book_id}-remote-{uuid4().hex}{suffix}"
    temporary_path = final_path.with_name(f".{final_path.name}.part")
    temporary_path.write_bytes(data)
    if temporary_path.stat().st_size != len(data):
        temporary_path.unlink(missing_ok=True)
        raise OSError("REMOTE_COVER_INVALID")
    return _PreparedRemoteCover(
        temporary_path=temporary_path,
        final_path=final_path,
        relative_final_path=str(final_path.relative_to(settings.resolved_storage_root)),
    )


def _publish_remote_cover(prepared: _PreparedRemoteCover) -> None:
    try:
        os.replace(prepared.temporary_path, prepared.final_path)
    except OSError as error:
        primary_id = record_exception(LOGGER, "metadata.cover_replace_failed", error, context={"step": "replace_cover"})
        try:
            prepared.temporary_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            record_exception(LOGGER, "metadata.cover_cleanup_failed", cleanup_error,
                             context={"step": "cleanup_cover", "parent_diagnostic_id": primary_id})
        raise


def _discard_remote_cover(prepared: _PreparedRemoteCover | None) -> None:
    if prepared is not None:
        prepared.temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class _PreparedCandidateApplication:
    book_id: str
    resource_id: str | None
    target_type: MetadataTarget
    target_id: str
    task_id: str
    fingerprint: str
    actor: MetadataPatchActor
    changes: tuple[MetadataChange, ...]
    remote_cover: _PreparedRemoteCover | None
    applied: tuple[str, ...]
    organize_job_id: str | None


def _prepare_candidate_application(
    db: Session, settings: Settings, task: dict[str, Any], provider: str,
    candidate: dict[str, Any],
    supplement: tuple[str, dict[str, Any]] | None = None,
) -> _PreparedCandidateApplication:
    resource_id = (str(task.get("resourceId") or "") or None) if task.get("recognition", {}).get("targetType") == "resource" else None
    context = load_recognition_context(db, book_id=str(task["bookId"]), resource_id=resource_id, execution="AUTOMATIC")
    if context is None or (task.get("recognition", {}).get("targetType") == "resource" and resource_id is None):
        raise ValueError("RECOGNITION_TARGET_DELETED")
    fingerprint = recognition_fingerprint(context)
    if task.get("recognition", {}).get("fingerprint", fingerprint) != fingerprint:
        raise ValueError("RECOGNITION_CHANGED")
    assessed = assess_candidates(context, provider, [candidate])
    proposals = propose_fields(context, provider, candidate, assessed[0][1])
    if supplement is not None:
        proposals += supplement_fields(context, provider, candidate, supplement[0], supplement[1])
    application = recognition_patches(db)
    before = application.port.snapshot(context.target_type, context.target_id, frozenset({context.library_id}))
    if before is None:
        raise ValueError("RECOGNITION_TARGET_DELETED")
    task_id = str(task["id"])
    actor = MetadataPatchActor(None, None, frozenset({context.library_id}), True, False, False, task_id)
    # Unknown existing provenance is never permission to overwrite. PATH repair
    # requires verifiable provenance; current historical rows remain UNKNOWN.
    repair_path = lookup_persist.allow_path_metadata_repair(db)
    origins = dict(context.provenance)
    values: dict[str, MetadataValue] = {}
    provenance: dict[str, str] = {}
    for proposal in proposals:
        name = proposal.field.split(".", 1)[1]
        if name not in values and not proposal.protected and (before.values.get(name) in (None, "", ()) or (repair_path and origins.get(name) == "PATH")):
            values[name] = cast(MetadataValue, proposal.value)
            provenance[name] = proposal.candidate_key
    db.close()
    remote_cover = None
    cover_url = values.pop("cover_ref", None)
    if isinstance(cover_url, str):
        try:
            remote_cover = _download_remote_cover(context.target_id, cover_url, settings)
            if remote_cover:
                values["cover_ref"] = "recognition:" + task_id
        except Exception as error:  # noqa: BLE001 - isolate optional cover download and diagnose.
            record_exception(LOGGER, "metadata.remote_cover_failed", error, context={"task_id": task_id, "step": "download_remote_cover"})
    changes = (MetadataChange(context.target_type, context.target_id, before.revision, "patch" if repair_path else "fill_missing", values,
                              provenance={name: provenance[name] for name in values}),) if values else ()
    return _PreparedCandidateApplication(context.book_id, resource_id, context.target_type, context.target_id,
        task_id, fingerprint, actor, changes, remote_cover,
        tuple(context.target_type + "." + name for name in values),
        str(task.get("organizeJobId") or "") or None)


def _persist_candidate_application(db: Session, prepared: _PreparedCandidateApplication) -> None:
    if not lookup_persist.lookup_task_authorizes_target(db, prepared.task_id, prepared.book_id, prepared.resource_id):
        raise ValueError("RECOGNITION_CANCELLED")
    context = load_recognition_context(db, book_id=prepared.book_id, resource_id=prepared.resource_id, execution="AUTOMATIC")
    if context is None or recognition_fingerprint(context) != prepared.fingerprint:
        raise ValueError("RECOGNITION_CHANGED")
    covers: dict[tuple[str, str], tuple[str, str]] = {(prepared.target_type, prepared.target_id): ("recognition:" + prepared.task_id, prepared.remote_cover.relative_final_path)} if prepared.remote_cover else {}
    if prepared.changes:
        recognition_patches(db, prepared_covers=covers).stage(prepared.actor, prepared.changes, skip_unchanged=True)
    if prepared.organize_job_id:
        lookup_persist.finish_organize_job(db, prepared.organize_job_id, status="APPLIED" if prepared.applied else "COMPLETED",
                                         summary="Metadata recognition complete / 元数据识别完成", error_summary=None,
                                         set_finished_at=True, only_if_not_cancelled=True, now=_now())


def _compensate_remote_cover_publish_failure(
    db: Session,
    prepared: _PreparedCandidateApplication,
) -> None:
    remote_cover = prepared.remote_cover
    if remote_cover is None:
        return
    with MetadataWriteTransaction(db):
        application = recognition_patches(db)
        before = application.port.snapshot(prepared.target_type, prepared.target_id, prepared.actor.library_ids)
        expected = "cover:" + hashlib.sha256(remote_cover.relative_final_path.encode()).hexdigest()
        if before is not None and before.values.get("cover_ref") == expected and "cover_ref" not in before.protected:
            application.stage(prepared.actor, (MetadataChange(prepared.target_type, prepared.target_id,
                before.revision, "patch", {}, clear_fields=frozenset({"cover_ref"})),), skip_unchanged=True)


@dataclass(frozen=True, slots=True)
class _PreparedUnresolvedOrganizeUpdate:
    book_id: str | None
    organize_job_id: str | None
    message: str
    failed: bool
    now: datetime


def _prepare_unresolved_organize_update(
    db: Session, task: dict[str, Any], message: str, *, failed: bool, now: datetime
) -> _PreparedUnresolvedOrganizeUpdate:
    book = lookup_persist.get_book_organize_state(db, task.get("bookId"))
    db.close()
    already_organized = (
        bool((book or {}).get("organized"))
        or (book or {}).get("organizeStatus") == "APPLIED"
    )
    return _PreparedUnresolvedOrganizeUpdate(
        book_id=(
            str(task["bookId"])
            if book and not already_organized and task.get("bookId")
            else None
        ),
        organize_job_id=(
            str(task["organizeJobId"]) if task.get("organizeJobId") else None
        ),
        message=message,
        failed=failed,
        now=now,
    )


def _persist_unresolved_organize_update(
    db: Session, prepared: _PreparedUnresolvedOrganizeUpdate
) -> None:
    if prepared.book_id:
        lookup_persist.mark_book_reviewing(db, prepared.book_id, now=prepared.now)
    if prepared.organize_job_id:
        lookup_persist.finish_organize_job(
            db,
            prepared.organize_job_id,
            status="FAILED",
            summary=prepared.message,
            error_summary=prepared.message if prepared.failed else None,
            set_finished_at=True,
            only_if_not_cancelled=True,
            now=prepared.now,
        )


def _update_task(
    db: Session,
    task_id: str,
    *,
    updated_at: datetime,
    owner_id: str | None = None,
    **values: Any,
) -> None:
    lookup_persist.update_lookup_task(
        db,
        task_id,
        owner_id=owner_id,
        updated_at=updated_at,
        **values,
    )


def _finish_without_match(
    db: Session,
    task: dict[str, Any],
    status: str,
    candidates: list[dict[str, Any]],
    message: str,
) -> None:
    if status in {"FAILED", "NO_PROVIDER"}:
        record_exception(
            LOGGER, "metadata.lookup_rule_failed", MetadataLookupRuleFailure(message),
            context={
                "task_id": str(task["id"]), "resource_id": task.get("resourceId"),
                "book_id": task.get("bookId"), "import_task_id": task.get("importTaskId"),
                "step": "finish_lookup",
                "outcome": status, "attempt": int(task.get("attempts") or 0) + 1,
            },
            target_type="book", target_id=task.get("bookId"),
        )
    outcome = ("AMBIGUOUS" if any(match.get("outcome") == "AMBIGUOUS"
               for attempt in candidates for match in attempt.get("matches", []))
               else status)
    recognition_result = {**task.get("recognition", {}), "schemaVersion": 2,
                          "outcome": outcome, "createdAt": _now().timestamp(),
                          "retryAfter": (_now() + timedelta(hours=24)).timestamp() if outcome == "NO_MATCH" else None}
    candidate_json = json.dumps({"recognition": recognition_result, "attempted": candidates}, ensure_ascii=False)
    finished_at = _now()
    unresolved = _prepare_unresolved_organize_update(
        db,
        task,
        message,
        failed=status == "FAILED",
        now=finished_at,
    )
    task_id = str(task["id"])
    owner_id = str(task.get("leaseOwnerId") or "") or None
    error_summary = message if status in {"FAILED", "NO_PROVIDER"} else None
    with MetadataWriteTransaction(db):
        _update_task(
            db,
            task_id,
            updated_at=finished_at,
            owner_id=owner_id,
            status=status,
            candidateRawJson=candidate_json,
            errorSummary=error_summary,
            nextAttemptAt=None,
            finishedAt=finished_at,
        )
        _persist_unresolved_organize_update(db, unresolved)


def _schedule_retry(
    db: Session, task: dict[str, Any], message: str, candidates: list[dict[str, Any]],
    *, import_status: str | None = None,
) -> str:
    attempts = int(task.get("attempts") or 0) + 1
    budget = task.get("requestBudget")
    candidate_json = json.dumps({"attempted": candidates, "recognition": {
        **task.get("recognition", {}), "schemaVersion": 2, "outcome": "SOURCE_ERROR",
        "httpAttempts": budget.attempts if isinstance(budget, RecognitionRequestBudget) else 0,
        "aiAttempts": budget.ai_attempts if isinstance(budget, RecognitionRequestBudget) else 0,
    }}, ensure_ascii=False)
    now = _now()
    retry_exhausted = attempts > len(RETRY_DELAYS_SECONDS)
    if retry_exhausted:
        record_exception(
            LOGGER, "metadata.lookup_retry_limit_reached",
            MetadataLookupRetryLimitReached(
                f"Attempt {attempts} exhausted {len(RETRY_DELAYS_SECONDS)} scheduled retries; last observed result: {message}"
                + (f"; upstream import state={import_status}" if import_status is not None else "")
            ),
            context={"task_id": str(task["id"]), "resource_id": task.get("resourceId"), "book_id": task.get("bookId"), "import_task_id": task.get("importTaskId"), "step": "schedule_lookup_retry", "attempt": attempts},
            target_type="book", target_id=task.get("bookId"),
        )
    unresolved = (
        _prepare_unresolved_organize_update(
            db,
            task,
            message,
            failed=True,
            now=now,
        )
        if retry_exhausted
        else None
    )
    task_values: dict[str, Any] = (
        {
            "status": "FAILED",
            "attempts": attempts,
            "nextAttemptAt": None,
            "candidateRawJson": candidate_json,
            "errorSummary": message,
            "finishedAt": now,
        }
        if retry_exhausted
        else {
            "status": "PENDING",
            "attempts": attempts,
            "nextAttemptAt": now
            + timedelta(seconds=RETRY_DELAYS_SECONDS[attempts - 1]),
            "candidateRawJson": candidate_json,
            "errorSummary": message,
            "startedAt": None,
        }
    )
    task_id = str(task["id"])
    owner_id = str(task.get("leaseOwnerId") or "") or None
    organize_job_id = str(task.get("organizeJobId") or "") or None
    retry_summary = f"识别暂时失败，将进行第 {attempts + 1} 次尝试"
    db.close()
    with MetadataWriteTransaction(db):
        _update_task(
            db,
            task_id,
            updated_at=now,
            owner_id=owner_id,
            **task_values,
        )
        if unresolved is not None:
            _persist_unresolved_organize_update(db, unresolved)
        elif organize_job_id is not None:
            lookup_persist.mark_organize_job_retry_wait(
                db,
                organize_job_id,
                summary=retry_summary,
                error=message,
                now=now,
            )
    return "FAILED" if retry_exhausted else "PENDING"


def process_metadata_lookup_task(
    db: Session,
    settings: Settings,
    task: dict[str, Any],
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> str:
    with exception_diagnostic_boundary(LOGGER, "metadata.task_failed", context={"task_id": str(task["id"]), "attempt": int(task.get("attempts") or 0) + 1}):
        try:
            import_status = lookup_persist.get_import_task_status(db, task.get("importTaskId"))
            if import_status is not None and import_status != "SUCCEEDED":
                return _schedule_retry(db, task, "等待本地导入任务完成", [], import_status=import_status)
            book = lookup_persist.get_book(db, task.get("bookId"))
            if not book:
                _finish_without_match(db, task, "FAILED", [], "图书已不存在")
                return "FAILED"
            metadata_guard = lookup_persist.book_metadata_guard(db, str(book["id"]))
            if metadata_guard is not None and metadata_guard[-1]:
                task_id = str(task["id"])
                now = _now()
                owner_id = str(task.get("leaseOwnerId") or "") or None
                db.close()
                with MetadataWriteTransaction(db):
                    _update_task(
                        db,
                        task_id,
                        updated_at=now,
                        owner_id=owner_id,
                        status="PENDING",
                        startedAt=None,
                        leaseOwnerId=None,
                        leaseExpiresAt=None,
                    )
                return "PENDING"
            if lookup_persist.local_identification_failed(db, str(book["id"])):
                _finish_without_match(db, task, "FAILED", [], "本地元数据识别失败，请重试识别")
                return "FAILED"
            context = metadata_context_for_book(db, str(book["id"]))
            if not context:
                _finish_without_match(
                    db,
                    task,
                    "FAILED",
                    [],
                    "无法建立元数据查询上下文",
                )
                return "FAILED"
            # Existing automatic tasks apply to Book. Their representative
            # resource is an import/writeback reference, never Book identity.
            persisted_result = json.loads(task.get("candidateRawJson") or "{}")
            declared_target = persisted_result.get("recognition", {}) if isinstance(persisted_result, dict) else {}
            explicit_resource = declared_target.get("targetType") == "resource"
            if explicit_resource and (not task.get("resourceId") or declared_target.get("targetId") != task["resourceId"]):
                _finish_without_match(db, task, "FAILED", [], "RECOGNITION_TARGET_DELETED")
                return "FAILED"
            recognition = load_recognition_context(
                db, book_id=str(book["id"]),
                resource_id=str(task["resourceId"]) if explicit_resource else None,
                execution="AUTOMATIC"
            )
            if recognition is None:
                _finish_without_match(db, task, "FAILED", [], "无法建立元数据查询上下文")
                return "FAILED"
            if explicit_resource:
                context = provider_context(db, recognition)
            task["recognition"] = {
                "fingerprint": recognition_fingerprint(recognition),
                "targetType": recognition.target_type, "targetId": recognition.target_id,
                "revision": recognition.revision, "relatedRevision": recognition.related_revision,
                "configRevision": recognition.config_revision,
            }
            no_match_message = (
                "No candidate has sufficient, conflict-free identity evidence"
                if configured_locale(db) == "en-US"
                else "未找到身份依据充分且无冲突的候选"
            )
            def request_active() -> bool:
                try:
                    return lookup_persist.lookup_task_is_active(db, str(task["id"]))
                finally:
                    db.close()

            previous = json.loads(task.get("candidateRawJson") or "{}")
            prior_record = previous.get("recognition", {}) if isinstance(previous, dict) else {}
            effective_request_gate = RecognitionRequestBudget(
                request_active, int(prior_record.get("httpAttempts") or 0),
                int(prior_record.get("aiAttempts") or 0))
            task["requestBudget"] = effective_request_gate

            enabled_providers = 0
            errors: list[str] = []
            inspected: list[dict[str, Any]] = []
            providers = _provider_order(task)
            attempts: list[tuple[str, str | None]] = [(provider, None) for provider in providers]
            attempts.append(("ai", None))
            enabled_sources: list[str] = []
            ai_candidates: list[dict[str, Any]] = []
            for provider_index, (provider, query_override) in enumerate(attempts):
                if provider == "ai":
                    if not enabled_sources:
                        continue
                    execution_id = _start_provider_execution(db, task, provider)
                    try:
                        advice = search_with_metadata_provider(db, {**context, "aiCandidates": ai_candidates[:5]}, "ai", automatic_request_gate=effective_request_gate)
                        assistance = advice.get("assistance")
                        if isinstance(assistance, dict):
                            task["recognition"]["aiAssistance"] = assistance
                            if assistance.get("purpose") == "query":
                                # Hints change the query only, never target identity or aliases.
                                attempts.extend((enabled_sources[0], hint["query"]) for hint in assistance.get("queryHints", [])[:2])
                        _finish_provider_execution(db, execution_id, status="COMPLETED" if assistance else "SKIPPED", result=advice)
                    except RecognitionRequestStopped as error:
                        _finish_provider_execution(db, execution_id, status="SKIPPED", result={"reason": str(error)})
                    except Exception as error:  # noqa: BLE001 - optional AI failure keeps the ordinary rule result.
                        record_exception(LOGGER, "metadata.ai_assistance_failed", error, context={"task_id": str(task["id"]), "step": "assist"})
                        _finish_provider_execution(db, execution_id, status="FAILED", error=provider_error_code(error))
                    task["recognition"].update(httpAttempts=effective_request_gate.attempts, aiAttempts=effective_request_gate.ai_attempts)
                    continue
                execution_id = _start_provider_execution(db, task, provider)
                try:
                    result = _search_provider(
                        db,
                        context,
                        provider,
                        query_override,
                        effective_request_gate,
                    )
                except RecognitionRequestStopped as exc:
                    _finish_provider_execution(db, execution_id, status="SKIPPED",
                                               result={"reason": str(exc)})
                    inspected.append({"provider": provider, "reason": str(exc), "matches": []})
                    if "BUDGET" in str(exc) or str(exc) == "CANCELLED":
                        break
                    continue
                except Exception as exc:  # noqa: BLE001 - contains one provider attempt.
                    record_exception(logging.getLogger(__name__), "services.metadata_lookup_queue.process_metadata_lookup_task.failed", exc,
                                     context={"step": "process_metadata_lookup_task", "task_id": str(task.get("id") or ""), "attempt": int(task.get("attempts") or 0) + 1})
                    _finish_provider_execution(
                        db, execution_id, status="FAILED", error=provider_error_code(exc)
                    )
                    inspected.append({"provider": provider, "errorCode": provider_error_code(exc), "matches": []})
                    errors.append(f"{provider}: {provider_error_code(exc)}")
                    continue
                if result.get("error"):
                    errors.append(f"{provider}: PROVIDER_ERROR")
                    _finish_provider_execution(db, execution_id, status="FAILED", error="PROVIDER_ERROR")
                    continue
                task["recognition"].update(httpAttempts=effective_request_gate.attempts,
                                           aiAttempts=effective_request_gate.ai_attempts)
                if not result.get("enabled"):
                    _finish_provider_execution(
                        db, execution_id, status="SKIPPED", result=result
                    )
                    continue
                enabled_providers += 1
                if provider not in enabled_sources:
                    enabled_sources.append(provider)
                raw_candidates = result.get("candidates")
                candidates: list[dict[str, Any]] = (
                    [
                        {str(key): value for key, value in candidate.items()}
                        for candidate in raw_candidates[:10]
                        if isinstance(candidate, dict)
                    ]
                    if isinstance(raw_candidates, list)
                    else []
                )
                assessed = assess_candidates(recognition, provider, candidates)
                ai_candidates.extend({**candidate_summary(item), "source": provider} for item, decision in assessed if decision.outcome == "AMBIGUOUS" and len(ai_candidates) < 5)
                selected = next(
                    ((item, decision) for item, decision in assessed if decision.outcome == "MATCHED"),
                    None,
                )
                candidate = selected[0] if selected else None
                inspected.append(
                    {
                        "provider": provider,
                        "exactCandidates": [
                            candidate_summary(item) for item, _ in assessed
                            if metadata_candidate_title_exact_match(recognition.identity.title, item)
                        ],
                        "matches": [match_view(decision) for _, decision in assessed],
                        "cacheHit": bool(result.get("cacheHit")),
                    }
                )
                if not candidate:
                    _finish_provider_execution(
                        db, execution_id, status="NO_MATCH", result=result
                    )
                    continue
                if not lookup_persist.lookup_task_is_active(db, str(task["id"])):
                    return "CANCELLED"
                prepared_application: _PreparedCandidateApplication | None = None
                try:
                    supplement = None
                    # At most one further source, and only for missing allowed fields.
                    missing = selected[1].allowed_fields - {proposal.field for proposal in propose_fields(recognition, provider, candidate, selected[1])} if selected else frozenset()
                    extra_provider = next((item for item in providers[provider_index + 1:] if item not in {"ai", "open-library"}), None)
                    if missing and extra_provider:
                        try:
                            extra = _search_provider(db, context, extra_provider,
                                next(iter(recognition_queries(context, extra_provider)), ""), effective_request_gate)
                            extra_candidates = extra.get("candidates") or []
                            if extra.get("enabled") and not extra.get("error"):
                                extra_assessed = assess_candidates(recognition, extra_provider, extra_candidates[:10])
                                extra_selected = next((item for item, decision in extra_assessed if decision.outcome == "MATCHED"), None)
                                if extra_selected is not None:
                                    supplement = (extra_provider, extra_selected)
                                inspected.append({"provider": extra_provider, "supplement": True,
                                    "matches": [match_view(decision) for _, decision in extra_assessed]})
                        except RecognitionRequestStopped:
                            pass  # Cancellation is checked again before applying; budget exhaustion merely ends supplementation.
                        except Exception as error:  # noqa: BLE001 - optional source failure is diagnosed before using primary fields.
                            record_exception(LOGGER, "metadata.supplement_failed", error, context={"task_id": str(task["id"]), "step": "supplement"})
                        task["recognition"].update(httpAttempts=effective_request_gate.attempts, aiAttempts=effective_request_gate.ai_attempts)
                    prepared_application = _prepare_candidate_application(db, settings, task, provider, candidate, supplement)
                    applied = list(prepared_application.applied)
                    selected_result_json = json.dumps(
                        { "selected": candidate_summary(candidate), "attempted": inspected,
                         "proposals": [asdict(item) for item in propose_fields(recognition, provider, candidate, selected[1])] if selected else [],
                         "recognition": {**task["recognition"], "schemaVersion": 2,
                                         "outcome": "APPLIED" if applied else "NO_CHANGES",
                                         "createdAt": _now().timestamp()}},
                        ensure_ascii=False, default=str,
                    )
                    applied_fields_json = json.dumps(applied, ensure_ascii=False)
                    finished_at = _now()
                    execution_result = {
                        "selected": candidate_summary(candidate),
                        "appliedFields": applied,
                    }
                    execution_result_json = json.dumps(
                        execution_result,
                        ensure_ascii=False,
                    )
                    completed_attempts = int(task.get("attempts") or 0) + 1
                    prepared_execution_finish = (
                        lookup_persist.prepare_provider_execution_finish(
                            execution_id,
                            status="COMPLETED",
                            raw_result_json=execution_result_json,
                            now=finished_at,
                        )
                    )
                    task_id = str(task["id"])
                    owner_id = str(task.get("leaseOwnerId") or "") or None
                    guarded_book_id = str(book["id"])
                    with MetadataWriteTransaction(db):
                        if (
                            lookup_persist.book_metadata_guard(db, guarded_book_id)
                            != metadata_guard
                        ):
                            raise RuntimeError("BOOK_METADATA_CHANGED")
                        _persist_candidate_application(db, prepared_application)
                    if prepared_application.remote_cover is not None:
                        try:
                            _publish_remote_cover(prepared_application.remote_cover)
                        except OSError as publish_error:
                            primary_id = record_exception(LOGGER, "metadata.cover_publish_failed", publish_error, context={"task_id": str(task["id"]), "step": "publish_cover"})
                            try:
                                _compensate_remote_cover_publish_failure(
                                    db,
                                    prepared_application,
                                )
                            except Exception as compensation_error:
                                record_exception(LOGGER, "metadata.cover_compensation_failed", compensation_error, context={"task_id": str(task["id"]), "step": "compensate_cover", "parent_diagnostic_id": primary_id})
                                raise RuntimeError(
                                    "REMOTE_COVER_PUBLISH_COMPENSATION_FAILED"
                                ) from compensation_error
                            applied = [field for field in applied if not field.endswith(".cover_ref")]
                            completed = json.loads(selected_result_json)
                            completed["recognition"].update(coverStatus="FAILED", outcome="APPLIED" if applied else "NO_CHANGES")
                            selected_result_json = json.dumps(completed, ensure_ascii=False)
                            applied_fields_json = json.dumps(applied, ensure_ascii=False)
                    with MetadataWriteTransaction(db):
                        _update_task(
                            db,
                            task_id,
                            updated_at=finished_at,
                            owner_id=owner_id,
                            status="COMPLETED",
                            attempts=completed_attempts,
                            nextAttemptAt=None,
                            resultSource=provider,
                            candidateRawJson=selected_result_json,
                            appliedFields=applied_fields_json,
                            errorSummary=None,
                            finishedAt=finished_at,
                        )
                        lookup_persist.write_prepared_provider_execution(
                            db, prepared_execution_finish
                        )
                    try:
                        if applied:
                            recognition_writeback(db, str(book["id"]), prepared_application.resource_id,
                                                  source="AUTOMATIC", task_id=task_id)
                    except Exception as writeback_error:  # noqa: BLE001 - DB success must not be replayed after optional OPF failure.
                        record_exception(LOGGER, "metadata.writeback_enqueue_failed", writeback_error,
                                         context={"task_id": task_id, "step": "enqueue_writeback", "outcome": "database_applied"})
                        db.rollback()
                        completed = json.loads(selected_result_json)
                        completed["recognition"]["writebackStatus"] = "FAILED"
                        with MetadataWriteTransaction(db):
                            _update_task(db, task_id, updated_at=_now(), candidateRawJson=json.dumps(completed, ensure_ascii=False))
                    return "COMPLETED"
                except Exception as exc:  # noqa: BLE001 - contains candidate application.
                    record_exception(logging.getLogger(__name__), "services.metadata_lookup_queue.process_metadata_lookup_task.failed", exc,
                                     context={"step": "process_metadata_lookup_task", "task_id": str(task.get("id") or ""), "attempt": int(task.get("attempts") or 0) + 1})
                    _discard_remote_cover(
                        prepared_application.remote_cover
                        if prepared_application is not None
                        else None
                    )
                    _finish_provider_execution(
                        db, execution_id, status="FAILED", error=f"apply: {exc}"
                    )
                    errors.append(f"{provider} apply: {exc}")

            if enabled_providers == 0 and not errors:
                if not lookup_persist.lookup_task_is_active(db, str(task["id"])):
                    return "CANCELLED"
                _finish_without_match(
                    db,
                    task,
                    "NO_PROVIDER",
                    inspected,
                    "所有适用的元数据插件均未启用",
                )
                return "NO_PROVIDER"
            if errors:
                if not lookup_persist.lookup_task_is_active(db, str(task["id"])):
                    return "CANCELLED"
                _schedule_retry(db, task, "；".join(errors), inspected)
                refreshed_status = lookup_persist.get_lookup_task_status(db, str(task["id"]))
                return str(refreshed_status or "FAILED")
            if not lookup_persist.lookup_task_is_active(db, str(task["id"])):
                return "CANCELLED"
            _finish_without_match(
                db, task, "NO_MATCH", inspected, no_match_message
            )
            return "NO_MATCH"
        finally:
            db.close()


def process_next_metadata_lookup_task(
    db: Session,
    settings: Settings,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
    *,
    owner_id: str = "metadata-lookup-compat",
    prefer_writeback: bool = False,
    prefer_preparation: bool = True,
    lookup_ready: bool = True,
    writeback_ready: bool = True,
    standard_handler: Callable[[Session, dict[str, Any], str], None] | None = None,
) -> bool:
    if (
        writeback_ready
        and prefer_writeback
        and process_next_metadata_writeback(
            db,
            settings,
            owner_id=owner_id,
            prefer_preparation=prefer_preparation,
            standard_handler=standard_handler,
        )
    ):
        return True
    task = (
        claim_next_metadata_lookup_task(db, owner_id=owner_id) if lookup_ready else None
    )
    if task:
        process_metadata_lookup_task(db, settings, task, automatic_request_gate)
        return True
    return writeback_ready and process_next_metadata_writeback(
        db,
        settings,
        owner_id=owner_id,
        prefer_preparation=prefer_preparation,
        standard_handler=standard_handler,
    )


@dataclass
class _MetadataRecovery:
    ready: bool = False
    attempts: int = 0
    next_attempt: float = 0.0
    error: str | None = None


class MetadataLookupWorker:
    def __init__(
        self,
        db_factory: Callable[[], Session],
        settings: Settings,
        poll_seconds: float = 2.0,
        heartbeat_db_factory: Callable[[], Session] | None = None,
        automatic_request_gate: AutomaticMetadataRequestGate | None = None,
        standard_handler: Callable[[Session, dict[str, Any], str], None] | None = None,
        standard_maintenance: Callable[[Session], None] | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._settings = settings
        self._poll_seconds = poll_seconds
        self._automatic_request_gate = automatic_request_gate
        self._standard_handler = standard_handler
        self._standard_maintenance = standard_maintenance
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="metadata-lookup-worker", daemon=True
        )
        self._instance_id = f"metadata-{uuid4().hex}"
        self._prefer_writeback = False
        self._prefer_preparation = True
        self._lookup_recovery = _MetadataRecovery()
        self._writeback_recovery = _MetadataRecovery()
        self._next_maintenance = 0.0
        self._maintenance_cursor: str | None = None
        self._heartbeat = QueueHeartbeatPump(
            heartbeat_db_factory or db_factory,
            queue_name="metadata",
            instance_id=self._instance_id,
            poll_interval_seconds=poll_seconds,
        )

    def start(self) -> None:
        self._thread.start()

    def _recover(
        self, state: _MetadataRecovery, operation: Callable[[Session], int], name: str
    ) -> None:
        if state.ready or self._stop.is_set() or monotonic() < state.next_attempt:
            return
        try:
            with self._db_factory() as db:
                operation(db)
        except Exception as exc:  # noqa: BLE001 - this component remains gated.
            state.attempts += 1
            retry = is_database_busy_error(exc) or is_database_operation_timeout(exc)
            state.next_attempt = (
                monotonic() + min(300.0, 5.0 * 2 ** min(state.attempts - 1, 6))
                if retry
                else float("inf")
            )
            state.error = (
                f"{name}:{'retrying' if retry else 'paused'}:{type(exc).__name__}"
            )
            record_exception(
                LOGGER,
                "metadata.recovery_failed",
                exc,
                context={"stage": name, "outcome": "retrying" if retry else "paused"},
                source="metadata",
                action="metadata.recovery_failed",
            )
        else:
            state.ready = True
            state.error = None

    def _maintain(self) -> None:
        if (
            not self._writeback_recovery.ready
            or self._stop.is_set()
            or monotonic() < self._next_maintenance
        ):
            return
        self._next_maintenance = monotonic() + 300.0
        try:
            with self._db_factory() as db:
                if self._standard_maintenance is not None:
                    self._standard_maintenance(db)
                self._maintenance_cursor = maintain_metadata_writebacks(
                    db, self._settings, after_id=self._maintenance_cursor
                )
        except Exception as exc:  # noqa: BLE001 - maintenance cannot revoke readiness.
            record_exception(
                LOGGER,
                "metadata.maintenance_deferred",
                exc,
                context={"stage": "maintenance", "outcome": "deferred"},
                source="metadata",
                action="metadata.maintenance_deferred",
            )

    def request_stop(self) -> None:
        self._stop.set()

    def shutdown(self) -> None:
        self.request_stop()
        if self._thread.is_alive():
            self._thread.join()

    def _process_iteration(
        self, *, lookup_ready: bool = True, writeback_ready: bool = True
    ) -> bool | None:
        with exception_diagnostic_boundary(LOGGER, "metadata.iteration_failed", context={}):
            prefer_writeback = self._prefer_writeback
            prefer_preparation = self._prefer_preparation
            self._prefer_writeback = not self._prefer_writeback
            self._prefer_preparation = not self._prefer_preparation
            for attempt in range(len(DATABASE_BUSY_RETRY_DELAYS_SECONDS) + 1):
                if attempt and self._stop.wait(
                    DATABASE_BUSY_RETRY_DELAYS_SECONDS[attempt - 1]
                ):
                    return None
                try:
                    with self._db_factory() as db:
                        return bool(
                            process_next_metadata_lookup_task(
                                db,
                                self._settings,
                                self._automatic_request_gate,
                                owner_id=self._instance_id,
                                prefer_writeback=prefer_writeback,
                                prefer_preparation=prefer_preparation,
                                lookup_ready=lookup_ready,
                                writeback_ready=writeback_ready,
                                standard_handler=self._standard_handler,
                            )
                        )
                except OperationalError as error:
                    record_exception(LOGGER, "metadata.database_attempt_failed", error, context={"step": "iteration", "attempt": attempt + 1})
                    if not is_database_busy_error(error) or attempt == len(
                        DATABASE_BUSY_RETRY_DELAYS_SECONDS
                    ):
                        raise
            raise AssertionError("metadata retry loop exhausted")

    def _record_iteration_error(self, error: BaseException) -> None:
        record_exception(
            LOGGER, "metadata.iteration_failed", error,
            context={"step": "iteration", "outcome": "retrying" if is_database_busy_error(error) else "paused"},
            source="metadata",
        )

    def _run(self) -> None:
        self._heartbeat.start()
        try:
            self._heartbeat.pulse(status="recovering")
            while not self._stop.is_set():
                self._recover(
                    self._lookup_recovery, recover_stale_metadata_lookup_tasks, "lookup"
                )
                self._recover(
                    self._writeback_recovery,
                    recover_interrupted_metadata_writebacks,
                    "writeback",
                )
                if self._stop.is_set():
                    break
                worked = False
                for name, state in (
                    ("lookup", self._lookup_recovery),
                    ("writeback", self._writeback_recovery),
                ):
                    if self._stop.is_set():
                        break
                    if not state.ready or monotonic() < state.next_attempt:
                        continue
                    try:
                        iteration_result = self._process_iteration(
                            lookup_ready=name == "lookup",
                            writeback_ready=name == "writeback",
                        )
                        worked = bool(iteration_result) or worked
                        state.error = None
                    except Exception as exc:  # noqa: BLE001 - only the failed path pauses.
                        self._record_iteration_error(exc)
                        retry = is_database_busy_error(exc)
                        state.error = f"{name}:{'retrying' if retry else 'paused'}:{type(exc).__name__}"
                        state.next_attempt = monotonic() + 60 if retry else float("inf")
                        if not retry:
                            state.ready = False
                self._heartbeat.pulse(
                    status="running"
                    if self._lookup_recovery.ready
                    and self._writeback_recovery.ready
                    and not self._lookup_recovery.error
                    and not self._writeback_recovery.error
                    else "degraded",
                    processed=worked,
                    error=self._lookup_recovery.error or self._writeback_recovery.error,
                )
                self._maintain()
                if not worked:
                    self._stop.wait(self._poll_seconds)
        finally:
            self._heartbeat.stop()
