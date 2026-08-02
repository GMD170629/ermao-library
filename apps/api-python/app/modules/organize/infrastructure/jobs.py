"""ORM persistence for organize job create / cancel / recognize / delete."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, inspect, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.library import LibraryWork
from app.models.organize import (
    DuplicateCandidate,
    MetadataLookupTask,
    MetadataProviderExecution,
    MetadataSuggestion,
    OrganizeJob,
    OrganizeRun,
)
from app.modules.organize.infrastructure.eligibility import UNRESOLVED_JOB_STATUSES
from app.modules.organize.infrastructure.runs import (
    count_jobs_for_run,
    job_entity_as_legacy_dict,
    update_run_after_enqueue,
)

ACTIVE_LOOKUP_STATUSES = ("PENDING", "RUNNING")


def _has_table(db: Session, table: str) -> bool:
    # Use the session connection. inspect(engine) on StaticPool :memory:
    # can checkout the shared connection and roll back in-flight writes.
    return inspect(db.connection()).has_table(table)


def insert_organize_run(
    db: Session,
    *,
    run_id: str,
    trigger: str,
    scope: dict[str, Any],
    dedupe_key: str,
    status: str,
    started_at: Any,
    finished_at: Any,
    now: Any,
) -> None:
    db.add(
        OrganizeRun(
            id=run_id,
            trigger=trigger,
            scope_json=json.dumps(scope, ensure_ascii=False),
            dedupe_key=dedupe_key,
            status=status,
            queued_count=0,
            completed_count=0,
            review_count=0,
            failed_count=0,
            started_at=started_at,
            finished_at=finished_at,
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()


def try_insert_unresolved_job(
    db: Session,
    *,
    job_id: str,
    run_id: str,
    work_id: str,
    volume_id: str | None,
    trigger: str,
    reasons: list[str],
    summary: str,
    now: Any,
) -> bool:
    """Insert a job unless an unresolved job already exists for the work.

    Uses the partial unique index OrganizeJob_unresolved_workId_key.
    """

    statement = (
        sqlite_insert(OrganizeJob)
        .values(
            id=job_id,
            run_id=run_id,
            work_id=work_id,
            volume_id=volume_id,
            import_task_id=None,
            trigger=trigger,
            status="LOOKUP_PENDING",
            issue_codes="[]",
            reason_codes=json.dumps(reasons, ensure_ascii=False),
            summary=summary,
            error_summary=None,
            started_at=None,
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[OrganizeJob.work_id],
            index_where=OrganizeJob.status.in_(UNRESOLVED_JOB_STATUSES),
        )
    )
    result = db.execute(statement)
    return bool(result.rowcount)


def insert_lookup_task(
    db: Session,
    *,
    task_id: str,
    work_id: str,
    volume_id: str | None,
    job_id: str,
    provider_order: list[str],
    now: Any,
) -> None:
    db.add(
        MetadataLookupTask(
            id=task_id,
            work_id=work_id,
            volume_id=volume_id,
            import_task_id=None,
            organize_job_id=job_id,
            status="PENDING",
            provider_order=json.dumps(provider_order, ensure_ascii=False),
            attempts=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def mark_work_organize_status(
    db: Session, *, work_id: str, status: str, now: Any
) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(organize_status=status, updated_at=now)
    )


def cancel_lookup_tasks_for_job(db: Session, *, job_id: str, now: Any) -> None:
    if not _has_table(db, "MetadataLookupTask"):
        return
    db.execute(
        update(MetadataLookupTask)
        .where(
            MetadataLookupTask.organize_job_id == job_id,
            MetadataLookupTask.status.in_(ACTIVE_LOOKUP_STATUSES),
        )
        .values(status="CANCELLED", finished_at=now, updated_at=now)
    )


def cancel_job(db: Session, *, job_id: str, now: Any) -> None:
    db.execute(
        update(OrganizeJob)
        .where(OrganizeJob.id == job_id)
        .values(status="CANCELLED", summary="已取消", finished_at=now, updated_at=now)
    )


def get_work_row(db: Session, work_id: str) -> dict[str, Any] | None:
    from app.modules.organize.infrastructure.eligibility import (
        work_entity_as_legacy_dict,
    )

    entity = db.get(LibraryWork, work_id)
    return work_entity_as_legacy_dict(entity) if entity is not None else None


def get_unresolved_job_for_work(
    db: Session,
    *,
    work_id: str,
    exclude_job_id: str,
) -> dict[str, Any] | None:
    entity = db.scalars(
        select(OrganizeJob)
        .where(
            OrganizeJob.work_id == work_id,
            OrganizeJob.id != exclude_job_id,
            OrganizeJob.status.in_(UNRESOLVED_JOB_STATUSES),
        )
        .order_by(OrganizeJob.updated_at.desc(), OrganizeJob.created_at.desc())
        .limit(1)
    ).first()
    return job_entity_as_legacy_dict(entity) if entity is not None else None


def list_lookup_task_ids_for_job(db: Session, job_id: str) -> list[str]:
    if not _has_table(db, "MetadataLookupTask"):
        return []
    return list(
        db.scalars(
            select(MetadataLookupTask.id).where(
                MetadataLookupTask.organize_job_id == job_id
            )
        ).all()
    )


def clear_job_recognition_artifacts(
    db: Session, *, job_id: str, task_ids: list[str]
) -> None:
    present = {
        name
        for name in (
            "MetadataProviderExecution",
            "MetadataSuggestion",
            "DuplicateCandidate",
            "MetadataLookupTask",
        )
        if _has_table(db, name)
    }
    if "MetadataProviderExecution" in present:
        db.execute(
            delete(MetadataProviderExecution).where(
                MetadataProviderExecution.job_id == job_id
            )
        )
        if task_ids:
            db.execute(
                delete(MetadataProviderExecution).where(
                    MetadataProviderExecution.lookup_task_id.in_(task_ids)
                )
            )
    if "MetadataSuggestion" in present:
        db.execute(
            delete(MetadataSuggestion).where(MetadataSuggestion.job_id == job_id)
        )
    if "DuplicateCandidate" in present:
        db.execute(
            delete(DuplicateCandidate).where(DuplicateCandidate.job_id == job_id)
        )
    if "MetadataLookupTask" in present:
        db.execute(
            delete(MetadataLookupTask).where(
                MetadataLookupTask.organize_job_id == job_id
            )
        )


def reset_job_for_recognition(
    db: Session,
    *,
    job_id: str,
    now: Any,
) -> None:
    db.execute(
        update(OrganizeJob)
        .where(OrganizeJob.id == job_id)
        .values(
            status="LOOKUP_PENDING",
            summary="等待重新识别",
            error_summary=None,
            trigger="MANUAL",
            reason_codes=json.dumps(["MANUAL_RECOGNIZE"], ensure_ascii=False),
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
    )


def reopen_run(db: Session, *, run_id: str, now: Any) -> None:
    if not _has_table(db, "OrganizeRun"):
        return
    db.execute(
        update(OrganizeRun)
        .where(OrganizeRun.id == run_id)
        .values(status="RUNNING", finished_at=None, updated_at=now)
    )


def delete_job_graph(db: Session, *, job_id: str, task_ids: list[str]) -> None:
    clear_job_recognition_artifacts(db, job_id=job_id, task_ids=task_ids)
    db.execute(delete(OrganizeJob).where(OrganizeJob.id == job_id))


def latest_job_status_for_work(db: Session, work_id: str) -> str | None:
    return db.scalar(
        select(OrganizeJob.status)
        .where(OrganizeJob.work_id == work_id)
        .order_by(OrganizeJob.created_at.desc())
        .limit(1)
    )


def work_is_organized(db: Session, work_id: str) -> bool:
    return bool(
        db.scalar(select(LibraryWork.organized).where(LibraryWork.id == work_id))
    )


def finish_unresolved_jobs_for_work(
    db: Session,
    *,
    work_id: str,
    now: Any,
) -> list[str]:
    statuses = ("PENDING", "REVIEWING", "FAILED")
    job_ids = [
        str(job_id)
        for job_id in db.scalars(
            select(OrganizeJob.id).where(
                OrganizeJob.work_id == work_id,
                OrganizeJob.status.in_(statuses),
            )
        ).all()
    ]
    if job_ids:
        db.execute(
            update(OrganizeJob)
            .where(OrganizeJob.id.in_(job_ids))
            .values(
                status="APPLIED",
                summary="元数据已应用，整理完成",
                error_summary=None,
                updated_at=now,
            )
        )
        db.flush()
    return job_ids


def refresh_run_queue_count(db: Session, *, run_id: str, now: Any) -> None:
    remaining_count = count_jobs_for_run(db, run_id)
    db.execute(
        update(OrganizeRun)
        .where(OrganizeRun.id == run_id)
        .values(
            status="RUNNING",
            queued_count=remaining_count,
            finished_at=None,
            updated_at=now,
        )
    )


def finalize_run_enqueue(db: Session, *, run_id: str, now: Any) -> int:
    queued_count = count_jobs_for_run(db, run_id)
    update_run_after_enqueue(
        db,
        run_id=run_id,
        queued_count=queued_count,
        status="RUNNING" if queued_count else "COMPLETED",
        finished_at=None if queued_count else now,
        now=now,
    )
    return queued_count
