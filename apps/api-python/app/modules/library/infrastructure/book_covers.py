"""SQLAlchemy queries for Book-owned covers; resources never supply Book metadata."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import ColumnElement, and_, case, exists, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import (
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.library.application.book_covers import BookCoverCandidate


def _ready_cover(
    column_path: ColumnElement[str | None] | InstrumentedAttribute[str | None],
    column_status: ColumnElement[str] | InstrumentedAttribute[str],
) -> ColumnElement[bool]:
    return and_(
        column_path.is_not(None),
        func.trim(func.coalesce(column_path, "")) != "",
        column_status == "READY",
        ~column_path.endswith("default-book-cover-v1.png"),
    )


def effective_book_cover_exists(book_id: object) -> ColumnElement[bool]:
    """The existing filter contract now counts only the Book's own real cover."""
    return _ready_cover(
        LibraryBookMetadata.cover_path, LibraryBookMetadata.cover_status
    )


def effective_book_cover_path(
    book_id: ColumnElement[str] | InstrumentedAttribute[str],
    book_cover_path: ColumnElement[str | None] | InstrumentedAttribute[str | None],
    book_cover_status: ColumnElement[str] | InstrumentedAttribute[str],
) -> ColumnElement[str | None]:
    return case(
        (_ready_cover(book_cover_path, book_cover_status), book_cover_path), else_=None
    )


class SqlAlchemyBookCoverQueries:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_candidates(self, book_id: str) -> tuple[BookCoverCandidate, ...]:
        path = self.preferred_paths((book_id,)).get(book_id)
        return (
            (BookCoverCandidate(source="BOOK", source_id=book_id, stored_path=path),)
            if path
            else ()
        )

    def preferred_paths(self, book_ids: tuple[str, ...]) -> Mapping[str, str]:
        if not book_ids:
            return {}
        return {
            str(row.book_id): str(row.cover_path)
            for row in self._db.execute(
                select(
                    LibraryBookMetadata.book_id, LibraryBookMetadata.cover_path
                ).where(
                    LibraryBookMetadata.book_id.in_(book_ids),
                    _ready_cover(
                        LibraryBookMetadata.cover_path, LibraryBookMetadata.cover_status
                    ),
                )
            ).all()
        }


__all__ = [
    "SqlAlchemyBookCoverQueries",
    "effective_book_cover_exists",
    "effective_book_cover_path",
]


def first_readable_resource_id(
    db: Session, book_id: str, resource_ids: tuple[str, ...] | None = None
) -> str | None:
    """Select identity before inspecting its cover; missing artwork cannot skip it."""
    query = (
        select(LibraryReadableResource.id)
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryReadableResource.source_node_id,
        )
        .where(
            LibraryReadableResource.book_id == book_id,
            LibraryReadableResource.enablement_state == "ENABLED",
            LibraryReadableResource.import_state == "READY",
            exists(
                select(LibraryResourceAsset.id).where(
                    LibraryResourceAsset.resource_id == LibraryReadableResource.id,
                    LibraryResourceAsset.import_state == "READY",
                )
            ),
        )
        .order_by(
            func.lower(LibrarySourceNode.relative_path), LibraryReadableResource.id
        )
        .limit(1)
    )
    if resource_ids is not None:
        query = query.where(LibraryReadableResource.id.in_(resource_ids))
    return db.scalar(query)
