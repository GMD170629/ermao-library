from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import time_ns
from typing import Any, Callable
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.book_identity import UNKNOWN_AUTHOR, identity_merge_key, normalize_identity_part
from app.services.metadata_provider_registry import metadata_provider_registry, search_with_metadata_provider
from app.services.organize_service import context_for_job, metadata_candidate_title_exact_match, metadata_search_candidates


LOGGER = logging.getLogger(__name__)
RETRY_DELAYS_SECONDS = (60, 300, 1800)
STALE_RUNNING_MINUTES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(db: Session, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    item = db.execute(text(sql), params or {}).mappings().first()
    return dict(item) if item else None


def _rows(db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(item) for item in db.execute(text(sql), params or {}).mappings().all()]


def _has_table(db: Session, table: str) -> bool:
    return table in inspect(db.connection()).get_table_names()


def _has_column(db: Session, table: str, column: str) -> bool:
    return _has_table(db, table) and any(item.get("name") == column for item in inspect(db.connection()).get_columns(table))


def _lookup_task_is_active(db: Session, task_id: str) -> bool:
    if not _has_table(db, "MetadataLookupTask"):
        return False
    return _row(
        db,
        "SELECT `id` FROM `MetadataLookupTask` WHERE `id` = :id AND `status` IN ('PENDING', 'RUNNING')",
        {"id": task_id},
    ) is not None


def _overwrite_title_author_enabled(db: Session) -> bool:
    if not _has_table(db, "OrganizePolicy") or not _has_column(db, "OrganizePolicy", "overwriteTitleAuthor"):
        return True
    policy = _row(db, "SELECT `overwriteTitleAuthor` FROM `OrganizePolicy` WHERE `id` = 'default'")
    return True if policy is None else bool(policy.get("overwriteTitleAuthor"))


def _update_task(db: Session, task_id: str, **values: Any) -> None:
    values["updatedAt"] = _now()
    params = {**values, "task_id": task_id}
    assignments = ", ".join(f"`{key}` = :{key}" for key in values)
    db.execute(
        text(
            f"UPDATE `MetadataLookupTask` SET {assignments} "
            "WHERE `id` = :task_id AND `status` != 'CANCELLED'"
        ),
        params,
    )


def recover_stale_metadata_lookup_tasks(db: Session) -> int:
    if not _has_table(db, "MetadataLookupTask"):
        return 0
    cutoff = _now() - timedelta(minutes=STALE_RUNNING_MINUTES)
    result = db.execute(
        text(
            """
            UPDATE `MetadataLookupTask`
            SET `status` = 'PENDING', `nextAttemptAt` = :now, `startedAt` = NULL,
                `errorSummary` = '任务进程中断，已自动恢复', `updatedAt` = :now
            WHERE `status` = 'RUNNING' AND `startedAt` < :cutoff
            """
        ),
        {"now": _now(), "cutoff": cutoff},
    )
    db.commit()
    return int(result.rowcount or 0)


def claim_next_metadata_lookup_task(db: Session) -> dict[str, Any] | None:
    if not _has_table(db, "MetadataLookupTask"):
        return None
    task = _row(
        db,
        """
        SELECT * FROM `MetadataLookupTask`
        WHERE `status` = 'PENDING'
          AND (`nextAttemptAt` IS NULL OR datetime(`nextAttemptAt`) <= CURRENT_TIMESTAMP)
        ORDER BY `createdAt` ASC
        LIMIT 1
        """,
    )
    if not task:
        return None
    started_at = _now()
    result = db.execute(
        text(
            """
            UPDATE `MetadataLookupTask`
            SET `status` = 'RUNNING', `startedAt` = :started_at, `updatedAt` = :started_at
            WHERE `id` = :task_id AND `status` = 'PENDING'
            """
        ),
        {"task_id": task["id"], "started_at": started_at},
    )
    if result.rowcount and task.get("organizeJobId") and _has_table(db, "OrganizeJob"):
        started_assignment = ", `startedAt` = COALESCE(`startedAt`, :started_at)" if _has_column(db, "OrganizeJob", "startedAt") else ""
        db.execute(
            text(
                f"UPDATE `OrganizeJob` SET `status` = 'RUNNING', `summary` = '正在调用元数据插件', "
                f"`updatedAt` = :started_at{started_assignment} WHERE `id` = :job_id"
            ),
            {"job_id": task["organizeJobId"], "started_at": started_at},
        )
    db.commit()
    if not result.rowcount:
        return None
    task["status"] = "RUNNING"
    task["startedAt"] = started_at
    return task


def _provider_order(task: dict[str, Any]) -> list[str]:
    try:
        parsed = json.loads(str(task.get("providerOrder") or "[]"))
    except json.JSONDecodeError:
        parsed = []
    registered = metadata_provider_registry().ids()
    return [str(item) for item in parsed if str(item) in registered]


def _search_provider(db: Session, context: dict[str, Any], provider: str, query: str) -> dict[str, Any]:
    # Lightweight worker unit tests and one-release legacy databases may not
    # have Source yet. Keep the old call boundary in that compatibility path.
    if not _has_table(db, "Source"):
        return metadata_search_candidates(db, context, provider, query, force=False, use_cache=True)
    return search_with_metadata_provider(db, context, provider, query, force=False, use_cache=True)


def _start_provider_execution(db: Session, task: dict[str, Any], provider: str) -> str | None:
    if not _has_table(db, "MetadataProviderExecution"):
        return None
    execution_id = f"py_{time_ns()}"
    now = _now()
    db.execute(
        text(
            """
            INSERT INTO `MetadataProviderExecution`
                (`id`, `jobId`, `lookupTaskId`, `providerId`, `status`, `attempts`,
                 `startedAt`, `createdAt`, `updatedAt`)
            VALUES
                (:id, :job_id, :task_id, :provider, 'RUNNING', :attempts, :now, :now, :now)
            """
        ),
        {
            "id": execution_id,
            "job_id": task.get("organizeJobId"),
            "task_id": task.get("id"),
            "provider": provider,
            "attempts": int(task.get("attempts") or 0) + 1,
            "now": now,
        },
    )
    db.commit()
    return execution_id


def _finish_provider_execution(
    db: Session,
    execution_id: str | None,
    *,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> None:
    if not execution_id or not _has_table(db, "MetadataProviderExecution"):
        return
    db.execute(
        text(
            """
            UPDATE `MetadataProviderExecution`
            SET `status` = :status, `rawResultJson` = :result, `errorSummary` = :error,
                `finishedAt` = :now, `updatedAt` = :now
            WHERE `id` = :id
            """
        ),
        {
            "id": execution_id,
            "status": status,
            "result": json.dumps(result, ensure_ascii=False) if result is not None else None,
            "error": error,
            "now": _now(),
        },
    )
    db.commit()


def _choose_exact_candidate(candidates: list[dict[str, Any]], title: str, author: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    exact = [candidate for candidate in candidates if metadata_candidate_title_exact_match(title, candidate)]
    if len(exact) == 1:
        return exact[0], exact
    if len(exact) > 1 and normalize_identity_part(author) != normalize_identity_part(UNKNOWN_AUTHOR):
        author_key = normalize_identity_part(author)
        author_matches = [candidate for candidate in exact if normalize_identity_part(candidate.get("author")) == author_key]
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


def _local_cover_exists(db: Session, work: dict[str, Any], edition_id: str | None) -> bool:
    if str(work.get("coverPath") or "").strip():
        return True
    if not edition_id:
        return False
    edition = _row(db, "SELECT `coverPath` FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id})
    if str((edition or {}).get("coverPath") or "").strip():
        return True
    volume = _row(
        db,
        "SELECT `id` FROM `LibraryVolume` WHERE `editionId` = :edition_id AND `coverPath` IS NOT NULL AND `coverPath` != '' LIMIT 1",
        {"edition_id": edition_id},
    )
    return volume is not None


def _download_remote_cover(work_id: str, cover_url: str, settings: Settings) -> str | None:
    if not cover_url.startswith(("http://", "https://")):
        return None
    request = UrlRequest(
        cover_url,
        headers={"Accept": "image/*", "User-Agent": "ShukuStarship/0.1 metadata-worker"},
    )
    with urlopen(request, timeout=20) as response:
        content_type = str(response.headers.get("content-type") or "").lower()
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024 or not data:
        raise ValueError("远程封面为空或超过 8 MiB")
    suffix = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
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
    work = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": task["workId"]})
    if not work:
        raise ValueError("作品已不存在")
    edition_id = str(work.get("primaryEditionId") or task.get("editionId") or "") or None
    edition = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id}) if edition_id else None
    work_patch: dict[str, Any] = {}
    edition_patch: dict[str, Any] = {}
    applied: list[str] = []

    overwrite_title_author = _overwrite_title_author_enabled(db)
    candidate_title = str(candidate.get("title") or "").strip()
    candidate_author = str(candidate.get("author") or "").strip()
    current_title = str(work.get("title") or "").strip()
    current_author = str(work.get("author") or "").strip()
    if candidate_title and (not current_title or (overwrite_title_author and candidate_title != current_title)):
        work_patch["title"] = candidate_title
        applied.append("title")
    if candidate_author and (
        not current_author
        or current_author == UNKNOWN_AUTHOR
        or (overwrite_title_author and candidate_author != current_author)
    ):
        work_patch["author"] = candidate_author
        applied.append("author")
    if not str(work.get("description") or "").strip() and str(candidate.get("description") or "").strip():
        work_patch["description"] = str(candidate["description"]).strip()
        applied.append("description")
    candidate_tags = _parse_tags(candidate.get("tags"))
    if not _parse_tags(work.get("tags")) and candidate_tags:
        work_patch["tags"] = json.dumps(list(dict.fromkeys(candidate_tags)), ensure_ascii=False)
        applied.append("tags")
    if not str(work.get("seriesName") or "").strip() and str(candidate.get("seriesName") or "").strip():
        work_patch["seriesName"] = str(candidate["seriesName"]).strip()
        applied.append("seriesName")
    if _has_column(db, "LibraryWork", "seriesIndex") and work.get("seriesIndex") is None and candidate.get("seriesIndex") is not None:
        try:
            work_patch["seriesIndex"] = float(candidate["seriesIndex"])
            applied.append("seriesIndex")
        except (TypeError, ValueError):
            pass
    if work.get("publishedYear") is None and candidate.get("publishedYear") is not None:
        try:
            work_patch["publishedYear"] = int(candidate["publishedYear"])
            applied.append("publishedYear")
        except (TypeError, ValueError):
            pass
    if edition and not str(edition.get("publisher") or "").strip() and str(candidate.get("publisher") or "").strip():
        edition_patch["publisher"] = str(candidate["publisher"]).strip()
        applied.append("publisher")
    if not _local_cover_exists(db, work, edition_id) and str(candidate.get("coverUrl") or "").strip():
        try:
            cover_path = _download_remote_cover(str(work["id"]), str(candidate["coverUrl"]).strip(), settings)
        except Exception as exc:
            LOGGER.warning("remote metadata cover skipped work=%s: %s", work["id"], exc)
        else:
            if cover_path:
                work_patch.update({"coverPath": cover_path, "coverStatus": "READY"})
                applied.append("cover")

    if "title" in work_patch or "author" in work_patch:
        title = str(work_patch.get("title", work.get("title")) or "").strip()
        author = str(work_patch.get("author", work.get("author")) or "").strip() or UNKNOWN_AUTHOR
        work_patch.update(
            {
                "normalizedTitle": normalize_identity_part(title),
                "normalizedAuthor": normalize_identity_part(author),
                "mergeKey": identity_merge_key(title, author),
            }
        )

    work_patch.update(
        {
            "metadataQuality": max(int(work.get("metadataQuality") or 0), 85 if applied else 80),
            "organized": True,
            "organizeStatus": "APPLIED",
            "updatedAt": _now(),
        }
    )
    work_assignments = ", ".join(f"`{key}` = :{key}" for key in work_patch)
    db.execute(text(f"UPDATE `LibraryWork` SET {work_assignments} WHERE `id` = :work_id"), {**work_patch, "work_id": work["id"]})
    if edition and edition_patch:
        edition_patch["updatedAt"] = _now()
        assignments = ", ".join(f"`{key}` = :{key}" for key in edition_patch)
        db.execute(text(f"UPDATE `LibraryEdition` SET {assignments} WHERE `id` = :edition_id"), {**edition_patch, "edition_id": edition["id"]})

    job_id = task.get("organizeJobId")
    if job_id and _has_table(db, "OrganizeJob"):
        finished_assignment = ", `finishedAt` = :now" if _has_column(db, "OrganizeJob", "finishedAt") else ""
        db.execute(
            text(
                f"""
                UPDATE `OrganizeJob`
                SET `status` = :status, `summary` = :summary, `errorSummary` = NULL, `updatedAt` = :now
                    {finished_assignment}
                WHERE `id` = :job_id
                """
            ),
            {
                "status": "APPLIED" if applied else "COMPLETED",
                "summary": (
                    f"已从 {provider} 自动应用 {len(applied)} 项元数据"
                    if applied
                    else f"已从 {provider} 完成识别，现有元数据无需更新"
                ),
                "now": _now(),
                "job_id": job_id,
            },
        )
    if edition_id and _has_table(db, "LibraryMetadata"):
        db.execute(
            text(
                """
                INSERT INTO `LibraryMetadata` (`id`, `editionId`, `source`, `rawJson`, `createdAt`, `updatedAt`)
                VALUES (:id, :edition_id, :source, :raw_json, :now, :now)
                """
            ),
            {
                "id": f"py_{time_ns()}",
                "edition_id": edition_id,
                "source": provider,
                "raw_json": json.dumps({"candidate": candidate, "appliedFields": applied}, ensure_ascii=False),
                "now": _now(),
            },
        )
    return applied


def _mark_organize_lookup_unresolved(db: Session, task: dict[str, Any], message: str, *, failed: bool = False) -> None:
    """Expose a lookup in the organize queue only after it has no usable match."""

    work = _row(db, "SELECT `organized`, `organizeStatus` FROM `LibraryWork` WHERE `id` = :id", {"id": task.get("workId")})
    already_organized = bool((work or {}).get("organized")) or (work or {}).get("organizeStatus") == "APPLIED"
    if work and not already_organized:
        db.execute(
            text("UPDATE `LibraryWork` SET `organized` = 0, `organizeStatus` = 'REVIEWING', `updatedAt` = :now WHERE `id` = :id"),
            {"now": _now(), "id": task.get("workId")},
        )
    if task.get("organizeJobId") and _has_table(db, "OrganizeJob"):
        finished_assignment = ", `finishedAt` = :now" if _has_column(db, "OrganizeJob", "finishedAt") else ""
        db.execute(
            text(
                "UPDATE `OrganizeJob` SET `status` = :status, `summary` = :summary, "
                f"`errorSummary` = :error, `updatedAt` = :now{finished_assignment} "
                "WHERE `id` = :id AND `status` != 'CANCELLED'"
            ),
            {
                "status": "FAILED",
                "summary": message,
                "error": message if failed else None,
                "now": _now(),
                "id": task["organizeJobId"],
            },
        )


def _finish_without_match(db: Session, task: dict[str, Any], status: str, candidates: list[dict[str, Any]], message: str) -> None:
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


def _schedule_retry(db: Session, task: dict[str, Any], message: str, candidates: list[dict[str, Any]]) -> None:
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
            nextAttemptAt=_now() + timedelta(seconds=RETRY_DELAYS_SECONDS[attempts - 1]),
            candidateRawJson=json.dumps(candidates, ensure_ascii=False),
            errorSummary=message,
            startedAt=None,
        )
        if task.get("organizeJobId") and _has_table(db, "OrganizeJob"):
            db.execute(
                text(
                    "UPDATE `OrganizeJob` SET `status` = 'LOOKUP_PENDING', `summary` = :summary, "
                    "`errorSummary` = :error, `updatedAt` = :now WHERE `id` = :id"
                ),
                {
                    "id": task["organizeJobId"],
                    "summary": f"识别暂时失败，将进行第 {attempts + 1} 次尝试",
                    "error": message,
                    "now": _now(),
                },
            )
    db.commit()


def process_metadata_lookup_task(db: Session, settings: Settings, task: dict[str, Any]) -> str:
    import_task = _row(db, "SELECT `status` FROM `ImportTask` WHERE `id` = :id", {"id": task.get("importTaskId")}) if task.get("importTaskId") else None
    if import_task and import_task.get("status") != "COMPLETED":
        _schedule_retry(db, task, "等待本地导入任务完成", [])
        return "PENDING"
    work = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": task.get("workId")})
    if not work:
        _finish_without_match(db, task, "FAILED", [], "作品已不存在")
        return "FAILED"
    context = context_for_job(db, {"workId": work["id"]})
    if not context:
        _finish_without_match(db, task, "FAILED", [], "无法建立元数据查询上下文")
        return "FAILED"

    enabled_providers = 0
    errors: list[str] = []
    inspected: list[dict[str, Any]] = []
    for provider in _provider_order(task):
        execution_id = _start_provider_execution(db, task, provider)
        try:
            result = _search_provider(db, context, provider, str(work.get("title") or ""))
        except Exception as exc:
            _finish_provider_execution(db, execution_id, status="FAILED", error=str(exc))
            errors.append(f"{provider}: {exc}")
            continue
        if not result.get("enabled"):
            _finish_provider_execution(db, execution_id, status="SKIPPED", result=result)
            continue
        enabled_providers += 1
        candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
        candidate, exact = _choose_exact_candidate(candidates, str(work.get("title") or ""), str(work.get("author") or UNKNOWN_AUTHOR))
        inspected.append({"provider": provider, "exactCandidates": exact, "cacheHit": bool(result.get("cacheHit"))})
        if not candidate:
            _finish_provider_execution(db, execution_id, status="NO_MATCH", result=result)
            continue
        if not _lookup_task_is_active(db, str(task["id"])):
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
                candidateRawJson=json.dumps({"selected": candidate, "attempted": inspected}, ensure_ascii=False),
                appliedFields=json.dumps(applied, ensure_ascii=False),
                errorSummary=None,
                finishedAt=_now(),
            )
            _finish_provider_execution(db, execution_id, status="COMPLETED", result={"selected": candidate, "appliedFields": applied})
            db.commit()
            return "COMPLETED"
        except Exception as exc:
            db.rollback()
            _finish_provider_execution(db, execution_id, status="FAILED", error=f"apply: {exc}")
            errors.append(f"{provider} apply: {exc}")

    if enabled_providers == 0 and not errors:
        if not _lookup_task_is_active(db, str(task["id"])):
            return "CANCELLED"
        _finish_without_match(db, task, "NO_PROVIDER", inspected, "所有适用的元数据插件均未启用")
        return "NO_PROVIDER"
    if errors:
        if not _lookup_task_is_active(db, str(task["id"])):
            return "CANCELLED"
        _schedule_retry(db, task, "；".join(errors), inspected)
        refreshed = _row(db, "SELECT `status` FROM `MetadataLookupTask` WHERE `id` = :id", {"id": task["id"]})
        return str((refreshed or {}).get("status") or "FAILED")
    if not _lookup_task_is_active(db, str(task["id"])):
        return "CANCELLED"
    _finish_without_match(db, task, "NO_MATCH", inspected, "未找到可唯一确定的标题精确候选")
    return "NO_MATCH"


def process_next_metadata_lookup_task(db: Session, settings: Settings) -> bool:
    task = claim_next_metadata_lookup_task(db)
    if not task:
        return False
    process_metadata_lookup_task(db, settings, task)
    return True


class MetadataLookupWorker:
    def __init__(self, db_factory: Callable[[], Session], settings: Settings, poll_seconds: float = 2.0) -> None:
        self._db_factory = db_factory
        self._settings = settings
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="metadata-lookup-worker", daemon=True)

    def start(self) -> None:
        with self._db_factory() as db:
            recovered = recover_stale_metadata_lookup_tasks(db)
            if recovered:
                LOGGER.warning("recovered %s stale metadata lookup tasks", recovered)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(2.0, self._poll_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop.is_set():
            worked = False
            try:
                with self._db_factory() as db:
                    worked = process_next_metadata_lookup_task(db, self._settings)
            except Exception:
                LOGGER.exception("metadata lookup worker iteration failed")
            if not worked:
                self._stop.wait(self._poll_seconds)
