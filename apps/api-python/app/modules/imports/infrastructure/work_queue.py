"""ORM adapter for the single persistent import work queue."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

from sqlalchemy import (
    and_,
    bindparam,
    case,
    delete,
    exists,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.common import db_timestamp
from app.models.import_pipeline import ImportScanJob, ImportTask, ImportWorkItem
from app.models.library import LibraryFile
from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.imports.application.scan_jobs import PreparedImportScanJob
from app.modules.imports.application.work_queue_dto import (
    ImportQueueMaintenanceProjection,
    ImportScanJobDTO,
    ImportScanStatus,
    ImportWorkItemDTO,
    ImportWorkKind,
    ImportWorkStatus,
    PreparedImportQueueMaintenance,
    ScanErrorDTO,
)
from app.modules.imports.infrastructure.source_keys import source_key
from app.modules.imports.infrastructure.task_mapper import import_task_dto_from_row

ACTIVE_SCAN_STATUSES = ("PENDING", "RUNNING")
IMPORT_WORK_HIGH_WATERMARK = 2_000


def insert_prepared_scan_jobs(
    db: Session,
    scan_jobs: tuple[PreparedImportScanJob, ...],
) -> int:
    """Insert all missing scan/work row pairs with bounded set-based SQL."""

    if not scan_jobs:
        return 0
    unique_requests = {request.dedupe_key: request for request in scan_jobs}
    existing_keys: set[str] = set()
    dedupe_keys = tuple(unique_requests)
    for chunk in sqlite_parameter_chunks(dedupe_keys, parameters_per_row=1):
        existing_keys.update(
            db.scalars(
                select(ImportWorkItem.dedupe_key).where(
                    ImportWorkItem.dedupe_key.in_(tuple(chunk))
                )
            ).all()
        )
    missing = tuple(
        request for key, request in unique_requests.items() if key not in existing_keys
    )
    job_rows = [
        {
            "id": request.job_id,
            "monitorFolderId": request.monitor_folder_id,
            "actorUserId": request.actor_user_id,
            "rootPath": request.root_path,
            "trigger": request.trigger,
            "status": "PENDING",
            "directoriesScanned": 0,
            "filesScanned": 0,
            "candidatesFound": 0,
            "queuedCount": 0,
            "skippedCount": 0,
            "errorCount": 0,
            "ignoredReasonCounts": {},
            "errorSamples": [],
            "restartCount": 0,
            "createdAt": request.created_at,
            "updatedAt": request.created_at,
        }
        for request in missing
    ]
    work_rows = [
        {
            "id": request.work_item_id,
            "kind": "SCAN_DIRECTORY",
            "scanJobId": request.job_id,
            "importTaskId": None,
            "dedupeKey": request.dedupe_key,
            "status": "PENDING",
            "priority": 100,
            "availableAt": request.available_at,
            "attempts": 0,
            "createdAt": request.created_at,
            "updatedAt": request.created_at,
        }
        for request in missing
    ]
    for chunk in sqlite_parameter_chunks(job_rows, parameters_per_row=17):
        db.execute(insert(ImportScanJob.__table__), list(chunk))
    for chunk in sqlite_parameter_chunks(work_rows, parameters_per_row=11):
        db.execute(insert(ImportWorkItem.__table__), list(chunk))
    return len(missing)


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


def list_scan_jobs_for_prepared_requests(
    db: Session,
    requests: tuple[PreparedImportScanJob, ...],
) -> list[ImportScanJobDTO]:
    """Resolve prepared request dedupe keys to persisted jobs in one projection."""

    if not requests:
        return []
    dedupe_order = {request.dedupe_key: index for index, request in enumerate(requests)}
    rows = db.execute(
        select(ImportWorkItem.dedupe_key, ImportScanJob)
        .join(ImportScanJob, ImportScanJob.id == ImportWorkItem.scan_job_id)
        .where(ImportWorkItem.dedupe_key.in_(tuple(dedupe_order)))
    ).all()
    rows.sort(key=lambda row: dedupe_order[str(row[0])])
    return [scan_job_dto(row[1]) for row in rows]


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
    if existing is not None:
        if existing.status == "PENDING":
            refreshed_available_at = available_at or now
            db.execute(
                update(ImportWorkItem)
                .where(ImportWorkItem.id == existing.id)
                .values(
                    available_at=refreshed_available_at,
                    updated_at=now,
                )
            )
            existing.available_at = refreshed_available_at
            existing.updated_at = now
        return existing
    if task.source_key != key:
        db.execute(
            update(ImportTask).where(ImportTask.id == task.id).values(source_key=key)
        )
        task.source_key = key
    work_id = f"work_{uuid4().hex}"
    work_available_at = available_at or now
    work = ImportWorkItem(
        id=work_id,
        kind="IMPORT_SOURCE",
        import_task_id=task.id,
        scan_job_id=None,
        dedupe_key=f"import:{key}:{task.id}",
        status="PENDING",
        priority=priority,
        available_at=work_available_at,
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    inserted = db.scalar(
        sqlite_insert(ImportWorkItem)
        .values(
            id=work_id,
            kind="IMPORT_SOURCE",
            import_task_id=task.id,
            scan_job_id=None,
            dedupe_key=f"import:{key}:{task.id}",
            status="PENDING",
            priority=priority,
            available_at=work_available_at,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        .returning(ImportWorkItem)
    )
    return inserted or work


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
    job_id = f"scan_{uuid4().hex}"
    work_id = f"work_{uuid4().hex}"
    job = ImportScanJob(
        id=job_id,
        monitor_folder_id=monitor_folder_id,
        actor_user_id=actor_user_id,
        root_path=str(canonical),
        trigger=trigger,
        status="PENDING",
        directories_scanned=0,
        files_scanned=0,
        candidates_found=0,
        queued_count=0,
        skipped_count=0,
        error_count=0,
        ignored_reason_counts={},
        error_samples=[],
        restart_count=0,
        created_at=now,
        updated_at=now,
    )
    db.execute(
        insert(ImportScanJob.__table__).values(
            id=job_id,
            monitorFolderId=monitor_folder_id,
            actorUserId=actor_user_id,
            rootPath=str(canonical),
            trigger=trigger,
            status="PENDING",
            directoriesScanned=0,
            filesScanned=0,
            candidatesFound=0,
            queuedCount=0,
            skippedCount=0,
            errorCount=0,
            ignoredReasonCounts={},
            errorSamples=[],
            restartCount=0,
            createdAt=now,
            updatedAt=now,
        )
    )
    db.execute(
        insert(ImportWorkItem.__table__).values(
            id=work_id,
            kind="SCAN_DIRECTORY",
            scanJobId=job_id,
            importTaskId=None,
            dedupeKey=dedupe_key,
            status="PENDING",
            priority=100,
            availableAt=available_at or now,
            attempts=0,
            createdAt=now,
            updatedAt=now,
        )
    )
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
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    attempts = row.attempts + 1
    claimed = db.execute(
        update(ImportWorkItem)
        .where(ImportWorkItem.id == row.id, claimable)
        .values(
            status="LEASED",
            lease_owner=worker_id,
            lease_expires_at=lease_expires_at,
            attempts=ImportWorkItem.attempts + 1,
            updated_at=now,
        )
    )
    if not claimed.rowcount:
        return None
    if row.scan_job_id is not None:
        db.execute(
            update(ImportScanJob)
            .where(ImportScanJob.id == row.scan_job_id)
            .values(
                status=case(
                    (ImportScanJob.status == "PENDING", "RUNNING"),
                    else_=ImportScanJob.status,
                ),
                started_at=case(
                    (ImportScanJob.status == "PENDING", now),
                    else_=ImportScanJob.started_at,
                ),
                heartbeat_at=now,
                updated_at=now,
            )
        )
    return ImportWorkItemDTO(
        id=row.id,
        kind=cast(ImportWorkKind, row.kind),
        scan_job_id=row.scan_job_id,
        import_task_id=row.import_task_id,
        status="LEASED",
        attempts=attempts,
    )


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
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    task_values = {
        property_.columns[0].name: getattr(task, property_.key)
        for property_ in ImportTask.__mapper__.column_attrs
    }
    task_values.update(
        {
            "status": "PARSING",
            "leaseOwner": worker_id,
            "leaseExpiresAt": lease_expires_at,
            "attempts": task.attempts + 1,
            "message": "正在准备导入",
            "updatedAt": now,
        }
    )
    claimed = db.execute(
        update(ImportTask)
        .where(ImportTask.id == task.id, ImportTask.status == "PENDING")
        .values(
            status="PARSING",
            lease_owner=worker_id,
            lease_expires_at=lease_expires_at,
            attempts=ImportTask.attempts + 1,
            message="正在准备导入",
            updated_at=now,
        )
    )
    if not claimed.rowcount:
        return None
    return import_task_dto_from_row(task_values)


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


def complete_work_item(db: Session, work_item_id: str) -> None:
    db.execute(delete(ImportWorkItem).where(ImportWorkItem.id == work_item_id))


def load_import_queue_maintenance_projection(
    db: Session,
    *,
    reconcile_limit: int = 2_000,
    source_key_limit: int = 500,
) -> ImportQueueMaintenanceProjection:
    task_rows = tuple(
        db.execute(
            select(
                ImportTask.id,
                ImportTask.source_key,
                ImportTask.source_path,
                ImportTask.status,
            )
            .where(
                ImportTask.status.in_(("PENDING", "PARSING")),
                ~exists().where(ImportWorkItem.import_task_id == ImportTask.id),
            )
            .order_by(ImportTask.created_at.asc(), ImportTask.id.asc())
            .limit(reconcile_limit)
        ).all()
    )
    missing_task_keys = tuple(
        db.execute(
            select(
                ImportTask.id,
                ImportTask.source_key,
                ImportTask.source_path,
                ImportTask.status,
            )
            .where(ImportTask.source_key.is_(None))
            .order_by(ImportTask.created_at.asc(), ImportTask.id.asc())
            .limit(source_key_limit)
        ).all()
    )
    task_rows_by_id = {str(row[0]): row for row in (*task_rows, *missing_task_keys)}
    remaining = max(0, source_key_limit - len(missing_task_keys))
    file_rows = (
        tuple(
            db.execute(
                select(LibraryFile.id, LibraryFile.path)
                .where(LibraryFile.path_key.is_(None))
                .order_by(LibraryFile.id.asc())
                .limit(remaining)
            ).all()
        )
        if remaining
        else ()
    )
    return ImportQueueMaintenanceProjection(
        task_rows=tuple(task_rows_by_id.values()),
        file_rows=file_rows,
    )


def prepare_import_queue_maintenance(
    projection: ImportQueueMaintenanceProjection,
    *,
    now: datetime,
) -> PreparedImportQueueMaintenance:
    task_updates: list[dict[str, object]] = []
    work_values: list[dict[str, object]] = []
    for task_id, stored_key, source_path, status in projection.task_rows:
        key = stored_key or source_key(source_path)
        task_updates.append(
            {
                "_target_id": task_id,
                "_source_key": key,
                "_status": "PENDING" if status == "PARSING" else status,
            }
        )
        if status in {"PENDING", "PARSING"}:
            work_values.append(
                {
                    "id": f"work_{uuid4().hex}",
                    "kind": "IMPORT_SOURCE",
                    "scanJobId": None,
                    "importTaskId": task_id,
                    "dedupeKey": f"import:{key}:{task_id}",
                    "status": "PENDING",
                    "priority": 10,
                    "availableAt": now,
                    "attempts": 0,
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
    file_updates = tuple(
        {"_target_id": file_id, "_path_key": source_key(path)}
        for file_id, path in projection.file_rows
    )
    return PreparedImportQueueMaintenance(
        task_updates=tuple(task_updates),
        work_rows=tuple(work_values),
        file_updates=file_updates,
    )


def write_prepared_import_queue_maintenance(
    db: Session,
    prepared: PreparedImportQueueMaintenance,
) -> int:
    task_table = ImportTask.__table__
    if prepared.task_updates:
        db.execute(
            task_table.update()
            .where(task_table.c.id == bindparam("_target_id"))
            .values(
                {
                    task_table.c["sourceKey"]: bindparam("_source_key"),
                    task_table.c.status: bindparam("_status"),
                    task_table.c["leaseOwner"]: None,
                    task_table.c["leaseExpiresAt"]: None,
                }
            ),
            list(prepared.task_updates),
        )
    for chunk in sqlite_parameter_chunks(prepared.work_rows, parameters_per_row=11):
        db.execute(
            sqlite_insert(ImportWorkItem.__table__)
            .values(list(chunk))
            .on_conflict_do_nothing(index_elements=[ImportWorkItem.dedupe_key])
        )
    file_table = LibraryFile.__table__
    if prepared.file_updates:
        db.execute(
            file_table.update()
            .where(file_table.c.id == bindparam("_target_id"))
            .values({file_table.c["pathKey"]: bindparam("_path_key")}),
            list(prepared.file_updates),
        )
    return prepared.changed_count


def recover_scan_work_items(db: Session) -> int:
    now = db_timestamp()
    running_filter = ImportScanJob.status == "RUNNING"
    running_count = db.scalar(
        select(func.count()).select_from(ImportScanJob).where(running_filter)
    )
    db.execute(
        update(ImportScanJob)
        .where(running_filter)
        .values(
            status="PENDING",
            directories_scanned=0,
            files_scanned=0,
            candidates_found=0,
            queued_count=0,
            skipped_count=0,
            error_count=0,
            ignored_reason_counts={},
            error_samples=[],
            restart_count=ImportScanJob.restart_count + 1,
            started_at=None,
            heartbeat_at=None,
            updated_at=now,
        )
    )
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
    return int(running_count or 0)


def clear_work_queue(db: Session) -> int:
    now = db_timestamp()
    db.execute(
        update(ImportScanJob)
        .where(ImportScanJob.status.in_(ACTIVE_SCAN_STATUSES))
        .values(status="CANCELLED", finished_at=now, updated_at=now)
    )
    result = db.execute(delete(ImportWorkItem))
    return int(result.rowcount or 0)
