"""ORM persistence for organize job create / cancel / recognize / delete."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, func, insert, inspect, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.models.library import LibraryWork
from app.models.organize import (
    DuplicateCandidate,
    MetadataLookupTask,
    MetadataProviderExecution,
    MetadataSuggestion,
    OrganizeJob,
    OrganizeRun,
)
from app.modules.organize.application.dto import PreparedOrganizeJobEnqueue
from app.modules.organize.infrastructure.eligibility import UNRESOLVED_JOB_STATUSES
from app.modules.organize.infrastructure.runs import job_entity_as_legacy_dict

ACTIVE_LOOKUP_STATUSES = ("PENDING", "RUNNING")


@dataclass(frozen=True, slots=True)
class PreparedOrganizeRunWrite:
    run_statement: Executable
    job_statement: Executable | None
    task_rows_by_job_id: dict[str, dict[str, object]]
    task_insert_statement: Executable
    work_statement: Executable | None
    finalize_statement: Executable


def prepare_organize_run_write(
    *,
    run_id: str,
    trigger: str,
    scope_json: str,
    dedupe_key: str,
    run_status: str,
    timestamp: datetime,
    job_plans: tuple[PreparedOrganizeJobEnqueue, ...],
) -> PreparedOrganizeRunWrite:
    """Build every row and typed statement before SQLite's first DML."""

    run_statement = insert(OrganizeRun).values(
        id=run_id,
        trigger=trigger,
        scope_json=scope_json,
        dedupe_key=dedupe_key,
        status=run_status,
        queued_count=0,
        completed_count=0,
        review_count=0,
        failed_count=0,
        started_at=timestamp,
        finished_at=timestamp if not job_plans else None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    job_rows = tuple(
        {
            "id": plan.job_id,
            "run_id": run_id,
            "work_id": plan.work_id,
            "volume_id": plan.volume_id,
            "version_id": plan.version_id,
            "import_task_id": None,
            "trigger": trigger,
            "status": "LOOKUP_PENDING",
            "issue_codes": "[]",
            "reason_codes": json.dumps(plan.reasons, ensure_ascii=False),
            "summary": "等待元数据插件识别",
            "error_summary": None,
            "started_at": None,
            "finished_at": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        for plan in job_plans
    )
    job_statement = (
        sqlite_insert(OrganizeJob)
        .values(list(job_rows))
        .on_conflict_do_nothing(
            index_elements=[OrganizeJob.work_id],
            index_where=OrganizeJob.status.in_(UNRESOLVED_JOB_STATUSES),
        )
        .returning(OrganizeJob.id)
        if job_rows
        else None
    )
    task_rows_by_job_id = {
        plan.job_id: {
            "id": plan.task_id,
            "work_id": plan.work_id,
            "volume_id": plan.volume_id,
            "version_id": plan.version_id,
            "import_task_id": None,
            "organize_job_id": plan.job_id,
            "status": "PENDING",
            "provider_order": json.dumps(plan.provider_order, ensure_ascii=False),
            "attempts": 0,
            "next_attempt_at": timestamp,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        for plan in job_plans
    }
    work_ids_for_run = select(OrganizeJob.work_id).where(
        OrganizeJob.run_id == run_id
    )
    work_statement = (
        update(LibraryWork)
        .where(LibraryWork.id.in_(work_ids_for_run))
        .values(organize_status="LOOKUP_PENDING", updated_at=timestamp)
        if job_plans
        else None
    )
    queued_count = (
        select(func.count())
        .select_from(OrganizeJob)
        .where(OrganizeJob.run_id == run_id)
        .scalar_subquery()
    )
    finalize_statement = (
        update(OrganizeRun)
        .where(OrganizeRun.id == run_id)
        .values(
            queued_count=queued_count,
            status=case((queued_count > 0, "RUNNING"), else_="COMPLETED"),
            finished_at=case((queued_count > 0, None), else_=timestamp),
            updated_at=timestamp,
        )
    )
    return PreparedOrganizeRunWrite(
        run_statement=run_statement,
        job_statement=job_statement,
        task_rows_by_job_id=task_rows_by_job_id,
        task_insert_statement=insert(MetadataLookupTask),
        work_statement=work_statement,
        finalize_statement=finalize_statement,
    )


def execute_organize_run_write(
    db: Session,
    prepared: PreparedOrganizeRunWrite,
) -> int:
    db.execute(prepared.run_statement)
    inserted_job_ids = (
        set(db.scalars(prepared.job_statement))
        if prepared.job_statement is not None
        else set()
    )
    task_rows = tuple(
        prepared.task_rows_by_job_id[job_id] for job_id in inserted_job_ids
    )
    if task_rows:
        db.execute(prepared.task_insert_statement, list(task_rows))
    if prepared.work_statement is not None:
        db.execute(prepared.work_statement)
    db.execute(prepared.finalize_statement)
    return len(inserted_job_ids)


def prepare_lookup_task_row(
    *,
    task_id: str,
    work_id: str,
    volume_id: str | None,
    version_id: str | None,
    job_id: str,
    provider_order: tuple[str, ...],
    timestamp: datetime,
) -> dict[str, object]:
    return {
        "id": task_id,
        "work_id": work_id,
        "volume_id": volume_id,
        "version_id": version_id,
        "import_task_id": None,
        "organize_job_id": job_id,
        "status": "PENDING",
        "provider_order": json.dumps(provider_order, ensure_ascii=False),
        "attempts": 0,
        "next_attempt_at": timestamp,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def insert_prepared_lookup_task(
    db: Session,
    prepared_row: dict[str, object],
) -> None:
    db.execute(insert(MetadataLookupTask), [prepared_row])


def _has_table(db: Session, table: str) -> bool:
    # Use the session connection. inspect(engine) on StaticPool :memory:
    # can checkout the shared connection and roll back in-flight writes.
    return inspect(db.connection()).has_table(table)


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
            reason_codes='["MANUAL_RECOGNIZE"]',
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


def latest_job_status_for_work_excluding(
    db: Session, work_id: str, excluded_job_id: str
) -> str | None:
    return db.scalar(
        select(OrganizeJob.status)
        .where(
            OrganizeJob.work_id == work_id,
            OrganizeJob.id != excluded_job_id,
        )
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
    return job_ids


def prepare_refresh_run_queue_count(
    *, run_id: str, now: datetime
) -> Executable:
    queued_count = (
        select(func.count())
        .select_from(OrganizeJob)
        .where(OrganizeJob.run_id == run_id)
        .scalar_subquery()
    )
    return (
        update(OrganizeRun)
        .where(OrganizeRun.id == run_id)
        .values(
            status="RUNNING",
            queued_count=queued_count,
            finished_at=None,
            updated_at=now,
        )
    )


def execute_refresh_run_queue_count(db: Session, statement: Executable) -> None:
    db.execute(statement)
