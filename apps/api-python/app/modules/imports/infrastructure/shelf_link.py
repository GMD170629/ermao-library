"""Set-based SQL adapter for watched-import shelf links."""

from __future__ import annotations

from sqlalchemy import literal, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.shelf import Shelf, ShelfWork
from app.modules.imports.application.shelf_link import PreparedImportShelfLink


class SqlAlchemyImportShelfLinkStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def write(self, prepared: PreparedImportShelfLink) -> None:
        table = ShelfWork.__table__
        link_source = select(
            literal(prepared.shelf_id),
            literal(prepared.work_id),
            literal(prepared.checkpoint_at),
        ).where(Shelf.id == prepared.shelf_id)
        self._db.execute(
            sqlite_insert(table)
            .from_select(
                [table.c.shelfId, table.c.workId, table.c.createdAt],
                link_source,
            )
            .prefix_with("OR IGNORE")
        )
        self._db.execute(
            update(Shelf)
            .where(Shelf.id == prepared.shelf_id)
            .values(updated_at=prepared.checkpoint_at)
        )
