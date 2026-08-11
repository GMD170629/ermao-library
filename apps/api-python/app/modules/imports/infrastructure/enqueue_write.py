"""Two-phase set-based persistence for import enqueue hand-offs."""

from __future__ import annotations

from datetime import datetime
from time import time_ns
from uuid import uuid4

from sqlalchemy import Integer, cast, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.core.time import now_timestamp_ms
from app.models.import_pipeline import ImportAsset, ImportTask, ImportWorkItem
from app.models.settings import MonitorFolder
from app.modules.imports.application.dto import StageImportCommand
from app.modules.imports.application.enqueue import (
    ImportEnqueueProjection,
    PreparedImportEnqueue,
)
from app.modules.imports.infrastructure.source_keys import source_key
from app.modules.imports.infrastructure.task_mapper import import_task_dto_from_row
from app.modules.imports.infrastructure.tasks import build_import_task_values


def load_import_enqueue_projection(
    db: Session,
    *,
    canonical_source_path: str,
    monitor_folder_id: str | None,
    allow_terminal_requeue: bool,
) -> ImportEnqueueProjection:
    statuses = (
        ("PENDING", "PARSING")
        if allow_terminal_requeue
        else ("PENDING", "PARSING", "COMPLETED", "FAILED")
    )
    key = source_key(canonical_source_path)
    task_row = (
        db.execute(
            select(ImportTask.__table__)
            .where(
                (ImportTask.source_key == key)
                | (
                    ImportTask.source_key.is_(None)
                    & (ImportTask.source_path == canonical_source_path)
                ),
                ImportTask.status.in_(statuses),
            )
            .order_by(cast(ImportTask.created_at, Integer).desc(), ImportTask.id.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    work_row = None
    if task_row is not None:
        work_row = (
            db.execute(
                select(ImportWorkItem.__table__)
                .where(ImportWorkItem.import_task_id == str(task_row["id"]))
                .limit(1)
            )
            .mappings()
            .first()
        )
    policy = None
    if monitor_folder_id is not None:
        policy = db.scalar(
            select(MonitorFolder.media_kind_policy).where(
                MonitorFolder.id == monitor_folder_id
            )
        )
    return ImportEnqueueProjection(
        existing_task=dict(task_row) if task_row is not None else None,
        existing_work=dict(work_row) if work_row is not None else None,
        media_kind_policy=str(policy or "MIXED"),
    )


def prepare_import_enqueue(
    command: StageImportCommand,
    projection: ImportEnqueueProjection,
    *,
    available_at: datetime,
) -> PreparedImportEnqueue:
    """Resolve paths, bundle assets, identifiers and rows without a Session."""

    canonical_source = command.source_path.expanduser().resolve()
    existing_task = projection.existing_task
    if existing_task is not None:
        task = import_task_dto_from_row(existing_task)
        existing_work = projection.existing_work
        should_enqueue = task.status == "PENDING"
        work_row = None
        refresh_work_id = None
        if should_enqueue and existing_work is None:
            key = source_key(canonical_source)
            timestamp = available_at
            work_row = {
                "id": f"work_{uuid4().hex}",
                "kind": "IMPORT_SOURCE",
                "scanJobId": None,
                "importTaskId": task.id,
                "dedupeKey": f"import:{key}:{task.id}",
                "status": "PENDING",
                "priority": 10,
                "availableAt": timestamp,
                "attempts": 0,
                "createdAt": timestamp,
                "updatedAt": timestamp,
            }
        elif should_enqueue and str(existing_work.get("status") or "") == "PENDING":
            refresh_work_id = str(existing_work["id"])
        return PreparedImportEnqueue(
            task=task,
            created=False,
            task_row=None,
            asset_rows=(),
            work_row=work_row,
            refresh_work_id=refresh_work_id,
            available_at=available_at,
        )

    now_ms = now_timestamp_ms()
    task_id = f"py_{time_ns()}"
    task_values, bundle_files = build_import_task_values(
        task_id=task_id,
        source=canonical_source,
        origin=command.origin,
        original_name=command.original_name,
        requested_title=command.requested_title,
        requested_author=command.requested_author,
        monitor_folder_id=command.monitor_folder_id,
        media_kind_policy=command.media_kind_policy
        or projection.media_kind_policy,
        message=command.message,
        now=now_ms,
    )
    asset_seed = time_ns()
    asset_rows = tuple(
        {
            "id": f"py_{asset_seed + index}",
            "importTaskId": task_id,
            "sourcePath": str(asset_path),
            "status": "PENDING",
            "sortOrder": index,
            "createdAt": now_ms,
            "updatedAt": now_ms,
        }
        for index, asset_path in enumerate(bundle_files)
    )
    key = source_key(canonical_source)
    work_row = {
        "id": f"work_{uuid4().hex}",
        "kind": "IMPORT_SOURCE",
        "scanJobId": None,
        "importTaskId": task_id,
        "dedupeKey": f"import:{key}:{task_id}",
        "status": "PENDING",
        "priority": 10,
        "availableAt": available_at,
        "attempts": 0,
        "createdAt": available_at,
        "updatedAt": available_at,
    }
    return PreparedImportEnqueue(
        task=import_task_dto_from_row(task_values),
        created=True,
        task_row=task_values,
        asset_rows=asset_rows,
        work_row=work_row,
        refresh_work_id=None,
        available_at=available_at,
    )


def execute_prepared_import_enqueue(
    db: Session,
    prepared: PreparedImportEnqueue,
) -> None:
    """Execute only typed set-based DML in the caller-owned transaction."""

    if prepared.task_row is not None:
        db.execute(insert(ImportTask.__table__), [dict(prepared.task_row)])
    for chunk in sqlite_parameter_chunks(prepared.asset_rows, parameters_per_row=7):
        db.execute(insert(ImportAsset.__table__), [dict(row) for row in chunk])
    if prepared.work_row is not None:
        db.execute(
            sqlite_insert(ImportWorkItem.__table__)
            .values(dict(prepared.work_row))
            .on_conflict_do_nothing(index_elements=[ImportWorkItem.dedupe_key])
        )
    if prepared.refresh_work_id is not None:
        db.execute(
            update(ImportWorkItem)
            .where(ImportWorkItem.id == prepared.refresh_work_id)
            .values(
                available_at=prepared.available_at,
                updated_at=prepared.available_at,
            )
        )


class SqlAlchemyPreparedImportEnqueueStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def write(self, prepared: PreparedImportEnqueue) -> None:
        execute_prepared_import_enqueue(self._db, prepared)
