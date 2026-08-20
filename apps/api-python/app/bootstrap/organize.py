"""Organize capability composition root."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.organize.application.dto import (
    PreparedOrganizeJobEnqueue,
    PreparedOrganizePolicyUpdate,
)
from app.modules.organize.infrastructure import job_queries as organize_job_queries
from app.modules.organize.infrastructure import jobs as organize_jobs
from app.modules.organize.infrastructure import runs as organize_runs
from app.modules.organize.infrastructure.policy import (
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_POLICY_ID,
    DEFAULT_RULES,
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    ensure_organize_policy,
    get_organize_policy,
    mark_policy_scheduled,
    prepare_organize_policy_update_statement,
    write_prepared_organize_policy_update,
)
from app.modules.organize.infrastructure.runs import (
    count_jobs_for_run,
    execute_sync_organize_runs,
    get_job_row,
    get_organize_run,
    get_run_by_dedupe_key,
    list_organize_runs,
    prepare_sync_organize_runs,
    run_view,
    sync_organize_runs,
    update_run_after_enqueue,
)
from app.modules.organize.public import OrganizeWriteTransaction


def update_organize_policy_command(
    db: Session, prepared: PreparedOrganizePolicyUpdate
) -> dict[str, Any]:
    statement = prepare_organize_policy_update_statement(prepared)
    with OrganizeWriteTransaction(db):
        write_prepared_organize_policy_update(db, statement)
    return get_organize_policy(db)


def create_organize_run_command(
    db: Session,
    *,
    run_id: str,
    trigger: str,
    scope: dict[str, Any],
    dedupe_key: str,
    run_status: str,
    timestamp: datetime,
    job_plans: tuple[PreparedOrganizeJobEnqueue, ...],
) -> int:
    prepared_write = organize_jobs.prepare_organize_run_write(
        run_id=run_id,
        trigger=trigger,
        scope_json=json.dumps(scope, ensure_ascii=False),
        dedupe_key=dedupe_key,
        run_status=run_status,
        timestamp=timestamp,
        job_plans=job_plans,
    )
    with OrganizeWriteTransaction(db):
        queued_count = organize_jobs.execute_organize_run_write(db, prepared_write)
    return queued_count


def cancel_organize_job_command(
    db: Session,
    *,
    job_id: str,
    work_id: str,
    timestamp: datetime,
) -> None:
    sync_statement = prepare_sync_organize_runs(now=timestamp)
    with OrganizeWriteTransaction(db):
        organize_jobs.cancel_lookup_tasks_for_job(db, job_id=job_id, now=timestamp)
        organize_jobs.cancel_job(db, job_id=job_id, now=timestamp)
        organize_jobs.mark_work_organize_status(
            db, work_id=work_id, status="UNASSESSED", now=timestamp
        )
        execute_sync_organize_runs(db, sync_statement)


def recognize_organize_job_command(
    db: Session,
    *,
    job_id: str,
    task_ids: tuple[str, ...],
    task_id: str,
    work_id: str,
    volume_id: str | None,
    version_id: str,
    provider_order: tuple[str, ...],
    run_id: str | None,
    timestamp: datetime,
) -> None:
    prepared_task_ids = list(task_ids)
    prepared_task = organize_jobs.prepare_lookup_task_row(
        task_id=task_id,
        work_id=work_id,
        volume_id=volume_id,
        version_id=version_id,
        job_id=job_id,
        provider_order=provider_order,
        timestamp=timestamp,
    )
    with OrganizeWriteTransaction(db):
        organize_jobs.clear_job_recognition_artifacts(
            db, job_id=job_id, task_ids=prepared_task_ids
        )
        organize_jobs.insert_prepared_lookup_task(db, prepared_task)
        organize_jobs.reset_job_for_recognition(db, job_id=job_id, now=timestamp)
        organize_jobs.mark_work_organize_status(
            db, work_id=work_id, status="LOOKUP_PENDING", now=timestamp
        )
        if run_id is not None:
            organize_jobs.reopen_run(db, run_id=run_id, now=timestamp)


def delete_organize_job_command(
    db: Session,
    *,
    job_id: str,
    task_ids: tuple[str, ...],
    work_id: str,
    organize_status: str | None,
    run_id: str | None,
    timestamp: datetime,
) -> None:
    prepared_task_ids = list(task_ids)
    refresh_statement = (
        organize_jobs.prepare_refresh_run_queue_count(
            run_id=run_id,
            now=timestamp,
        )
        if run_id is not None
        else None
    )
    sync_statement = prepare_sync_organize_runs(now=timestamp)
    with OrganizeWriteTransaction(db):
        organize_jobs.delete_job_graph(
            db,
            job_id=job_id,
            task_ids=prepared_task_ids,
        )
        if work_id and organize_status is not None:
            organize_jobs.mark_work_organize_status(
                db, work_id=work_id, status=organize_status, now=timestamp
            )
        if refresh_statement is not None:
            organize_jobs.execute_refresh_run_queue_count(db, refresh_statement)
        execute_sync_organize_runs(db, sync_statement)


def sync_organize_runs_command(db: Session) -> int:
    statement = prepare_sync_organize_runs(now=datetime.now(UTC))
    with OrganizeWriteTransaction(db):
        updated = execute_sync_organize_runs(db, statement)
    return updated


def mark_organize_policy_scheduled_command(
    db: Session, *, timestamp: datetime, next_run_at: datetime
) -> None:
    with OrganizeWriteTransaction(db):
        mark_policy_scheduled(db, now=timestamp, next_run_at=next_run_at)

__all__ = [
    "DEFAULT_INTERVAL_MINUTES",
    "DEFAULT_POLICY_ID",
    "DEFAULT_RULES",
    "MAX_INTERVAL_MINUTES",
    "MIN_INTERVAL_MINUTES",
    "organize_job_queries",
    "organize_jobs",
    "organize_runs",
    "count_jobs_for_run",
    "ensure_organize_policy",
    "get_job_row",
    "get_organize_policy",
    "get_organize_run",
    "get_run_by_dedupe_key",
    "list_organize_runs",
    "mark_policy_scheduled",
    "run_view",
    "sync_organize_runs",
    "update_run_after_enqueue",
    "cancel_organize_job_command",
    "create_organize_run_command",
    "delete_organize_job_command",
    "mark_organize_policy_scheduled_command",
    "recognize_organize_job_command",
    "sync_organize_runs_command",
    "update_organize_policy_command",
]
