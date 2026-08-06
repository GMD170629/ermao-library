from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.infrastructure.sqlite_retry import execute_with_sqlite_busy_retry
from app.models.common import db_timestamp
from app.modules.metadata.application.commands import execute_metadata_transaction
from app.modules.metadata.application.rate_limits import AutomaticMetadataRequestGate
from app.modules.metadata.infrastructure import lookup_queue as lookup_persist
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
    normalize_identity_part,
)
from app.services.library_management import sync_work_facets
from app.services.metadata_file_writeback import (
    process_next_metadata_writeback,
    recover_interrupted_metadata_writebacks,
    schedule_work_metadata_writebacks,
)
from app.services.metadata_provider_registry import (
    metadata_provider_registry,
    search_with_metadata_provider,
)
from app.services.organize_service import (
    context_for_job,
    metadata_candidate_title_exact_match,
)
from app.services.queue_runtime import QueueHeartbeatPump

LOGGER = logging.getLogger(__name__)
RETRY_DELAYS_SECONDS = (60, 300, 1800)
DATABASE_BUSY_RETRY_DELAYS_SECONDS = (0.25, 1.0)
STALE_RUNNING_MINUTES = lookup_persist.STALE_RUNNING_MINUTES


def _now() -> datetime:
    return db_timestamp()


def recover_stale_metadata_lookup_tasks(db: Session) -> int:
    return execute_metadata_transaction(
        db,
        lambda: lookup_persist.recover_stale_lookup_tasks(db),
    )


def claim_next_metadata_lookup_task(db: Session) -> dict[str, Any] | None:
    return execute_metadata_transaction(
        db,
        lambda: lookup_persist.claim_next_lookup_task(db),
    )


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
    return execute_metadata_transaction(
        db,
        lambda: lookup_persist.start_provider_execution(db, task, provider),
    )


def _finish_provider_execution(
    db: Session,
    execution_id: str | None,
    *,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> None:
    execute_metadata_transaction(
        db,
        lambda: lookup_persist.finish_provider_execution(
            db,
            execution_id,
            status=status,
            result=result,
            error=error,
        ),
    )


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


def _download_remote_cover(
    work_id: str, cover_url: str, settings: Settings
) -> str | None:
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
        content_type = str(response.headers.get("content-type") or "").lower()
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024 or not data:
        raise ValueError("远程封面为空或超过 8 MiB")
    suffix = (
        ".png"
        if "png" in content_type
        else ".webp"
        if "webp" in content_type
        else ".jpg"
    )
    target_dir = settings.resolved_storage_root / "covers"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{work_id}-remote{suffix}"
    target.write_bytes(data)
    return str(target.relative_to(settings.resolved_storage_root))


def _apply_candidate(
    db: Session,
    settings: Settings,
    task: dict[str, Any],
    provider: str,
    candidate: dict[str, Any],
) -> list[str]:
    work = lookup_persist.get_work(db, str(task["workId"]))
    if not work:
        raise ValueError("作品已不存在")
    volume_id = str(task.get("volumeId") or "") or None
    volume = lookup_persist.get_volume(db, volume_id) if volume_id else None
    work_patch: dict[str, Any] = {}
    volume_patch: dict[str, Any] = {}
    applied: list[str] = []
    prefer_local = lookup_persist.prefer_local_metadata_enabled(db)

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
    if (not prefer_local or not _local_cover_exists(db, work, volume_id)) and str(
        candidate.get("coverUrl") or ""
    ).strip():
        try:
            cover_path = _download_remote_cover(
                str(work["id"]), str(candidate["coverUrl"]).strip(), settings
            )
        except Exception as exc:
            LOGGER.warning("remote metadata cover skipped work=%s: %s", work["id"], exc)
        else:
            if cover_path:
                work_patch.update({"coverPath": cover_path, "coverStatus": "READY"})
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
                "mergeKey": identity_merge_key(title, author),
            }
        )

    work_patch.update(
        {
            "metadataQuality": max(
                int(work.get("metadataQuality") or 0), 85 if applied else 80
            ),
            "organized": True,
            "organizeStatus": "APPLIED",
            "updatedAt": _now(),
        }
    )
    lookup_persist.update_work(db, str(work["id"]), work_patch)
    if volume and volume_patch:
        volume_patch["updatedAt"] = _now()
        lookup_persist.update_volume(db, str(volume["id"]), volume_patch)
    sync_work_facets(db, str(work["id"]), commit=False)

    job_id = task.get("organizeJobId")
    if job_id:
        lookup_persist.finish_organize_job(
            db,
            str(job_id),
            status="APPLIED" if applied else "COMPLETED",
            summary=(
                f"已从 {provider} 自动应用 {len(applied)} 项元数据"
                if applied
                else f"已从 {provider} 完成识别，现有元数据无需更新"
            ),
            error_summary=None,
            set_finished_at=True,
        )
    if volume_id:
        lookup_persist.insert_library_metadata(
            db,
            volume_id=volume_id,
            source=provider,
            raw_json=json.dumps(
                {"candidate": candidate, "appliedFields": applied}, ensure_ascii=False
            ),
        )
    schedule_work_metadata_writebacks(
        db,
        work_id=str(work["id"]),
        media_version_id=str(task["mediaVersionId"])
        if task.get("mediaVersionId")
        else None,
        source="AUTOMATIC",
        lookup_task_id=str(task["id"]),
    )
    return applied


def _mark_organize_lookup_unresolved(
    db: Session, task: dict[str, Any], message: str, *, failed: bool = False
) -> None:
    """Expose a lookup in the organize queue only after it has no usable match."""

    work = lookup_persist.get_work_organize_state(db, task.get("workId"))
    already_organized = (
        bool((work or {}).get("organized"))
        or (work or {}).get("organizeStatus") == "APPLIED"
    )
    if work and not already_organized and task.get("workId"):
        lookup_persist.mark_work_reviewing(db, str(task["workId"]))
    if task.get("organizeJobId"):
        lookup_persist.finish_organize_job(
            db,
            str(task["organizeJobId"]),
            status="FAILED",
            summary=message,
            error_summary=message if failed else None,
            set_finished_at=True,
            only_if_not_cancelled=True,
        )


def _update_task(db: Session, task_id: str, **values: Any) -> None:
    lookup_persist.update_lookup_task(db, task_id, **values)


def _finish_without_match(
    db: Session,
    task: dict[str, Any],
    status: str,
    candidates: list[dict[str, Any]],
    message: str,
) -> None:
    _update_task(
        db,
        str(task["id"]),
        status=status,
        candidateRawJson=json.dumps(candidates, ensure_ascii=False),
        errorSummary=message if status in {"FAILED", "NO_PROVIDER"} else None,
        nextAttemptAt=None,
        finishedAt=_now(),
    )
    _mark_organize_lookup_unresolved(db, task, message, failed=status == "FAILED")
    db.commit()


def _schedule_retry(
    db: Session, task: dict[str, Any], message: str, candidates: list[dict[str, Any]]
) -> None:
    attempts = int(task.get("attempts") or 0) + 1
    if attempts > len(RETRY_DELAYS_SECONDS):
        _update_task(
            db,
            str(task["id"]),
            status="FAILED",
            attempts=attempts,
            nextAttemptAt=None,
            candidateRawJson=json.dumps(candidates, ensure_ascii=False),
            errorSummary=message,
            finishedAt=_now(),
        )
        _mark_organize_lookup_unresolved(db, task, message, failed=True)
    else:
        _update_task(
            db,
            str(task["id"]),
            status="PENDING",
            attempts=attempts,
            nextAttemptAt=_now()
            + timedelta(seconds=RETRY_DELAYS_SECONDS[attempts - 1]),
            candidateRawJson=json.dumps(candidates, ensure_ascii=False),
            errorSummary=message,
            startedAt=None,
        )
        if task.get("organizeJobId"):
            lookup_persist.mark_organize_job_retry_wait(
                db,
                str(task["organizeJobId"]),
                summary=f"识别暂时失败，将进行第 {attempts + 1} 次尝试",
                error=message,
            )
    db.commit()


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
    context = context_for_job(db, {"workId": work["id"]})
    if not context:
        _finish_without_match(db, task, "FAILED", [], "无法建立元数据查询上下文")
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
        except Exception as exc:
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
        try:
            applied = _apply_candidate(db, settings, task, provider, candidate)
            _update_task(
                db,
                str(task["id"]),
                status="COMPLETED",
                attempts=int(task.get("attempts") or 0) + 1,
                nextAttemptAt=None,
                resultSource=provider,
                candidateRawJson=json.dumps(
                    {"selected": candidate, "attempted": inspected}, ensure_ascii=False
                ),
                appliedFields=json.dumps(applied, ensure_ascii=False),
                errorSummary=None,
                finishedAt=_now(),
            )
            _finish_provider_execution(
                db,
                execution_id,
                status="COMPLETED",
                result={"selected": candidate, "appliedFields": applied},
            )
            db.commit()
            return "COMPLETED"
        except Exception as exc:
            db.rollback()
            _finish_provider_execution(
                db, execution_id, status="FAILED", error=f"apply: {exc}"
            )
            errors.append(f"{provider} apply: {exc}")

    if enabled_providers == 0 and not errors:
        if not lookup_persist.lookup_task_is_active(db, str(task["id"])):
            return "CANCELLED"
        _finish_without_match(
            db, task, "NO_PROVIDER", inspected, "所有适用的元数据插件均未启用"
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
) -> bool:
    if process_next_metadata_writeback(db, settings):
        return True
    task = claim_next_metadata_lookup_task(db)
    if not task:
        return False
    process_metadata_lookup_task(db, settings, task, automatic_request_gate)
    return True


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
        self._thread = threading.Thread(
            target=self._run, name="metadata-lookup-worker", daemon=True
        )
        self._instance_id = f"metadata-{uuid4().hex}"
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
            recovered_writebacks = recover_interrupted_metadata_writebacks(db)
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
        result = execute_with_sqlite_busy_retry(
            self._db_factory,
            lambda db: process_next_metadata_lookup_task(
                db, self._settings, self._automatic_request_gate
            ),
            retry_delays_seconds=DATABASE_BUSY_RETRY_DELAYS_SECONDS,
            stop_wait=self._stop.wait,
        )
        return bool(result.value) if result.completed else None

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
                except Exception as exc:
                    error = exc
                    LOGGER.exception("metadata lookup worker iteration failed")
                self._heartbeat.pulse(processed=worked, error=error)
                if not worked:
                    self._stop.wait(self._poll_seconds)
        finally:
            self._heartbeat.stop()
