"""SQL-only monitor-folder command adapter."""

from __future__ import annotations

from sqlalchemy import delete, func, insert, update
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.settings import MonitorFolder
from app.modules.imports.application.monitor_folder_commands import (
    PreparedMonitorFolderCreate,
    PreparedMonitorFolderDelete,
    PreparedMonitorFolderUpdate,
)
from app.services.system_events import write_prepared_system_events


class SqlAlchemyMonitorFolderWriteStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, prepared: PreparedMonitorFolderCreate) -> None:
        self._db.execute(insert(MonitorFolder.__table__).values(prepared.values))
        write_prepared_system_events(self._db, (prepared.event,))

    def update(self, prepared: PreparedMonitorFolderUpdate) -> None:
        self._db.execute(
            update(MonitorFolder)
            .where(MonitorFolder.id == prepared.folder_id)
            .values(**prepared.values)
        )
        write_prepared_system_events(self._db, (prepared.event,))

    def delete(self, prepared: PreparedMonitorFolderDelete) -> bool:
        result = self._db.execute(
            delete(MonitorFolder).where(MonitorFolder.id == prepared.folder_id)
        )
        deleted = bool(result.rowcount)
        if prepared.affected_user_ids:
            self._db.execute(
                update(User)
                .where(User.id.in_(prepared.affected_user_ids))
                .values(
                    authz_version=func.coalesce(User.authz_version, 1) + 1,
                    updated_at=prepared.updated_at,
                )
            )
        if deleted:
            write_prepared_system_events(self._db, (prepared.event,))
        return deleted
