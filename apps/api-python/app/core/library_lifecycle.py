"""Database predicates for the immediate library-removal boundary."""

from sqlalchemy import ColumnElement, exists, select, update
from sqlalchemy.orm import Session

from app.models.library import Library
from app.modules.library.infrastructure.readable_resource_schema import LibraryBook


def active_library(library_id: ColumnElement[str]) -> ColumnElement[bool]:
    # An independent alias also works when the outer query selects Library.
    live = Library.__table__.alias("live_library")
    return exists(select(live.c.id).where(
        live.c.id == library_id, live.c.deletionRequestedAt.is_(None),
    ))


def active_book(book_id: ColumnElement[str]) -> ColumnElement[bool]:
    book = LibraryBook.__table__.alias("live_book")
    return exists(select(book.c.id).where(
        book.c.id == book_id, active_library(book.c.libraryId),
    ))


def library_is_active(db: Session, library_id: str) -> bool:
    return db.scalar(select(Library.id).where(
        Library.id == library_id, Library.deletion_requested_at.is_(None),
    )) is not None


def lock_active_library(db: Session, library_id: str) -> bool:
    """Fence new work with the same writer lock used to commit removal."""
    result = db.execute(update(Library).where(
        Library.id == library_id, Library.deletion_requested_at.is_(None),
    ).values(enabled=Library.enabled, updated_at=Library.updated_at))
    return bool(result.rowcount)
