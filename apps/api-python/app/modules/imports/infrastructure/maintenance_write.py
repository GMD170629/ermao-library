"""SQL-only adapter for prepared import maintenance commands."""

from __future__ import annotations

from sqlalchemy import delete, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.import_pipeline import (
    BookConversionTask,
    ImportAsset,
    ImportTask,
    ImportWorkItem,
)
from app.modules.imports.application.maintenance_commands import (
    PreparedImportRetry,
    PreparedTerminalImportClear,
)
from app.services.system_events import write_prepared_system_events


class SqlAlchemyImportMaintenanceWriteStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def clear_terminal(self, prepared: PreparedTerminalImportClear) -> int:
        deleted = 0
        for task_ids in sqlite_parameter_chunks(
            prepared.task_ids,
            parameters_per_row=1,
        ):
            ids = tuple(task_ids)
            self._db.execute(
                delete(BookConversionTask).where(
                    BookConversionTask.import_task_id.in_(ids)
                )
            )
            result = self._db.execute(
                delete(ImportTask).where(ImportTask.id.in_(ids))
            )
            deleted += int(result.rowcount or 0)
        write_prepared_system_events(self._db, prepared.events)
        return deleted

    def retry(self, prepared: PreparedImportRetry) -> None:
        self._db.execute(
            update(ImportTask)
            .where(ImportTask.id == prepared.task_id)
            .values(
                status="PENDING",
                progress=0,
                processed_asset_count=0,
                message="已重新加入后台队列",
                error_code=None,
                error_summary=None,
                retryable=False,
                started_at=None,
                finished_at=None,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=prepared.updated_at,
            )
        )
        self._db.execute(
            update(ImportAsset)
            .where(ImportAsset.import_task_id == prepared.task_id)
            .values(
                status="PENDING",
                file_id=None,
                error_code=None,
                error_summary=None,
                updated_at=prepared.updated_at,
            )
        )
        self._db.execute(
            update(BookConversionTask)
            .where(BookConversionTask.import_task_id == prepared.task_id)
            .values(
                status="QUEUED",
                progress=0,
                retryable=False,
                error_code=None,
                error_summary=None,
                started_at=None,
                finished_at=None,
                updated_at=prepared.updated_at,
            )
        )
        work = prepared.work_row
        self._db.execute(
            sqlite_insert(ImportWorkItem.__table__)
            .values(work)
            .on_conflict_do_update(
                index_elements=[ImportWorkItem.dedupe_key],
                set_={
                    "status": "PENDING",
                    "leaseOwner": None,
                    "leaseExpiresAt": None,
                    "availableAt": prepared.updated_at,
                    "attempts": 0,
                    "updatedAt": prepared.updated_at,
                },
            )
        )
        write_prepared_system_events(self._db, (prepared.event,))
