"""SQL-only library command adapter."""

from __future__ import annotations

from sqlalchemy import delete, func, insert, update
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.library import Library
from app.modules.imports.application.library_commands import (
    PreparedLibraryCreate,
    PreparedLibraryDelete,
    PreparedLibraryUpdate,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.services.system_events import write_prepared_system_events


class SqlAlchemyLibraryWriteStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, prepared: PreparedLibraryCreate) -> None:
        self._db.execute(insert(Library).values(prepared.values))
        write_prepared_system_events(self._db, (prepared.event,))

    def update(self, prepared: PreparedLibraryUpdate) -> None:
        self._db.execute(
            update(Library)
            .where(Library.id == prepared.library_id)
            .values(**prepared.values)
        )
        write_prepared_system_events(self._db, (prepared.event,))

    def cancel_import_tasks(self, library_id: str) -> int:
        result = self._db.execute(
            delete(LibraryImportTask).where(
                LibraryImportTask.library_id == library_id
            )
        )
        self._db.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    def delete(self, prepared: PreparedLibraryDelete) -> bool:
        result = self._db.execute(
            delete(Library).where(Library.id == prepared.library_id)
        )
        deleted = bool(getattr(result, "rowcount", 0))
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
