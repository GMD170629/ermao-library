"""SQLAlchemy adapter for the public Shelf Book-membership capability."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.shelf.application.memberships import ShelfBookMembershipPort
from app.modules.shelf.infrastructure import shelves


class SqlAlchemyShelfBookMembership(ShelfBookMembershipPort):
    """Persist static-shelf Book links without owning the transaction."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def add_books(
        self,
        *,
        shelf_id: str,
        book_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        shelves.add_shelf_books(
            self._db,
            shelf_id=shelf_id,
            book_ids=book_ids,
            now=now,
        )

    def remove_books(
        self,
        *,
        shelf_id: str,
        book_ids: tuple[str, ...],
    ) -> None:
        shelves.remove_shelf_books(
            self._db,
            shelf_id=shelf_id,
            book_ids=book_ids,
        )


__all__ = ["SqlAlchemyShelfBookMembership"]
