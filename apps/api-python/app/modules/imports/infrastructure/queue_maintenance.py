"""SQLAlchemy adapter for import-queue maintenance."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.import_pipeline import (
    ImportAsset,
    ImportLog,
    ImportTask,
)


class SqlAlchemyImportQueueMaintenanceStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def delete_all_tasks(self) -> int:
        self._db.execute(delete(ImportAsset))
        self._db.execute(delete(ImportLog))
        result = self._db.execute(delete(ImportTask))
        return int(result.rowcount or 0)
