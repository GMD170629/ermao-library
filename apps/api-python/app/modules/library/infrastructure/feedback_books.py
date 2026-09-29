"""Bounded public book labels for an explicitly selected diagnostic event."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBookMetadata,
)


def feedback_book_titles(db: Session, book_ids: frozenset[str]) -> dict[str, str]:
    if not book_ids:
        return {}
    rows = db.execute(
        select(LibraryBookMetadata.book_id, LibraryBookMetadata.title)
        .where(LibraryBookMetadata.book_id.in_(sorted(book_ids)[:20]))
    ).all()
    return {str(book_id): str(title) for book_id, title in rows}
