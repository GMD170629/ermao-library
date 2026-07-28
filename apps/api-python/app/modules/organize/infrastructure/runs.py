"""ORM persistence for OrganizeRun / OrganizeJob list and sync paths."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, inspect, select, update
from sqlalchemy.orm import Session

from app.models.organize import OrganizeJob, OrganizeRun
from app.modules.organize.infrastructure.policy import DEFAULT_RULES

ACTIVE_RUN_STATUSES = ("QUEUED", "RUNNING")


def _now() -> datetime:
    return datetime.now(UTC)


def has_run_table(db: Session) -> bool:
    return inspect(db.connection()).has_table("OrganizeRun")


def has_job_table(db: Session) -> bool:
    return inspect(db.connection()).has_table("OrganizeJob")


def run_entity_as_legacy_dict(entity: OrganizeRun) -> dict[str, Any]:
    """Map an ORM run to camelCase keys matching legacy raw-SQL row dicts."""

    return {
        "id": entity.id,
        "trigger": entity.trigger,
        "scopeJson": entity.scope_json,
        "dedupeKey": entity.dedupe_key,
        "status": entity.status,
        "queuedCount": entity.queued_count,
        "completedCount": entity.completed_count,
        "reviewCount": entity.review_count,
        "failedCount": entity.failed_count,
        "startedAt": entity.started_at,
        "finishedAt": entity.finished_at,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def job_entity_as_legacy_dict(entity: OrganizeJob) -> dict[str, Any]:
    """Map an ORM job to camelCase keys matching legacy raw-SQL row dicts."""

    return {
        "id": entity.id,
        "runId": entity.run_id,
        "workId": entity.work_id,
        "editionId": entity.edition_id,
        "importTaskId": entity.import_task_id,
        "trigger": entity.trigger,
        "status": entity.status,
        "issueCodes": entity.issue_codes,
        "reasonCodes": entity.reason_codes,
        "summary": entity.summary,
        "errorSummary": entity.error_summary,
        "startedAt": entity.started_at,
        "finishedAt": entity.finished_at,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def _json_dict(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return dict(fallback)
    return parsed if isinstance(parsed, dict) else dict(fallback)


def run_view(row: dict[str, Any]) -> dict[str, Any]:
    stored_scope = _json_dict(row.get("scopeJson"), {})
    stored_work_ids = stored_scope.get("workIds")
    work_ids = (
        [str(work_id).strip() for work_id in stored_work_ids if str(work_id).strip()]
        if isinstance(stored_work_ids, list)
        else []
    )
    stored_rules = stored_scope.get("rules")
    rules = stored_rules if isinstance(stored_rules, dict) else {}
    return {
        "id": row.get("id"),
        "trigger": row.get("trigger"),
        "scope": {
            "workIds": work_ids,
            "rules": {
                "unrecognized": bool(
                    rules.get("unrecognized", DEFAULT_RULES["unrecognized"])
                ),
                "missingMetadata": bool(
                    rules.get(
                        "missingMetadata",
                        DEFAULT_RULES["missingMetadata"],
                    )
                ),
            },
        },
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


def get_run_row(db: Session, run_id: str) -> dict[str, Any] | None:
    entity = db.scalar(select(OrganizeRun).where(OrganizeRun.id == run_id))
    return run_entity_as_legacy_dict(entity) if entity is not None else None


def get_run_by_dedupe_key(db: Session, dedupe_key: str) -> dict[str, Any] | None:
    entity = db.scalar(select(OrganizeRun).where(OrganizeRun.dedupe_key == dedupe_key))
    return run_entity_as_legacy_dict(entity) if entity is not None else None


def list_run_rows(db: Session, limit: int) -> list[dict[str, Any]]:
    bounded = min(max(limit, 1), 100)
    rows = db.scalars(
        select(OrganizeRun).order_by(OrganizeRun.created_at.desc()).limit(bounded)
    ).all()
    return [run_entity_as_legacy_dict(row) for row in rows]


def get_job_row(db: Session, job_id: str) -> dict[str, Any] | None:
    entity = db.scalar(select(OrganizeJob).where(OrganizeJob.id == job_id))
    return job_entity_as_legacy_dict(entity) if entity is not None else None


def count_jobs_for_run(db: Session, run_id: str) -> int:
    return int(
        db.scalar(select(func.count()).select_from(OrganizeJob).where(OrganizeJob.run_id == run_id))
        or 0
    )


def job_status_counts_for_run(db: Session, run_id: str) -> dict[str, int]:
    rows = db.execute(
        select(OrganizeJob.status, func.count())
        .where(OrganizeJob.run_id == run_id)
        .group_by(OrganizeJob.status)
    ).all()
    return {str(status): int(count) for status, count in rows}


def update_run_after_enqueue(
    db: Session,
    *,
    run_id: str,
    queued_count: int,
    status: str,
    finished_at: datetime | None,
    now: datetime,
) -> None:
    db.execute(
        update(OrganizeRun)
        .where(OrganizeRun.id == run_id)
        .values(
            queued_count=queued_count,
            status=status,
            finished_at=finished_at,
            updated_at=now,
        )
    )


def sync_organize_runs(db: Session) -> int:
    if not has_run_table(db) or not has_job_table(db):
        return 0
    runs = db.scalars(select(OrganizeRun).where(OrganizeRun.status.in_(ACTIVE_RUN_STATUSES))).all()
    updated = 0
    now = _now()
    for run in runs:
        counts = job_status_counts_for_run(db, run.id)
        completed = sum(counts.get(item, 0) for item in ("APPLIED", "COMPLETED", "DISMISSED"))
        review = counts.get("REVIEWING", 0)
        failed = counts.get("FAILED", 0)
        cancelled = counts.get("CANCELLED", 0)
        terminal = completed + review + failed + cancelled
        queued = int(run.queued_count or 0)
        done = terminal >= queued
        db.execute(
            update(OrganizeRun)
            .where(OrganizeRun.id == run.id)
            .values(
                status="COMPLETED" if done else "RUNNING",
                completed_count=completed,
                review_count=review,
                failed_count=failed,
                finished_at=now if done else None,
                updated_at=now,
            )
        )
        updated += 1
    if updated:
        db.flush()
    return updated


def projected_run_view(db: Session, row: dict[str, Any]) -> dict[str, Any]:
    """Calculate the latest run projection without mutating persistent state."""

    if str(row.get("status") or "") not in ACTIVE_RUN_STATUSES:
        return run_view(row)
    counts = job_status_counts_for_run(db, str(row["id"]))
    completed = sum(
        counts.get(item, 0) for item in ("APPLIED", "COMPLETED", "DISMISSED")
    )
    review = counts.get("REVIEWING", 0)
    failed = counts.get("FAILED", 0)
    cancelled = counts.get("CANCELLED", 0)
    queued = int(row.get("queuedCount") or 0)
    done = completed + review + failed + cancelled >= queued
    return run_view(
        {
            **row,
            "status": "COMPLETED" if done else "RUNNING",
            "completedCount": completed,
            "reviewCount": review,
            "failedCount": failed,
            "finishedAt": row.get("finishedAt") if done else None,
        }
    )


def get_organize_run(db: Session, run_id: str) -> dict[str, Any] | None:
    if not has_run_table(db):
        return None
    row = get_run_row(db, run_id)
    return projected_run_view(db, row) if row else None


def list_organize_runs(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    if not has_run_table(db):
        return []
    return [projected_run_view(db, row) for row in list_run_rows(db, limit)]
