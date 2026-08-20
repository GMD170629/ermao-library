from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic, time
from typing import Any
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.bootstrap.library import (
    PreparedWorkFacetWrite,
    execute_work_facet_write,
    load_work_facet_projections,
    prepare_work_facet_write,
)
from app.core.config import Settings
from app.core.database_errors import is_database_busy_error
from app.models.common import db_timestamp
from app.modules.library.public import prepare_work_facet
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.application.rate_limits import AutomaticMetadataRequestGate
from app.modules.metadata.application.writeback import (
    prepare_metadata_writeback_intents,
)
from app.modules.metadata.infrastructure import lookup_queue as lookup_persist
from app.modules.metadata.infrastructure import writeback_queue
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    normalize_identity_part,
)
from app.services.metadata_file_writeback import (
    process_next_metadata_writeback,
    recover_interrupted_metadata_writebacks,
)
from app.services.metadata_provider_registry import (
    metadata_provider_registry,
    search_with_metadata_provider,
)
from app.services.organize_service import (
    metadata_candidate_title_exact_match,
    metadata_context_for_work,
)
from app.services.queue_runtime import QueueHeartbeatPump

LOGGER = logging.getLogger(__name__)
RETRY_DELAYS_SECONDS = (60, 300, 1800)
DATABASE_BUSY_RETRY_DELAYS_SECONDS = (0.25, 1.0)
DATABASE_BUSY_LOG_INTERVAL_SECONDS = 30.0
STALE_RUNNING_MINUTES = lookup_persist.STALE_RUNNING_MINUTES
ORPHAN_COVER_PART_MAX_AGE_SECONDS = 24 * 60 * 60


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
    organize_job_ready = lookup_persist.organize_job_table_ready(db)
    db.close()
    now = _now()
    lease_expires_at = now + timedelta(seconds=lookup_persist.LOOKUP_LEASE_SECONDS)
    with MetadataWriteTransaction(db):
        task = lookup_persist.claim_next_lookup_task(
            db,
            owner_id=owner_id,
            now=now,
            lease_expires_at=lease_expires_at,
            organize_job_ready=organize_job_ready,
        )
    return task


def _provider_order(task: dict[str, Any]) -> list[str]:
    try:
        parsed = json.loads(str(task.get("providerOrder") or "[]"))
    except json.JSONDecodeError:
        parsed = []
    registered = metadata_provider_registry().ids()
    return [str(item) for item in parsed if str(item) in registered]


def _search_provider(
    db: Session,
    context: dict[str, Any],
    provider: str,
    query: str,
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
    table_ready = lookup_persist.provider_execution_table_ready(db)
    db.close()
    prepared = lookup_persist.prepare_provider_execution_start(
        task,
        provider,
        execution_id=execution_id,
        attempts=attempts,
        now=now,
        table_ready=table_ready,
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
        json.dumps(result, ensure_ascii=False) if result is not None else None
    )
    now = _now()
    table_ready = lookup_persist.provider_execution_table_ready(db)
    db.close()
    prepared = lookup_persist.prepare_provider_execution_finish(
        execution_id,
        status=status,
        raw_result_json=raw_result_json,
        error=error,
        now=now,
        table_ready=table_ready,
    )
    with MetadataWriteTransaction(db):
        lookup_persist.write_prepared_provider_execution(db, prepared)


def _choose_exact_candidate(
    candidates: list[dict[str, Any]], title: str, author: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    exact = [
        candidate
        for candidate in candidates
        if metadata_candidate_title_exact_match(title, candidate)
    ]
    if len(exact) == 1:
        return exact[0], exact
    if len(exact) > 1 and normalize_identity_part(author) != normalize_identity_part(
        UNKNOWN_AUTHOR
    ):
        author_key = normalize_identity_part(author)
        author_matches = [
            candidate
            for candidate in exact
            if normalize_identity_part(candidate.get("author")) == author_key
        ]
        if len(author_matches) == 1:
            return author_matches[0], exact
    return None, exact


def _parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return _parse_tags(parsed)
    return []


def _local_cover_exists(
    db: Session, work: dict[str, Any], volume_id: str | None
) -> bool:
    if str(work.get("coverPath") or "").strip():
        return True
    if not volume_id:
        return False
    volume = lookup_persist.get_volume(db, volume_id)
    if str((volume or {}).get("coverPath") or "").strip():
        return True
    return lookup_persist.volume_has_cover(db, volume_id)


@dataclass(frozen=True, slots=True)
class _PreparedRemoteCover:
    temporary_path: Path
    final_path: Path
    relative_final_path: str


def _cleanup_orphan_remote_cover_parts(
    target_dir: Path,
    *,
    work_id: str,
    current_time: float | None = None,
) -> int:
    cutoff = (time() if current_time is None else current_time) - (
        ORPHAN_COVER_PART_MAX_AGE_SECONDS
    )
    removed = 0
    for part_path in target_dir.glob(f".{work_id}-remote-*.part"):
        try:
            if part_path.stat().st_mtime > cutoff:
                continue
            part_path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            LOGGER.debug("orphan remote cover cleanup skipped path=%s", part_path)
    return removed


def _validated_remote_cover_suffix(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("REMOTE_COVER_INVALID")


def _download_remote_cover(
    work_id: str, cover_url: str, settings: Settings
) -> _PreparedRemoteCover | None:
    if not cover_url.startswith(("http://", "https://")):
        return None
    request = UrlRequest(
        cover_url,
        headers={
            "Accept": "image/*",
            "User-Agent": "ShukuStarship/0.1 metadata-worker",
        },
    )
    with urlopen(request, timeout=20) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024 or not data:
        raise ValueError("REMOTE_COVER_INVALID")
    suffix = _validated_remote_cover_suffix(data)
    target_dir = settings.resolved_storage_root / "covers"
    target_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_orphan_remote_cover_parts(target_dir, work_id=work_id)
    final_path = target_dir / f"{work_id}-remote-{uuid4().hex}{suffix}"
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
    except OSError:
        prepared.temporary_path.unlink(missing_ok=True)
        raise


def _discard_remote_cover(prepared: _PreparedRemoteCover | None) -> None:
    if prepared is not None:
        prepared.temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class _PreparedCandidateApplication:
    work_id: str
    volume_id: str | None
    work_patch: dict[str, Any]
    volume_patch: dict[str, Any]
    organize_job_id: str | None
    organize_job_status: str
    organize_job_summary: str
    library_metadata_json: str | None
    library_metadata_id: str | None
    now: datetime
    facet_write: PreparedWorkFacetWrite
    remote_cover: _PreparedRemoteCover | None
    applied: tuple[str, ...]


def _prepare_candidate_application(
    db: Session,
    settings: Settings,
    task: dict[str, Any],
    provider: str,
    candidate: dict[str, Any],
) -> _PreparedCandidateApplication:
    work = lookup_persist.get_work(db, str(task["workId"]))
    if not work:
        raise ValueError("作品已不存在")
    facet_projections = load_work_facet_projections(db, (str(work["id"]),))
    if len(facet_projections) != 1:
        raise ValueError("WORK_FACET_PROJECTION_NOT_FOUND")
    volume_id = str(task.get("volumeId") or "") or None
    volume = lookup_persist.get_volume(db, volume_id) if volume_id else None
    prefer_local = lookup_persist.prefer_local_metadata_enabled(db)
    local_cover_exists = _local_cover_exists(db, work, volume_id)

    # End every projection read before parsing provider data, downloading a
    # cover or constructing the prepared SQL statements for the write phase.
    db.close()
    work_patch: dict[str, Any] = {}
    volume_patch: dict[str, Any] = {}
    applied: list[str] = []
    remote_cover: _PreparedRemoteCover | None = None

    candidate_title = str(candidate.get("title") or "").strip()
    candidate_author = str(candidate.get("author") or "").strip()
    current_title = str(work.get("title") or "").strip()
    current_author = str(work.get("author") or "").strip()
    if (
        candidate_title
        and candidate_title != current_title
        and (not prefer_local or not current_title)
    ):
        work_patch["title"] = candidate_title
        applied.append("title")
    local_author_is_missing = not current_author or current_author in {
        UNKNOWN_AUTHOR,
        "unknown",
        "Unknown",
    }
    if (
        candidate_author
        and candidate_author != current_author
        and (not prefer_local or local_author_is_missing)
    ):
        work_patch["author"] = candidate_author
        applied.append("author")
    if (not prefer_local or not str(work.get("description") or "").strip()) and str(
        candidate.get("description") or ""
    ).strip():
        work_patch["description"] = str(candidate["description"]).strip()
        applied.append("description")
    candidate_tags = _parse_tags(candidate.get("tags"))
    if candidate_tags and (not prefer_local or not _parse_tags(work.get("tags"))):
        work_patch["tags"] = json.dumps(
            list(dict.fromkeys(candidate_tags)), ensure_ascii=False
        )
        applied.append("tags")
    if (not prefer_local or not str(work.get("seriesName") or "").strip()) and str(
        candidate.get("seriesName") or ""
    ).strip():
        work_patch["seriesName"] = str(candidate["seriesName"]).strip()
        applied.append("seriesName")
    if (not prefer_local or work.get("seriesIndex") is None) and candidate.get(
        "seriesIndex"
    ) is not None:
        try:
            work_patch["seriesIndex"] = float(candidate["seriesIndex"])
            applied.append("seriesIndex")
        except (TypeError, ValueError):
            pass
    volume_metadata = candidate.get("volumeMetadata")
    if not isinstance(volume_metadata, dict):
        volume_metadata = {
            key: candidate.get(key)
            for key in ("publisher", "publishedAt", "language", "isbn")
        }
    if volume:
        if (not prefer_local or volume.get("publishedAt") is None) and isinstance(
            volume_metadata.get("publishedAt"), str
        ):
            try:
                published_at = datetime.fromisoformat(
                    str(volume_metadata["publishedAt"])
                )
            except ValueError:
                published_at = None
            if published_at is not None:
                volume_patch["publishedAt"] = published_at
                applied.append("publishedAt")
        for field in ("publisher", "language", "isbn"):
            value = str(volume_metadata.get(field) or "").strip()
            if value and (not prefer_local or not str(volume.get(field) or "").strip()):
                volume_patch[field] = value
                applied.append(field)
    if (not prefer_local or not local_cover_exists) and str(
        candidate.get("coverUrl") or ""
    ).strip():
        try:
            remote_cover = _download_remote_cover(
                str(work["id"]), str(candidate["coverUrl"]).strip(), settings
            )
        except Exception as exc:  # noqa: BLE001 - optional cover failure is isolated.
            LOGGER.warning("remote metadata cover skipped work=%s: %s", work["id"], exc)
        else:
            if remote_cover:
                work_patch.update(
                    {
                        "coverPath": remote_cover.relative_final_path,
                        "coverStatus": "READY",
                    }
                )
                applied.append("cover")

    if "title" in work_patch or "author" in work_patch:
        title = str(work_patch.get("title", work.get("title")) or "").strip()
        author = (
            str(work_patch.get("author", work.get("author")) or "").strip()
            or UNKNOWN_AUTHOR
        )
        work_patch.update(
            {
                "normalizedTitle": normalize_identity_part(title),
                "normalizedAuthor": normalize_identity_part(author),
            }
        )

    now = _now()
    work_patch.update(
        {
            "metadataQuality": max(
                int(work.get("metadataQuality") or 0), 85 if applied else 80
            ),
            "organized": True,
            "organizeStatus": "APPLIED",
            "updatedAt": now,
        }
    )
    if volume and volume_patch:
        volume_patch["updatedAt"] = now

    job_id = str(task.get("organizeJobId") or "") or None
    organize_job_summary = (
        f"已从 {provider} 自动应用 {len(applied)} 项元数据"
        if applied
        else f"已从 {provider} 完成识别，现有元数据无需更新"
    )
    library_metadata_json = (
        json.dumps(
            {"candidate": candidate, "appliedFields": applied},
            ensure_ascii=False,
        )
        if volume_id
        else None
    )
    final_facet_projection = replace(
        facet_projections[0],
        author=(
            str(work_patch.get("author"))
            if work_patch.get("author") is not None
            else facet_projections[0].author
        ),
        tags_source=str(work_patch.get("tags", facet_projections[0].tags_source)),
        series_name=(
            str(work_patch.get("seriesName"))
            if work_patch.get("seriesName") is not None
            else facet_projections[0].series_name
        ),
    )
    facet_write = prepare_work_facet_write(
        (prepare_work_facet(final_facet_projection),),
        now=now,
    )
    return _PreparedCandidateApplication(
        work_id=str(work["id"]),
        volume_id=volume_id,
        work_patch=work_patch,
        volume_patch=volume_patch,
        organize_job_id=job_id,
        organize_job_status="APPLIED" if applied else "COMPLETED",
        organize_job_summary=organize_job_summary,
        library_metadata_json=library_metadata_json,
        library_metadata_id=f"py_{uuid4().hex}" if library_metadata_json else None,
        now=now,
        facet_write=facet_write,
        remote_cover=remote_cover,
        applied=tuple(applied),
    )


def _persist_candidate_application(
    db: Session,
    prepared: _PreparedCandidateApplication,
    provider: str,
) -> None:
    lookup_persist.update_work(db, prepared.work_id, prepared.work_patch)
    if prepared.volume_id and prepared.volume_patch:
        lookup_persist.update_volume(
            db,
            prepared.volume_id,
            prepared.volume_patch,
        )
    execute_work_facet_write(db, prepared.facet_write)
    if prepared.organize_job_id:
        lookup_persist.finish_organize_job(
            db,
            prepared.organize_job_id,
            status=prepared.organize_job_status,
            summary=prepared.organize_job_summary,
            error_summary=None,
            set_finished_at=True,
            now=prepared.now,
        )
    if (
        prepared.library_metadata_json is not None
        and prepared.library_metadata_id is not None
        and prepared.volume_id is not None
    ):
        lookup_persist.insert_library_metadata(
            db,
            volume_id=prepared.volume_id,
            source=provider,
            raw_json=prepared.library_metadata_json,
            metadata_id=prepared.library_metadata_id,
            now=prepared.now,
        )


def _compensate_remote_cover_publish_failure(
    db: Session,
    prepared: _PreparedCandidateApplication,
) -> None:
    remote_cover = prepared.remote_cover
    if remote_cover is None:
        return
    now = _now()
    with MetadataWriteTransaction(db):
        lookup_persist.clear_remote_cover_if_current(
            db,
            prepared.work_id,
            cover_path=remote_cover.relative_final_path,
            now=now,
        )


@dataclass(frozen=True, slots=True)
class _PreparedUnresolvedOrganizeUpdate:
    work_id: str | None
    organize_job_id: str | None
    message: str
    failed: bool
    now: datetime


def _prepare_unresolved_organize_update(
    db: Session, task: dict[str, Any], message: str, *, failed: bool, now: datetime
) -> _PreparedUnresolvedOrganizeUpdate:
    work = lookup_persist.get_work_organize_state(db, task.get("workId"))
    db.close()
    already_organized = (
        bool((work or {}).get("organized"))
        or (work or {}).get("organizeStatus") == "APPLIED"
    )
    return _PreparedUnresolvedOrganizeUpdate(
        work_id=(
            str(task["workId"])
            if work and not already_organized and task.get("workId")
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
    if prepared.work_id:
        lookup_persist.mark_work_reviewing(db, prepared.work_id, now=prepared.now)
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
    candidate_json = json.dumps(candidates, ensure_ascii=False)
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
    db: Session, task: dict[str, Any], message: str, candidates: list[dict[str, Any]]
) -> None:
    attempts = int(task.get("attempts") or 0) + 1
    candidate_json = json.dumps(candidates, ensure_ascii=False)
    now = _now()
    retry_exhausted = attempts > len(RETRY_DELAYS_SECONDS)
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


def process_metadata_lookup_task(
    db: Session,
    settings: Settings,
    task: dict[str, Any],
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> str:
    import_status = lookup_persist.get_import_task_status(db, task.get("importTaskId"))
    if import_status is not None and import_status != "COMPLETED":
        _schedule_retry(db, task, "等待本地导入任务完成", [])
        return "PENDING"
    work = lookup_persist.get_work(db, task.get("workId"))
    if not work:
        _finish_without_match(db, task, "FAILED", [], "作品已不存在")
        return "FAILED"
    context = metadata_context_for_work(db, str(work["id"]))
    if not context:
        _finish_without_match(
            db,
            task,
            "FAILED",
            [],
            "无法建立元数据查询上下文",
        )
        return "FAILED"
    effective_request_gate = (
        automatic_request_gate
        if lookup_persist.automatic_rate_limit_applies(db, task)
        else None
    )

    enabled_providers = 0
    errors: list[str] = []
    inspected: list[dict[str, Any]] = []
    for provider in _provider_order(task):
        execution_id = _start_provider_execution(db, task, provider)
        try:
            result = _search_provider(
                db,
                context,
                provider,
                str(work.get("title") or ""),
                effective_request_gate,
            )
        except Exception as exc:  # noqa: BLE001 - contains one provider attempt.
            _finish_provider_execution(
                db, execution_id, status="FAILED", error=str(exc)
            )
            errors.append(f"{provider}: {exc}")
            continue
        if not result.get("enabled"):
            _finish_provider_execution(
                db, execution_id, status="SKIPPED", result=result
            )
            continue
        enabled_providers += 1
        candidates = (
            result.get("candidates")
            if isinstance(result.get("candidates"), list)
            else []
        )
        candidate, exact = _choose_exact_candidate(
            candidates,
            str(work.get("title") or ""),
            str(work.get("author") or UNKNOWN_AUTHOR),
        )
        inspected.append(
            {
                "provider": provider,
                "exactCandidates": exact,
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
            prepared_application = _prepare_candidate_application(
                db,
                settings,
                task,
                provider,
                candidate,
            )
            applied = list(prepared_application.applied)
            selected_result_json = json.dumps(
                {"selected": candidate, "attempted": inspected},
                ensure_ascii=False,
            )
            applied_fields_json = json.dumps(applied, ensure_ascii=False)
            finished_at = _now()
            execution_result = {
                "selected": candidate,
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
                    table_ready=execution_id is not None,
                )
            )
            task_id = str(task["id"])
            owner_id = str(task.get("leaseOwnerId") or "") or None
            with MetadataWriteTransaction(db):
                _persist_candidate_application(db, prepared_application, provider)
            if prepared_application.remote_cover is not None:
                try:
                    _publish_remote_cover(prepared_application.remote_cover)
                except OSError as publish_error:
                    try:
                        _compensate_remote_cover_publish_failure(
                            db,
                            prepared_application,
                        )
                    except Exception as compensation_error:
                        raise RuntimeError(
                            "REMOTE_COVER_PUBLISH_COMPENSATION_FAILED"
                        ) from compensation_error
                    raise RuntimeError("REMOTE_COVER_PUBLISH_FAILED") from publish_error
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
            projection = writeback_queue.load_metadata_writeback_projection(
                db,
                work_id=str(work["id"]),
                version_id=(
                    str(task["versionId"]) if task.get("versionId") else None
                ),
            )
            db.close()
            intents = prepare_metadata_writeback_intents(
                projection,
                source="AUTOMATIC",
                lookup_task_id=str(task["id"]),
            )
            with MetadataWriteTransaction(db):
                writeback_queue.enqueue_prepared_writeback_intents(db, intents)
            return "COMPLETED"
        except Exception as exc:  # noqa: BLE001 - contains candidate application.
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
        db, task, "NO_MATCH", inspected, "未找到可唯一确定的标题精确候选"
    )
    return "NO_MATCH"


def process_next_metadata_lookup_task(
    db: Session,
    settings: Settings,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
    *,
    owner_id: str = "metadata-lookup-compat",
    prefer_writeback: bool = False,
    prefer_preparation: bool = True,
) -> bool:
    if prefer_writeback and process_next_metadata_writeback(
        db,
        settings,
        owner_id=owner_id,
        prefer_preparation=prefer_preparation,
    ):
        return True
    task = claim_next_metadata_lookup_task(db, owner_id=owner_id)
    if task:
        process_metadata_lookup_task(db, settings, task, automatic_request_gate)
        return True
    return process_next_metadata_writeback(
        db,
        settings,
        owner_id=owner_id,
        prefer_preparation=prefer_preparation,
    )


class MetadataLookupWorker:
    def __init__(
        self,
        db_factory: Callable[[], Session],
        settings: Settings,
        poll_seconds: float = 2.0,
        heartbeat_db_factory: Callable[[], Session] | None = None,
        automatic_request_gate: AutomaticMetadataRequestGate | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._settings = settings
        self._poll_seconds = poll_seconds
        self._automatic_request_gate = automatic_request_gate
        self._stop = threading.Event()
        self._last_busy_log_at: float | None = None
        self._thread = threading.Thread(
            target=self._run, name="metadata-lookup-worker", daemon=True
        )
        self._instance_id = f"metadata-{uuid4().hex}"
        self._prefer_writeback = False
        self._prefer_preparation = True
        self._heartbeat = QueueHeartbeatPump(
            heartbeat_db_factory or db_factory,
            queue_name="metadata",
            instance_id=self._instance_id,
            poll_interval_seconds=poll_seconds,
        )

    def start(self) -> None:
        with self._db_factory() as db:
            recovered = recover_stale_metadata_lookup_tasks(db)
            if recovered:
                LOGGER.warning("recovered %s stale metadata lookup tasks", recovered)
            recovered_writebacks = recover_interrupted_metadata_writebacks(
                db, self._settings
            )
            if recovered_writebacks:
                LOGGER.warning(
                    "recovered %s interrupted metadata writeback targets",
                    recovered_writebacks,
                )
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(2.0, self._poll_seconds + 1.0))

    def _process_iteration(self) -> bool | None:
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
                        )
                    )
            except OperationalError as error:
                if not is_database_busy_error(error) or attempt == len(
                    DATABASE_BUSY_RETRY_DELAYS_SECONDS
                ):
                    raise
        raise AssertionError("metadata retry loop exhausted")

    def _record_iteration_error(self, error: BaseException) -> None:
        if not is_database_busy_error(error):
            LOGGER.exception("metadata lookup worker iteration failed")
            return
        now = monotonic()
        if (
            self._last_busy_log_at is not None
            and now - self._last_busy_log_at < DATABASE_BUSY_LOG_INTERVAL_SECONDS
        ):
            return
        LOGGER.warning(
            "metadata_lookup_iteration outcome=deferred reason=database_busy"
        )
        self._last_busy_log_at = now

    def _run(self) -> None:
        self._heartbeat.start()
        try:
            while not self._stop.is_set():
                worked = False
                error = None
                try:
                    iteration_result = self._process_iteration()
                    if iteration_result is None:
                        break
                    worked = iteration_result
                except Exception as exc:  # noqa: BLE001 - worker containment boundary.
                    error = exc
                    self._record_iteration_error(exc)
                self._heartbeat.pulse(processed=worked, error=error)
                if not worked:
                    self._stop.wait(self._poll_seconds)
        finally:
            self._heartbeat.stop()
