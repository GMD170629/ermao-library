"""Organize capability composition root."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.metadata.infrastructure import external_cache as metadata_cache
from app.modules.organize.application.dto import (
    PreparedDuplicateAction,
    PreparedOrganizeJobEnqueue,
    PreparedOrganizePolicyUpdate,
)
from app.modules.organize.infrastructure import duplicates as organize_duplicates
from app.modules.organize.infrastructure import job_queries as organize_job_queries
from app.modules.organize.infrastructure import jobs as organize_jobs
from app.modules.organize.infrastructure import review as organize_review
from app.modules.organize.infrastructure import runs as organize_runs
from app.modules.organize.infrastructure import suggestions as organize_suggestions
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


def dismiss_organize_job_command(
    db: Session,
    *,
    job_row: dict[str, Any],
    work_row: dict[str, Any] | None,
) -> None:
    prepared_jobs = organize_review.prepare_job_update_rows((job_row,))
    prepared_works = organize_review.prepare_work_update_rows(
        (work_row,) if work_row is not None else ()
    )
    with OrganizeWriteTransaction(db):
        organize_review.write_prepared_job_updates(db, prepared_jobs)
        organize_review.write_prepared_work_updates(db, prepared_works)


def apply_organize_job_command(
    db: Session,
    *,
    work_row: dict[str, Any] | None,
    suggestion_ids: tuple[str, ...],
    duplicate_actions: tuple[PreparedDuplicateAction, ...],
    dismiss_job_id: str | None,
    job_row: dict[str, Any],
) -> None:
    prepared_works = organize_review.prepare_work_update_rows(
        (work_row,) if work_row is not None else ()
    )
    prepared_jobs = organize_review.prepare_job_update_rows((job_row,))
    prepared_suggestion_ids = list(suggestion_ids)
    prepared_duplicates = organize_duplicates.prepare_duplicate_actions_write(
        db, duplicate_actions
    )
    with OrganizeWriteTransaction(db):
        organize_review.write_prepared_work_updates(db, prepared_works)
        if prepared_suggestion_ids:
            organize_suggestions.mark_suggestions_applied(
                db, prepared_suggestion_ids
            )
        organize_duplicates.execute_duplicate_actions_write(db, prepared_duplicates)
        if dismiss_job_id is not None:
            organize_suggestions.dismiss_pending_suggestions(db, dismiss_job_id)
            organize_duplicates.dismiss_pending_duplicates(db, dismiss_job_id)
        organize_review.write_prepared_job_updates(db, prepared_jobs)


def apply_duplicate_actions_command(
    db: Session, actions: tuple[PreparedDuplicateAction, ...]
) -> None:
    prepared = organize_duplicates.prepare_duplicate_actions_write(db, actions)
    with OrganizeWriteTransaction(db):
        organize_duplicates.execute_duplicate_actions_write(db, prepared)


def set_organize_work_hidden_command(
    db: Session,
    *,
    work_id: str,
    hidden: bool,
    organize_status: str,
    timestamp: datetime,
) -> None:
    with OrganizeWriteTransaction(db):
        organize_duplicates.set_work_hidden(
            db,
            work_id=work_id,
            hidden=hidden,
            organize_status=organize_status,
            now=timestamp,
        )


def fail_organize_job_command(db: Session, job_row: dict[str, Any]) -> None:
    prepared_jobs = organize_review.prepare_job_update_rows((job_row,))
    with OrganizeWriteTransaction(db):
        organize_review.write_prepared_job_updates(db, prepared_jobs)


def refresh_organize_job_command(
    db: Session,
    *,
    job_id: str,
    duplicate_chunks: tuple[tuple[dict[str, Any], ...], ...],
    job_row: dict[str, Any],
    work_row: dict[str, Any],
) -> None:
    prepared_jobs = organize_review.prepare_job_update_rows((job_row,))
    prepared_works = organize_review.prepare_work_update_rows((work_row,))
    with OrganizeWriteTransaction(db):
        organize_duplicates.delete_pending_duplicates(db, job_id)
        for chunk in duplicate_chunks:
            organize_duplicates.insert_duplicate_candidates(db, chunk)
        organize_review.write_prepared_job_updates(db, prepared_jobs)
        organize_review.write_prepared_work_updates(db, prepared_works)


def create_legacy_organize_job_command(
    db: Session,
    *,
    job_id: str,
    work_id: str,
    volume_id: str | None,
    status: str,
    issue_codes_json: str,
    summary: str,
    timestamp: datetime,
) -> dict[str, Any]:
    with OrganizeWriteTransaction(db):
        created = organize_review.insert_organize_job(
            db,
            job_id=job_id,
            work_id=work_id,
            volume_id=volume_id,
            status=status,
            issue_codes_json=issue_codes_json,
            summary=summary,
            now=timestamp,
        )
    return created


def upsert_external_metadata_cache_command(
    db: Session,
    *,
    entry_id: str,
    provider: str,
    query_key: str,
    raw_json: str,
    expires_at_ms: int,
    now_ms: int,
) -> None:
    with OrganizeWriteTransaction(db):
        metadata_cache.upsert_cache_entry(
            db,
            entry_id=entry_id,
            provider=provider,
            query_key=query_key,
            raw_json=raw_json,
            expires_at_ms=expires_at_ms,
            now_ms=now_ms,
        )


def insert_organize_suggestions_command(
    db: Session, chunks: tuple[tuple[dict[str, Any], ...], ...]
) -> None:
    with OrganizeWriteTransaction(db):
        for chunk in chunks:
            organize_suggestions.insert_suggestions(db, chunk)


def refresh_duplicate_candidates_command(
    db: Session,
    *,
    job_id: str,
    chunks: tuple[tuple[dict[str, Any], ...], ...],
) -> None:
    with OrganizeWriteTransaction(db):
        organize_duplicates.delete_pending_duplicates(db, job_id)
        for chunk in chunks:
            organize_duplicates.insert_duplicate_candidates(db, chunk)


def bulk_apply_organize_jobs_command(
    db: Session,
    *,
    work_rows: tuple[dict[str, Any], ...],
    job_rows: tuple[dict[str, Any], ...],
    suggestion_id_chunks: tuple[tuple[str, ...], ...],
    dismiss_job_chunks: tuple[tuple[str, ...], ...],
) -> None:
    prepared_works = organize_review.prepare_work_update_rows(work_rows)
    prepared_jobs = organize_review.prepare_job_update_rows(job_rows)
    prepared_suggestion_chunks = tuple(list(chunk) for chunk in suggestion_id_chunks)
    with OrganizeWriteTransaction(db):
        organize_review.write_prepared_work_updates(db, prepared_works)
        organize_review.write_prepared_job_updates(db, prepared_jobs)
        for chunk in prepared_suggestion_chunks:
            organize_suggestions.mark_suggestions_applied(db, chunk)
        for chunk in dismiss_job_chunks:
            organize_suggestions.dismiss_pending_suggestions_for_jobs(db, chunk)
            organize_duplicates.dismiss_pending_duplicates_for_jobs(db, chunk)


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
    "apply_duplicate_actions_command",
    "apply_organize_job_command",
    "bulk_apply_organize_jobs_command",
    "create_legacy_organize_job_command",
    "dismiss_organize_job_command",
    "fail_organize_job_command",
    "insert_organize_suggestions_command",
    "refresh_duplicate_candidates_command",
    "refresh_organize_job_command",
    "set_organize_work_hidden_command",
    "upsert_external_metadata_cache_command",
    "cancel_organize_job_command",
    "create_organize_run_command",
    "delete_organize_job_command",
    "mark_organize_policy_scheduled_command",
    "recognize_organize_job_command",
    "sync_organize_runs_command",
    "update_organize_policy_command",
]
