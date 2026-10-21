"""SQL-only library command adapter."""

from __future__ import annotations

from sqlalchemy import func, insert, update
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.library import Library
from app.modules.imports.application.library_commands import (
    PreparedLibraryCreate,
    PreparedLibraryDelete,
    PreparedLibraryOrder,
    PreparedLibraryUpdate,
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
            .where(Library.id == prepared.library_id, Library.deletion_requested_at.is_(None))
            .values(**prepared.values)
        )
        write_prepared_system_events(self._db, (prepared.event,))

    def reorder(self, prepared: PreparedLibraryOrder) -> None:
        for index, library_id in enumerate(prepared.library_ids, start=1):
            self._db.execute(
                update(Library)
                .where(Library.id == library_id, Library.deletion_requested_at.is_(None))
                .values(sort_order=index, updated_at=prepared.updated_at)
            )
        write_prepared_system_events(self._db, (prepared.event,))

    def delete(self, prepared: PreparedLibraryDelete) -> bool:
        # The committed marker is also the durable cleanup queue entry. No
        # per-book work belongs in the foreground removal transaction.
        result = self._db.execute(
            update(Library)
            .where(
                Library.id == prepared.library_id,
                Library.deletion_requested_at.is_(None),
            )
            .values(
                deletion_requested_at=prepared.updated_at,
                enabled=False,
                updated_at=prepared.updated_at,
            )
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
