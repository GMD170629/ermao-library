from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from time import time_ns
from typing import Any, Callable

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.services.metadata_provider_registry import enabled_metadata_provider_ids


LOGGER = logging.getLogger(__name__)
DEFAULT_POLICY_ID = "default"
DEFAULT_INTERVAL_MINUTES = 60
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 7 * 24 * 60
ACTIVE_JOB_STATUSES = ("LOOKUP_PENDING", "PENDING", "QUEUED", "RUNNING", "RETRY_WAIT", "REVIEWING")
UNRESOLVED_JOB_STATUSES = (*ACTIVE_JOB_STATUSES, "FAILED")
TERMINAL_JOB_STATUSES = ("APPLIED", "COMPLETED", "DISMISSED", "CANCELLED", "FAILED")
DEFAULT_RULES = {
    "unrecognized": True,
    "missingMetadata": True,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"py_{prefix}_{time_ns()}"


def _has_table(db: Session, table: str) -> bool:
    return table in inspect(db.connection()).get_table_names()


def _has_column(db: Session, table: str, column: str) -> bool:
    return _has_table(db, table) and any(item.get("name") == column for item in inspect(db.connection()).get_columns(table))


def _row(db: Session, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    item = db.execute(text(sql), params or {}).mappings().first()
    return dict(item) if item else None


def _rows(db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(item) for item in db.execute(text(sql), params or {}).mappings().all()]


def _json_dict(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return dict(fallback)
    return parsed if isinstance(parsed, dict) else dict(fallback)


def _policy_view(row: dict[str, Any]) -> dict[str, Any]:
    stored_rules = _json_dict(row.get("rulesJson"), DEFAULT_RULES)
    return {
        "id": row.get("id") or DEFAULT_POLICY_ID,
        "enabled": bool(row.get("enabled")),
        "scheduleMode": str(row.get("scheduleMode") or "MANUAL"),
        "intervalMinutes": int(row.get("intervalMinutes") or DEFAULT_INTERVAL_MINUTES),
        "autoRunOnNew": bool(row.get("autoRunOnNew")),
        "autoRunOnNewSince": row.get("autoRunOnNewSince"),
        "rules": {
            "unrecognized": bool(stored_rules.get("unrecognized", True)),
            "missingMetadata": bool(stored_rules.get("missingMetadata", True)),
        },
        "overwriteTitleAuthor": bool(row.get("overwriteTitleAuthor", True)),
        "lastScheduledAt": row.get("lastScheduledAt"),
        "nextRunAt": row.get("nextRunAt"),
        "updatedAt": row.get("updatedAt"),
    }


def ensure_organize_policy(db: Session) -> dict[str, Any]:
    if not _has_table(db, "OrganizePolicy"):
        raise ValueError("整理策略数据表尚未初始化")
    existing = _row(db, "SELECT * FROM `OrganizePolicy` WHERE `id` = :id", {"id": DEFAULT_POLICY_ID})
    if existing:
        return _policy_view(existing)
    now = _now()
    db.execute(
        text(
            """
            INSERT OR IGNORE INTO `OrganizePolicy`
                (`id`, `enabled`, `scheduleMode`, `intervalMinutes`, `autoRunOnNew`,
                 `autoRunOnNewSince`, `rulesJson`, `overwriteTitleAuthor`, `lastScheduledAt`,
                 `nextRunAt`, `createdAt`, `updatedAt`)
            VALUES
                (:id, 0, 'MANUAL', :interval, 0, NULL, :rules, 1, NULL, NULL, :now, :now)
            """
        ),
        {
            "id": DEFAULT_POLICY_ID,
            "interval": DEFAULT_INTERVAL_MINUTES,
            "rules": json.dumps(DEFAULT_RULES, ensure_ascii=False),
            "now": now,
        },
    )
    db.commit()
    return _policy_view(_row(db, "SELECT * FROM `OrganizePolicy` WHERE `id` = :id", {"id": DEFAULT_POLICY_ID}) or {})


def get_organize_policy(db: Session) -> dict[str, Any]:
    return ensure_organize_policy(db)


def update_organize_policy(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    current = ensure_organize_policy(db)
    schedule_mode = str(payload.get("scheduleMode", current["scheduleMode"])).upper()
    if schedule_mode not in {"MANUAL", "INTERVAL"}:
        raise ValueError("执行方式仅支持手动或定时间隔")
    try:
        interval = int(payload.get("intervalMinutes", current["intervalMinutes"]))
    except (TypeError, ValueError):
        raise ValueError("执行间隔格式不正确") from None
    if interval < MIN_INTERVAL_MINUTES or interval > MAX_INTERVAL_MINUTES:
        raise ValueError(f"执行间隔需在 {MIN_INTERVAL_MINUTES} 到 {MAX_INTERVAL_MINUTES} 分钟之间")

    enabled = bool(payload.get("enabled", current["enabled"]))
    auto_run_on_new = bool(payload.get("autoRunOnNew", current["autoRunOnNew"]))
    rules_payload = payload.get("rules", current["rules"])
    if not isinstance(rules_payload, dict):
        raise ValueError("识别范围配置格式不正确")
    rules = {
        "unrecognized": bool(rules_payload.get("unrecognized", current["rules"]["unrecognized"])),
        "missingMetadata": bool(rules_payload.get("missingMetadata", current["rules"]["missingMetadata"])),
    }
    now = _now()
    newly_enabled_for_new = auto_run_on_new and not current["autoRunOnNew"]
    auto_since = now if newly_enabled_for_new else current.get("autoRunOnNewSince")
    if not auto_run_on_new:
        auto_since = None
    next_run_at = None
    if enabled and schedule_mode == "INTERVAL":
        old_next = current.get("nextRunAt")
        settings_changed = (
            not current["enabled"]
            or current["scheduleMode"] != schedule_mode
            or current["intervalMinutes"] != interval
        )
        next_run_at = now + timedelta(minutes=interval) if settings_changed or not old_next else old_next

    db.execute(
        text(
            """
            UPDATE `OrganizePolicy`
            SET `enabled` = :enabled, `scheduleMode` = :schedule_mode,
                `intervalMinutes` = :interval, `autoRunOnNew` = :auto_run_on_new,
                `autoRunOnNewSince` = :auto_since, `rulesJson` = :rules,
                `overwriteTitleAuthor` = :overwrite_title_author, `nextRunAt` = :next_run_at,
                `updatedAt` = :now
            WHERE `id` = :id
            """
        ),
        {
            "id": DEFAULT_POLICY_ID,
            "enabled": enabled,
            "schedule_mode": schedule_mode,
            "interval": interval,
            "auto_run_on_new": auto_run_on_new,
            "auto_since": auto_since,
            "rules": json.dumps(rules, ensure_ascii=False),
            "overwrite_title_author": bool(payload.get("overwriteTitleAuthor", current["overwriteTitleAuthor"])),
            "next_run_at": next_run_at,
            "now": now,
        },
    )
    db.commit()
    return get_organize_policy(db)


def _reason_codes(work: dict[str, Any], rules: dict[str, Any], *, force_selected: bool = False) -> list[str]:
    if force_selected:
        return ["MANUAL_SELECTED"]
    reasons: list[str] = []
    if rules.get("unrecognized") and not bool(work.get("organized")):
        reasons.append("UNRECOGNIZED")
    # A description is optional enrichment. Treating it as required makes a
    # successfully imported work eligible on every schedule tick when no
    # provider can supply a unique match.
    missing = any(not str(work.get(field) or "").strip() for field in ("author", "coverPath"))
    if rules.get("missingMetadata") and missing:
        reasons.append("MISSING_METADATA")
    return reasons


def eligible_organize_works(
    db: Session,
    policy: dict[str, Any] | None = None,
    *,
    work_ids: list[str] | None = None,
    trigger: str = "MANUAL",
    limit: int = 500,
    force_selected: bool = False,
) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryWork"):
        return []
    policy = policy or get_organize_policy(db)
    params: dict[str, Any] = {"limit": min(max(int(limit), 1), 2000)}
    where = ["COALESCE(w.`hidden`, 0) = 0", "COALESCE(w.`organizeStatus`, '') != 'DISMISSED'"]
    if work_ids:
        normalized_ids = list(dict.fromkeys(str(item) for item in work_ids if str(item).strip()))
        if not normalized_ids:
            return []
        placeholders = []
        for index, work_id in enumerate(normalized_ids):
            key = f"work_id_{index}"
            params[key] = work_id
            placeholders.append(f":{key}")
        where.append(f"w.`id` IN ({', '.join(placeholders)})")
    if _has_table(db, "OrganizeJob"):
        unresolved = ", ".join(f"'{item}'" for item in UNRESOLVED_JOB_STATUSES)
        where.append(
            f"NOT EXISTS (SELECT 1 FROM `OrganizeJob` j WHERE j.`workId` = w.`id` AND j.`status` IN ({unresolved}))"
        )
        if trigger == "NEW":
            where.append("NOT EXISTS (SELECT 1 FROM `OrganizeJob` j WHERE j.`workId` = w.`id` AND j.`trigger` = 'NEW')")
    if trigger == "NEW":
        since = policy.get("autoRunOnNewSince")
        if not since:
            return []
        params["since"] = since
        where.append("datetime(w.`createdAt`) >= datetime(:since)")
    rows = _rows(
        db,
        f"SELECT w.* FROM `LibraryWork` w WHERE {' AND '.join(where)} ORDER BY w.`createdAt` ASC LIMIT :limit",
        params,
    )
    result: list[dict[str, Any]] = []
    for work in rows:
        reasons = _reason_codes(work, policy["rules"], force_selected=force_selected)
        if reasons:
            result.append({**work, "reasonCodes": reasons})
    return result


def organize_candidate_summary(db: Session) -> dict[str, Any]:
    policy = get_organize_policy(db)
    works = eligible_organize_works(db, policy, limit=2000)
    counts: dict[str, int] = {}
    for work in works:
        for reason in work.get("reasonCodes") or []:
            counts[reason] = counts.get(reason, 0) + 1
    return {
        "total": len(works),
        "reasonCounts": counts,
        "works": [
            {
                "id": work.get("id"),
                "title": work.get("title"),
                "author": work.get("author"),
                "workType": work.get("workType"),
                "coverPath": work.get("coverPath"),
                "metadataQuality": int(work.get("metadataQuality") or 0),
                "reasonCodes": work.get("reasonCodes") or [],
                "createdAt": work.get("createdAt"),
            }
            for work in works
        ],
    }


def _primary_edition_id(db: Session, work: dict[str, Any]) -> str | None:
    if work.get("primaryEditionId"):
        return str(work["primaryEditionId"])
    if not _has_table(db, "LibraryEdition"):
        return None
    edition = _row(
        db,
        "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0 ORDER BY COALESCE(`primary`, 0) DESC, `createdAt` ASC LIMIT 1",
        {"work_id": work["id"]},
    )
    return str(edition["id"]) if edition else None


def _run_dedupe_key(trigger: str, work_ids: list[str], supplied: str | None = None) -> str:
    if supplied:
        return supplied
    digest = hashlib.sha256("\n".join(sorted(work_ids)).encode("utf-8")).hexdigest()[:20]
    return f"{trigger.lower()}:{digest}:{time_ns()}"


def create_organize_run(
    db: Session,
    *,
    trigger: str = "MANUAL",
    work_ids: list[str] | None = None,
    dedupe_key: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    if not all(_has_table(db, table) for table in ("OrganizeRun", "OrganizeJob", "MetadataLookupTask")):
        raise ValueError("整理队列数据表尚未初始化")
    normalized_trigger = str(trigger or "MANUAL").upper()
    if normalized_trigger not in {"MANUAL", "SCHEDULE", "NEW"}:
        raise ValueError("不支持的整理任务触发方式")
    policy = get_organize_policy(db)
    selected = [str(item) for item in (work_ids or []) if str(item).strip()]
    works = eligible_organize_works(
        db,
        policy,
        work_ids=selected or None,
        trigger=normalized_trigger,
        limit=limit,
        force_selected=bool(selected) and normalized_trigger == "MANUAL",
    )
    provider_plans = {
        str(work["id"]): enabled_metadata_provider_ids(db, str(work.get("workType") or ""))
        for work in works
    }
    ids = [str(work["id"]) for work in works]
    key = _run_dedupe_key(normalized_trigger, ids, dedupe_key)
    existing = _row(db, "SELECT * FROM `OrganizeRun` WHERE `dedupeKey` = :key", {"key": key})
    if existing:
        return _run_view(existing)

    now = _now()
    run_id = _id("organize_run")
    run_status = "RUNNING" if works else "COMPLETED"
    scope = {"workIds": selected, "rules": policy["rules"]}
    db.execute(
        text(
            """
            INSERT INTO `OrganizeRun`
                (`id`, `trigger`, `scopeJson`, `dedupeKey`, `status`, `queuedCount`,
                 `completedCount`, `reviewCount`, `failedCount`, `startedAt`, `finishedAt`, `createdAt`, `updatedAt`)
            VALUES
                (:id, :trigger, :scope, :dedupe_key, :status, :queued_count,
                 0, 0, 0, :started_at, :finished_at, :now, :now)
            """
        ),
        {
            "id": run_id,
            "trigger": normalized_trigger,
            "scope": json.dumps(scope, ensure_ascii=False),
            "dedupe_key": key,
            "status": run_status,
            # The eligibility read and inserts are intentionally separated. A
            # concurrent organizer may claim a work in between; the database
            # unique index is the final arbiter, so the actual count is filled
            # after the inserts below.
            "queued_count": 0,
            "started_at": now,
            "finished_at": now if not works else None,
            "now": now,
        },
    )
    for work in works:
        work_id = str(work["id"])
        edition_id = _primary_edition_id(db, work)
        provider_order = provider_plans[work_id]
        job_id = _id("organize_job")
        task_id = _id("metadata_lookup")
        reasons = list(work.get("reasonCodes") or [])
        inserted = db.execute(
            text(
                """
                INSERT INTO `OrganizeJob`
                    (`id`, `runId`, `workId`, `editionId`, `importTaskId`, `trigger`, `status`,
                     `issueCodes`, `reasonCodes`, `summary`, `errorSummary`, `startedAt`, `finishedAt`, `createdAt`, `updatedAt`)
                VALUES
                    (:id, :run_id, :work_id, :edition_id, NULL, :trigger, 'LOOKUP_PENDING',
                     '[]', :reasons, :summary, NULL, NULL, NULL, :now, :now)
                ON CONFLICT(`workId`) WHERE `status` IN
                    ('LOOKUP_PENDING', 'PENDING', 'QUEUED', 'RUNNING', 'RETRY_WAIT', 'REVIEWING', 'FAILED')
                DO NOTHING
                """
            ),
            {
                "id": job_id,
                "run_id": run_id,
                "work_id": work_id,
                "edition_id": edition_id,
                "trigger": normalized_trigger,
                "reasons": json.dumps(reasons, ensure_ascii=False),
                "summary": "等待元数据插件识别",
                "now": now,
            },
        )
        if not inserted.rowcount:
            continue
        db.execute(
            text(
                """
                INSERT INTO `MetadataLookupTask`
                    (`id`, `workId`, `editionId`, `importTaskId`, `organizeJobId`, `status`,
                     `providerOrder`, `attempts`, `nextAttemptAt`, `createdAt`, `updatedAt`)
                VALUES
                    (:id, :work_id, :edition_id, NULL, :job_id, 'PENDING',
                     :provider_order, 0, :now, :now, :now)
                """
            ),
            {
                "id": task_id,
                "work_id": work_id,
                "edition_id": edition_id,
                "job_id": job_id,
                "provider_order": json.dumps(provider_order, ensure_ascii=False),
                "now": now,
            },
        )
        db.execute(
            text("UPDATE `LibraryWork` SET `organizeStatus` = 'LOOKUP_PENDING', `updatedAt` = :now WHERE `id` = :id"),
            {"id": work_id, "now": now},
        )
    queued_count = int(
        db.execute(
            text("SELECT COUNT(*) FROM `OrganizeJob` WHERE `runId` = :run_id"),
            {"run_id": run_id},
        ).scalar()
        or 0
    )
    db.execute(
        text(
            "UPDATE `OrganizeRun` SET `queuedCount` = :queued_count, `status` = :status, "
            "`finishedAt` = :finished_at, `updatedAt` = :now WHERE `id` = :run_id"
        ),
        {
            "run_id": run_id,
            "queued_count": queued_count,
            "status": "RUNNING" if queued_count else "COMPLETED",
            "finished_at": None if queued_count else now,
            "now": now,
        },
    )
    db.commit()
    return get_organize_run(db, run_id) or {
        "id": run_id,
        "status": "RUNNING" if queued_count else "COMPLETED",
        "queuedCount": queued_count,
    }


def _run_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "trigger": row.get("trigger"),
        "scope": _json_dict(row.get("scopeJson"), {}),
        "status": row.get("status"),
        "queuedCount": int(row.get("queuedCount") or 0),
        "completedCount": int(row.get("completedCount") or 0),
        "reviewCount": int(row.get("reviewCount") or 0),
        "failedCount": int(row.get("failedCount") or 0),
        "startedAt": row.get("startedAt"),
        "finishedAt": row.get("finishedAt"),
        "createdAt": row.get("createdAt"),
        "updatedAt": row.get("updatedAt"),
    }


def sync_organize_runs(db: Session) -> int:
    if not _has_table(db, "OrganizeRun") or not _has_table(db, "OrganizeJob"):
        return 0
    runs = _rows(db, "SELECT * FROM `OrganizeRun` WHERE `status` IN ('QUEUED', 'RUNNING')")
    updated = 0
    now = _now()
    for run in runs:
        counts = {
            str(item["status"]): int(item["count"])
            for item in _rows(
                db,
                "SELECT `status`, COUNT(*) AS `count` FROM `OrganizeJob` WHERE `runId` = :run_id GROUP BY `status`",
                {"run_id": run["id"]},
            )
        }
        completed = sum(counts.get(item, 0) for item in ("APPLIED", "COMPLETED", "DISMISSED"))
        review = counts.get("REVIEWING", 0)
        failed = counts.get("FAILED", 0)
        cancelled = counts.get("CANCELLED", 0)
        terminal = completed + review + failed + cancelled
        queued = int(run.get("queuedCount") or 0)
        done = terminal >= queued
        db.execute(
            text(
                """
                UPDATE `OrganizeRun`
                SET `status` = :status, `completedCount` = :completed,
                    `reviewCount` = :review, `failedCount` = :failed,
                    `finishedAt` = :finished_at, `updatedAt` = :now
                WHERE `id` = :id
                """
            ),
            {
                "id": run["id"],
                "status": "COMPLETED" if done else "RUNNING",
                "completed": completed,
                "review": review,
                "failed": failed,
                "finished_at": now if done else None,
                "now": now,
            },
        )
        updated += 1
    if updated:
        db.commit()
    return updated


def get_organize_run(db: Session, run_id: str) -> dict[str, Any] | None:
    sync_organize_runs(db)
    row = _row(db, "SELECT * FROM `OrganizeRun` WHERE `id` = :id", {"id": run_id}) if _has_table(db, "OrganizeRun") else None
    return _run_view(row) if row else None


def list_organize_runs(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    sync_organize_runs(db)
    if not _has_table(db, "OrganizeRun"):
        return []
    return [_run_view(row) for row in _rows(db, "SELECT * FROM `OrganizeRun` ORDER BY `createdAt` DESC LIMIT :limit", {"limit": min(max(limit, 1), 100)})]


def cancel_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = _row(db, "SELECT * FROM `OrganizeJob` WHERE `id` = :id", {"id": job_id}) if _has_table(db, "OrganizeJob") else None
    if not job:
        raise ValueError("整理任务不存在")
    if str(job.get("status")) in TERMINAL_JOB_STATUSES:
        raise ValueError("当前状态无法取消")
    now = _now()
    if _has_table(db, "MetadataLookupTask"):
        db.execute(
            text("UPDATE `MetadataLookupTask` SET `status` = 'CANCELLED', `finishedAt` = :now, `updatedAt` = :now WHERE `organizeJobId` = :id AND `status` IN ('PENDING', 'RUNNING')"),
            {"id": job_id, "now": now},
        )
    db.execute(
        text("UPDATE `OrganizeJob` SET `status` = 'CANCELLED', `summary` = '已取消', `finishedAt` = :now, `updatedAt` = :now WHERE `id` = :id"),
        {"id": job_id, "now": now},
    )
    db.execute(
        text("UPDATE `LibraryWork` SET `organizeStatus` = 'UNASSESSED', `updatedAt` = :now WHERE `id` = :work_id"),
        {"work_id": job["workId"], "now": now},
    )
    db.commit()
    sync_organize_runs(db)
    return _row(db, "SELECT * FROM `OrganizeJob` WHERE `id` = :id", {"id": job_id}) or {}


def recognize_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = _row(db, "SELECT * FROM `OrganizeJob` WHERE `id` = :id", {"id": job_id}) if _has_table(db, "OrganizeJob") else None
    if not job:
        raise ValueError("整理记录不存在")
    work = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": job["workId"]})
    if not work:
        raise ValueError("作品已不存在")
    unresolved = ", ".join(f"'{item}'" for item in UNRESOLVED_JOB_STATUSES)
    current_unresolved = _row(
        db,
        f"SELECT * FROM `OrganizeJob` WHERE `workId` = :work_id AND `id` != :id "
        f"AND `status` IN ({unresolved}) ORDER BY `updatedAt` DESC, `createdAt` DESC LIMIT 1",
        {"work_id": job["workId"], "id": job_id},
    )
    if current_unresolved:
        # Re-recognition is a work-level intent. Reuse its unresolved record
        # when the action originated from an older successful history row.
        job = current_unresolved
        job_id = str(current_unresolved["id"])
    now = _now()
    providers = enabled_metadata_provider_ids(db, str(work.get("workType") or ""))
    tasks = _rows(
        db,
        "SELECT `id` FROM `MetadataLookupTask` WHERE `organizeJobId` = :id",
        {"id": job_id},
    ) if _has_table(db, "MetadataLookupTask") else []

    # A new recognition pass owns a clean set of provider executions. Keep the
    # legacy review tables readable for old backups, but never carry their rows
    # into a new automatic run.
    if _has_table(db, "MetadataProviderExecution"):
        db.execute(text("DELETE FROM `MetadataProviderExecution` WHERE `jobId` = :id"), {"id": job_id})
        for task in tasks:
            db.execute(
                text("DELETE FROM `MetadataProviderExecution` WHERE `lookupTaskId` = :id"),
                {"id": task["id"]},
            )
    for legacy_table in ("MetadataSuggestion", "DuplicateCandidate"):
        if _has_table(db, legacy_table):
            db.execute(text(f"DELETE FROM `{legacy_table}` WHERE `jobId` = :id"), {"id": job_id})

    if _has_table(db, "MetadataLookupTask"):
        db.execute(text("DELETE FROM `MetadataLookupTask` WHERE `organizeJobId` = :id"), {"id": job_id})
    db.execute(
        text(
            """
            INSERT INTO `MetadataLookupTask`
                (`id`, `workId`, `editionId`, `organizeJobId`, `status`, `providerOrder`, `attempts`, `nextAttemptAt`, `createdAt`, `updatedAt`)
            VALUES (:id, :work_id, :edition_id, :job_id, 'PENDING', :providers, 0, :now, :now, :now)
            """
        ),
        {
            "id": _id("metadata_lookup"),
            "work_id": job["workId"],
            "edition_id": job.get("editionId"),
            "job_id": job_id,
            "providers": json.dumps(providers, ensure_ascii=False),
            "now": now,
        },
    )
    job_values: dict[str, Any] = {
        "status": "LOOKUP_PENDING",
        "summary": "等待重新识别",
        "errorSummary": None,
        "updatedAt": now,
    }
    if _has_column(db, "OrganizeJob", "trigger"):
        job_values["trigger"] = "MANUAL"
    if _has_column(db, "OrganizeJob", "reasonCodes"):
        job_values["reasonCodes"] = json.dumps(["MANUAL_RECOGNIZE"], ensure_ascii=False)
    for timestamp_column in ("startedAt", "finishedAt"):
        if _has_column(db, "OrganizeJob", timestamp_column):
            job_values[timestamp_column] = None
    assignments = ", ".join(f"`{key}` = :{key}" for key in job_values)
    db.execute(
        text(f"UPDATE `OrganizeJob` SET {assignments} WHERE `id` = :id"),
        {**job_values, "id": job_id},
    )
    db.execute(
        text("UPDATE `LibraryWork` SET `organizeStatus` = 'LOOKUP_PENDING', `updatedAt` = :now WHERE `id` = :work_id"),
        {"work_id": job["workId"], "now": now},
    )
    if job.get("runId") and _has_table(db, "OrganizeRun"):
        db.execute(
            text(
                "UPDATE `OrganizeRun` SET `status` = 'RUNNING', `finishedAt` = NULL, "
                "`updatedAt` = :now WHERE `id` = :run_id"
            ),
            {"run_id": job["runId"], "now": now},
        )
    db.commit()
    return _row(db, "SELECT * FROM `OrganizeJob` WHERE `id` = :id", {"id": job_id}) or {}


def retry_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    """Backward-compatible service alias for callers from older releases."""

    return recognize_organize_job(db, job_id)


def delete_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = _row(db, "SELECT * FROM `OrganizeJob` WHERE `id` = :id", {"id": job_id}) if _has_table(db, "OrganizeJob") else None
    if not job:
        raise ValueError("整理记录不存在")

    work_id = str(job.get("workId") or "")
    run_id = str(job.get("runId") or "") or None
    task_ids = [
        str(item["id"])
        for item in _rows(
            db,
            "SELECT `id` FROM `MetadataLookupTask` WHERE `organizeJobId` = :id",
            {"id": job_id},
        )
    ] if _has_table(db, "MetadataLookupTask") else []

    if _has_table(db, "MetadataProviderExecution"):
        db.execute(text("DELETE FROM `MetadataProviderExecution` WHERE `jobId` = :id"), {"id": job_id})
        for task_id in task_ids:
            db.execute(text("DELETE FROM `MetadataProviderExecution` WHERE `lookupTaskId` = :id"), {"id": task_id})
    for legacy_table in ("MetadataSuggestion", "DuplicateCandidate"):
        if _has_table(db, legacy_table):
            db.execute(text(f"DELETE FROM `{legacy_table}` WHERE `jobId` = :id"), {"id": job_id})
    if _has_table(db, "MetadataLookupTask"):
        db.execute(text("DELETE FROM `MetadataLookupTask` WHERE `organizeJobId` = :id"), {"id": job_id})
    db.execute(text("DELETE FROM `OrganizeJob` WHERE `id` = :id"), {"id": job_id})

    now = _now()
    if work_id and _has_table(db, "LibraryWork"):
        remaining = _row(
            db,
            "SELECT `status` FROM `OrganizeJob` WHERE `workId` = :work_id ORDER BY `createdAt` DESC LIMIT 1",
            {"work_id": work_id},
        )
        work = _row(db, "SELECT `organized` FROM `LibraryWork` WHERE `id` = :id", {"id": work_id})
        organize_status = str((remaining or {}).get("status") or ("APPLIED" if bool((work or {}).get("organized")) else "UNASSESSED"))
        db.execute(
            text("UPDATE `LibraryWork` SET `organizeStatus` = :status, `updatedAt` = :now WHERE `id` = :id"),
            {"id": work_id, "status": organize_status, "now": now},
        )
    if run_id and _has_table(db, "OrganizeRun"):
        remaining_count = int(
            db.execute(text("SELECT COUNT(*) FROM `OrganizeJob` WHERE `runId` = :run_id"), {"run_id": run_id}).scalar() or 0
        )
        db.execute(
            text(
                "UPDATE `OrganizeRun` SET `status` = 'RUNNING', `queuedCount` = :count, "
                "`finishedAt` = NULL, `updatedAt` = :now WHERE `id` = :run_id"
            ),
            {"run_id": run_id, "count": remaining_count, "now": now},
        )
    db.commit()
    sync_organize_runs(db)
    return {"id": job_id, "workId": work_id, "deleted": True}


def process_organize_schedule_tick(db: Session) -> int:
    policy = get_organize_policy(db)
    sync_organize_runs(db)
    queued = 0
    now = _now()
    if policy["autoRunOnNew"]:
        new_works = eligible_organize_works(db, policy, trigger="NEW", limit=500)
        if new_works:
            ids = [str(item["id"]) for item in new_works]
            result = create_organize_run(
                db,
                trigger="NEW",
                work_ids=ids,
                dedupe_key=f"new:{hashlib.sha256('|'.join(sorted(ids)).encode()).hexdigest()[:24]}",
            )
            queued += int(result.get("queuedCount") or 0)
    next_run = policy.get("nextRunAt")
    next_due = False
    if next_run:
        try:
            next_due = datetime.fromisoformat(str(next_run).replace("Z", "+00:00")) <= now
        except ValueError:
            next_due = True
    if policy["enabled"] and policy["scheduleMode"] == "INTERVAL" and next_due:
        due_key = f"schedule:{str(next_run)}"
        result = create_organize_run(db, trigger="SCHEDULE", dedupe_key=due_key)
        queued += int(result.get("queuedCount") or 0)
        db.execute(
            text("UPDATE `OrganizePolicy` SET `lastScheduledAt` = :now, `nextRunAt` = :next_run, `updatedAt` = :now WHERE `id` = :id"),
            {
                "id": DEFAULT_POLICY_ID,
                "now": now,
                "next_run": now + timedelta(minutes=policy["intervalMinutes"]),
            },
        )
        db.commit()
    return queued


class OrganizerScheduler:
    def __init__(self, db_factory: Callable[[], Session], poll_seconds: float = 5.0) -> None:
        self._db_factory = db_factory
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="organizer-scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(2.0, self._poll_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._db_factory() as db:
                    process_organize_schedule_tick(db)
            except Exception:
                LOGGER.exception("organizer scheduler iteration failed")
            self._stop.wait(self._poll_seconds)
