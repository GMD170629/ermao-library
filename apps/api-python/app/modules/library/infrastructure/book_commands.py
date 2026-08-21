"""SQLAlchemy adapter for Book mutation use cases."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.modules.library.application.book_commands import BookMutationPort
from app.modules.library.infrastructure import books


class SqlAlchemyBookMutation(BookMutationPort):
    """Persist a Book update without owning the surrounding transaction."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def update_book(
        self, *, book_id: str, values: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        updated = books.update_book_fields(self._db, book_id, dict(values))
        return dict(updated) if updated is not None else None


__all__ = ["SqlAlchemyBookMutation"]
