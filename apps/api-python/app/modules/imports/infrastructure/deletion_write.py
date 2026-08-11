"""SQL-only persistence for an already prepared import-task deletion."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.import_pipeline import ImportTask
from app.modules.imports.application.deletion import PreparedImportDeletion
from app.services.system_events import write_prepared_system_events


class SqlAlchemyImportTaskDeletionStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def delete_task(self, prepared: PreparedImportDeletion) -> bool:
        result = self._db.execute(
            delete(ImportTask).where(ImportTask.id == prepared.task_id)
        )
        deleted = bool(result.rowcount)
        if deleted:
            write_prepared_system_events(self._db, prepared.events)
        return deleted
