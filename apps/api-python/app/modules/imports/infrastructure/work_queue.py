"""ORM adapter for the single persistent import work queue."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.import_pipeline import ImportScanJob, ImportTask, ImportWorkItem
from app.models.library import LibraryFile
from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.imports.application.work_queue_dto import (
    ImportScanJobDTO,
    ImportScanStatus,
    ImportWorkItemDTO,
    ImportWorkKind,
    ImportWorkStatus,
    ScanErrorDTO,
)
from app.modules.imports.infrastructure.source_keys import source_key
from app.modules.imports.infrastructure.task_mapper import import_task_dto_from_row

ACTIVE_SCAN_STATUSES = ("PENDING", "RUNNING")
IMPORT_WORK_HIGH_WATERMARK = 2_000


def _work_dto(row: ImportWorkItem) -> ImportWorkItemDTO:
    return ImportWorkItemDTO(
        id=row.id,
        kind=cast(ImportWorkKind, row.kind),
        scan_job_id=row.scan_job_id,
        import_task_id=row.import_task_id,
        status=cast(ImportWorkStatus, row.status),
        attempts=row.attempts,
    )


def scan_job_dto(row: ImportScanJob) -> ImportScanJobDTO:
    error_samples = tuple(
        ScanErrorDTO(
            path=str(item.get("path") or ""),
            error=str(item.get("error") or ""),
            code=str(item["code"]) if item.get("code") is not None else None,
            limit=int(item["limit"]) if item.get("limit") is not None else None,
            observed_count=(
                int(item["observedCount"])
                if item.get("observedCount") is not None
                else None
            ),
        )
        for item in (row.error_samples or [])
        if isinstance(item, dict)
    )
    return ImportScanJobDTO(
        id=row.id,
        monitor_folder_id=row.monitor_folder_id,
        actor_user_id=row.actor_user_id,
        root_path=row.root_path,
        trigger=row.trigger,
        status=cast(ImportScanStatus, row.status),
        directories_scanned=row.directories_scanned,
        files_scanned=row.files_scanned,
        candidates_found=row.candidates_found,
        queued_count=row.queued_count,
        skipped_count=row.skipped_count,
        error_count=row.error_count,
        ignored_reason_counts=dict(row.ignored_reason_counts or {}),
        error_samples=error_samples,
        restart_count=row.restart_count,
        started_at=row.started_at,
        heartbeat_at=row.heartbeat_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def ensure_import_work_item(
    db: Session,
    task: ImportTask,
    *,
    available_at: datetime | None = None,
    priority: int = 10,
) -> ImportWorkItem:
    existing = db.scalar(
        select(ImportWorkItem).where(ImportWorkItem.import_task_id == task.id).limit(1)
    )
    now = db_timestamp()
    key = task.source_key or source_key(task.source_path)
    task.source_key = key
    if existing is not None:
        if existing.status == "PENDING":
            existing.available_at = available_at or now
            existing.updated_at = now
        return existing
    work = ImportWorkItem(
        id=f"work_{uuid4().hex}",
        kind="IMPORT_SOURCE",
        import_task_id=task.id,
        scan_job_id=None,
        dedupe_key=f"import:{key}:{task.id}",
        status="PENDING",
        priority=priority,
        available_at=available_at or now,
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    db.add(work)
    db.flush()
    return work


def create_or_reuse_scan_job(
    db: Session,
    *,
    monitor_folder_id: str,
    actor_user_id: str | None,
    root_path: Path,
    trigger: str,
    available_at: datetime | None = None,
) -> tuple[ImportScanJobDTO, bool]:
    canonical = root_path.expanduser().resolve()
    dedupe_key = f"scan:{monitor_folder_id}:{source_key(canonical)}"
    existing_work = db.scalar(
        select(ImportWorkItem).where(ImportWorkItem.dedupe_key == dedupe_key).limit(1)
    )
    if existing_work is not None and existing_work.scan_job_id is not None:
        existing_job = db.get(ImportScanJob, existing_work.scan_job_id)
        if existing_job is not None:
            if existing_work.status == "PENDING" and available_at is not None:
                existing_work.available_at = available_at
                existing_work.updated_at = db_timestamp()
            return scan_job_dto(existing_job), False
    now = db_timestamp()
    job = ImportScanJob(
        id=f"scan_{uuid4().hex}",
        monitor_folder_id=monitor_folder_id,
        actor_user_id=actor_user_id,
        root_path=str(canonical),
        trigger=trigger,
        status="PENDING",
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    db.add(
        ImportWorkItem(
            id=f"work_{uuid4().hex}",
            kind="SCAN_DIRECTORY",
            scan_job_id=job.id,
            import_task_id=None,
            dedupe_key=dedupe_key,
            status="PENDING",
            priority=100,
            available_at=available_at or now,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    return scan_job_dto(job), True


def get_scan_job(db: Session, job_id: str) -> ImportScanJobDTO | None:
    row = db.get(ImportScanJob, job_id)
    return scan_job_dto(row) if row is not None else None


def list_scan_jobs(
    db: Session,
    *,
    monitor_folder_ids: tuple[str, ...] | None,
    status: str | None,
    limit: int = 20,
) -> list[ImportScanJobDTO]:
    statement = select(ImportScanJob)
    if monitor_folder_ids is not None:
        statement = statement.where(
            ImportScanJob.monitor_folder_id.in_(monitor_folder_ids)
        )
    if status:
        statement = statement.where(ImportScanJob.status == status)
    rows = db.scalars(
        statement.order_by(
            ImportScanJob.updated_at.desc(), ImportScanJob.id.desc()
        ).limit(limit)
    ).all()
    return [scan_job_dto(row) for row in rows]


def cancel_scan_job(db: Session, job_id: str) -> bool:
    job = db.get(ImportScanJob, job_id)
    if job is None:
        return False
    if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        return True
    now = db_timestamp()
    job.status = "CANCELLED"
    job.finished_at = now
    job.updated_at = now
    db.execute(delete(ImportWorkItem).where(ImportWorkItem.scan_job_id == job_id))
    db.flush()
    return True


def active_import_work_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ImportWorkItem)
            .where(ImportWorkItem.kind == "IMPORT_SOURCE")
        )
        or 0
    )


def source_already_known(db: Session, path: Path) -> bool:
    canonical = path.expanduser().resolve()
    key = source_key(canonical)
    task_exists = db.scalar(
        select(ImportTask.id)
        .where(
            (ImportTask.source_key == key)
            | (
                ImportTask.source_key.is_(None)
                & (ImportTask.source_path == str(canonical))
            )
        )
        .limit(1)
    )
    if task_exists is not None:
        return True
    return (
        db.scalar(
            select(LibraryFile.id)
            .where(
                (LibraryFile.path_key == key)
                | (
                    LibraryFile.path_key.is_(None)
                    & (LibraryFile.path == str(canonical))
                )
            )
            .limit(1)
        )
        is not None
    )


def claim_next_work_item(
    db: Session, *, worker_id: str, import_lease_seconds: int
) -> ImportWorkItemDTO | None:
    now = db_timestamp()
    claimable = or_(
        ImportWorkItem.status == "PENDING",
        and_(
            ImportWorkItem.status == "LEASED",
            ImportWorkItem.lease_expires_at.is_not(None),
            ImportWorkItem.lease_expires_at <= now,
        ),
    )
    row = db.scalar(
        select(ImportWorkItem)
        .where(ImportWorkItem.available_at <= now, claimable)
        .order_by(
            ImportWorkItem.priority.asc(),
            ImportWorkItem.created_at.asc(),
            ImportWorkItem.id.asc(),
        )
        .limit(1)
    )
    if row is None:
        return None
    lease_seconds = import_lease_seconds if row.kind == "IMPORT_SOURCE" else 60
    row.status = "LEASED"
    row.lease_owner = worker_id
    row.lease_expires_at = now + timedelta(seconds=lease_seconds)
    row.attempts += 1
    row.updated_at = now
    if row.scan_job_id is not None:
        job = db.get(ImportScanJob, row.scan_job_id)
        if job is not None:
            if job.status == "PENDING":
                job.status = "RUNNING"
                job.started_at = now
            job.heartbeat_at = now
            job.updated_at = now
    db.flush()
    return _work_dto(row)


def claim_import_task_for_work_item(
    db: Session,
    work_item: ImportWorkItemDTO,
    *,
    worker_id: str,
    lease_seconds: int,
) -> ImportTaskDTO | None:
    if work_item.import_task_id is None:
        return None
    now = db_timestamp()
    task = db.get(ImportTask, work_item.import_task_id)
    if task is None:
        complete_work_item(db, work_item.id)
        return None
    if task.status != "PENDING":
        if task.status in {"COMPLETED", "FAILED"}:
            complete_work_item(db, work_item.id)
        return None
    task.status = "PARSING"
    task.lease_owner = worker_id
    task.lease_expires_at = now + timedelta(seconds=lease_seconds)
    task.attempts += 1
    task.message = "正在准备导入"
    task.updated_at = now
    db.flush()
    return import_task_dto_from_row(
        {
            property_.columns[0].name: getattr(task, property_.key)
            for property_ in ImportTask.__mapper__.column_attrs
        }
    )


def release_scan_work_item(
    db: Session, work_item_id: str, *, reset_attempts: bool = True
) -> None:
    now = db_timestamp()
    values: dict[str, object] = {
        "status": "PENDING",
        "lease_owner": None,
        "lease_expires_at": None,
        "available_at": now,
        "updated_at": now,
    }
    if reset_attempts:
        values["attempts"] = 0
    db.execute(
        update(ImportWorkItem).where(ImportWorkItem.id == work_item_id).values(**values)
    )
    db.flush()


def complete_work_item(db: Session, work_item_id: str) -> None:
    db.execute(delete(ImportWorkItem).where(ImportWorkItem.id == work_item_id))
    db.flush()


def reconcile_existing_import_tasks(db: Session, *, limit: int = 2_000) -> int:
    tasks = db.scalars(
        select(ImportTask)
        .where(
            ImportTask.status.in_(("PENDING", "PARSING")),
            ~exists().where(ImportWorkItem.import_task_id == ImportTask.id),
        )
        .order_by(ImportTask.created_at.asc(), ImportTask.id.asc())
        .limit(limit)
    ).all()
    created = 0
    for task in tasks:
        if task.status == "PARSING":
            task.status = "PENDING"
            task.lease_owner = None
            task.lease_expires_at = None
        ensure_import_work_item(db, task)
        created += 1
    db.flush()
    return created


def backfill_source_keys(db: Session, *, limit: int = 500) -> int:
    """Backfill a restart-safe bounded page without delaying process startup."""

    task_rows = db.scalars(
        select(ImportTask)
        .where(ImportTask.source_key.is_(None))
        .order_by(ImportTask.created_at.asc(), ImportTask.id.asc())
        .limit(limit)
    ).all()
    remaining = max(0, limit - len(task_rows))
    file_rows = (
        db.scalars(
            select(LibraryFile)
            .where(LibraryFile.path_key.is_(None))
            .order_by(LibraryFile.id.asc())
            .limit(remaining)
        ).all()
        if remaining
        else []
    )
    for task in task_rows:
        task.source_key = source_key(task.source_path)
    for library_file in file_rows:
        library_file.path_key = source_key(library_file.path)
    db.flush()
    return len(task_rows) + len(file_rows)


def recover_scan_work_items(db: Session) -> int:
    now = db_timestamp()
    jobs = db.scalars(
        select(ImportScanJob).where(ImportScanJob.status == "RUNNING")
    ).all()
    for job in jobs:
        job.status = "PENDING"
        job.directories_scanned = 0
        job.files_scanned = 0
        job.candidates_found = 0
        job.queued_count = 0
        job.skipped_count = 0
        job.error_count = 0
        job.ignored_reason_counts = {}
        job.error_samples = []
        job.restart_count += 1
        job.started_at = None
        job.heartbeat_at = None
        job.updated_at = now
    db.execute(
        update(ImportWorkItem)
        .where(ImportWorkItem.kind == "SCAN_DIRECTORY")
        .values(
            status="PENDING",
            lease_owner=None,
            lease_expires_at=None,
            available_at=now,
            updated_at=now,
            attempts=0,
        )
    )
    db.flush()
    return len(jobs)


def clear_work_queue(db: Session) -> int:
    scan_jobs = db.scalars(
        select(ImportScanJob).where(ImportScanJob.status.in_(ACTIVE_SCAN_STATUSES))
    ).all()
    now = db_timestamp()
    for job in scan_jobs:
        job.status = "CANCELLED"
        job.finished_at = now
        job.updated_at = now
    result = db.execute(delete(ImportWorkItem))
    db.flush()
    return int(result.rowcount or 0)
