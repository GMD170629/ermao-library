"""SQLAlchemy queries for effective Book cover fallback resolution."""

from __future__ import annotations

from collections.abc import Collection, Mapping

from sqlalchemy import ColumnElement, and_, case, exists, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased

from app.models import (
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
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
    )


def _nonblank_cover(
    column_path: ColumnElement[str | None] | InstrumentedAttribute[str | None],
) -> ColumnElement[bool]:
    return and_(
        column_path.is_not(None),
        func.trim(func.coalesce(column_path, "")) != "",
    )


def effective_book_cover_exists(book_id: object) -> ColumnElement[bool]:
    """Return a correlated predicate for a READY Book or readable Resource cover."""

    book_cover = _ready_cover(
        LibraryBookMetadata.cover_path,
        LibraryBookMetadata.cover_status,
    )
    resource_cover = exists(
        select(LibraryReadableResource.id)
        .join(
            LibraryReadableResourceMetadata,
            LibraryReadableResourceMetadata.resource_id == LibraryReadableResource.id,
        )
        .where(
            LibraryReadableResource.book_id == book_id,
            LibraryReadableResource.enablement_state == "ENABLED",
            LibraryReadableResource.import_state == "READY",
            _ready_cover(
                LibraryReadableResourceMetadata.cover_path,
                LibraryReadableResourceMetadata.cover_status,
            ),
        )
    )
    return or_(book_cover, resource_cover)


def effective_book_cover_path(
    book_id: ColumnElement[str] | InstrumentedAttribute[str],
    book_cover_path: ColumnElement[str | None] | InstrumentedAttribute[str | None],
    book_cover_status: ColumnElement[str] | InstrumentedAttribute[str],
) -> ColumnElement[str | None]:
    """Return the preferred READY cover path as a correlated SQL expression."""

    resource = aliased(LibraryReadableResource)
    metadata = aliased(LibraryReadableResourceMetadata)
    source_node = aliased(LibrarySourceNode)
    resource_cover = (
        select(metadata.cover_path)
        .join(resource, resource.id == metadata.resource_id)
        .join(source_node, source_node.id == resource.source_node_id)
        .where(
            resource.book_id == book_id,
            resource.enablement_state == "ENABLED",
            resource.import_state == "READY",
            _ready_cover(metadata.cover_path, metadata.cover_status),
        )
        .order_by(
            func.lower(source_node.relative_path).asc(),
            resource.id.asc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    return case(
        (_ready_cover(book_cover_path, book_cover_status), book_cover_path),
        else_=resource_cover,
    )


class SqlAlchemyBookCoverQueries:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_candidates(self, book_id: str) -> tuple[BookCoverCandidate, ...]:
        candidates: list[BookCoverCandidate] = []
        book_path = self._db.scalar(
            select(LibraryBookMetadata.cover_path).where(
                LibraryBookMetadata.book_id == book_id,
                _nonblank_cover(LibraryBookMetadata.cover_path),
            )
        )
        if book_path:
            candidates.append(
                BookCoverCandidate(
                    source="BOOK",
                    source_id=book_id,
                    stored_path=str(book_path),
                )
            )

        rows = self._resource_cover_rows((book_id,))
        candidates.extend(
            BookCoverCandidate(
                source="RESOURCE",
                source_id=resource_id,
                stored_path=cover_path,
            )
            for _book_id, resource_id, cover_path in rows
        )
        return tuple(candidates)

    def preferred_paths(self, book_ids: tuple[str, ...]) -> Mapping[str, str]:
        if not book_ids:
            return {}
        paths = {
            str(row.book_id): str(row.cover_path)
            for row in self._db.execute(
                select(
                    LibraryBookMetadata.book_id,
                    LibraryBookMetadata.cover_path,
                ).where(
                    LibraryBookMetadata.book_id.in_(book_ids),
                    _ready_cover(
                        LibraryBookMetadata.cover_path,
                        LibraryBookMetadata.cover_status,
                    ),
                )
            ).all()
        }
        for book_id, _resource_id, cover_path in self._resource_cover_rows(book_ids):
            paths.setdefault(book_id, cover_path)
        return paths

    def _resource_cover_rows(
        self, book_ids: Collection[str]
    ) -> list[tuple[str, str, str]]:
        if not book_ids:
            return []
        rows = self._db.execute(
            select(
                LibraryReadableResource.book_id,
                LibraryReadableResource.id.label("resource_id"),
                LibraryReadableResourceMetadata.cover_path,
            )
            .join(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryReadableResource.source_node_id,
            )
            .where(
                LibraryReadableResource.book_id.in_(book_ids),
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
                _ready_cover(
                    LibraryReadableResourceMetadata.cover_path,
                    LibraryReadableResourceMetadata.cover_status,
                ),
            )
            .order_by(
                LibraryReadableResource.book_id.asc(),
                func.lower(LibrarySourceNode.relative_path).asc(),
                LibraryReadableResource.id.asc(),
            )
        ).all()
        return [
            (str(row.book_id), str(row.resource_id), str(row.cover_path))
            for row in rows
        ]


__all__ = [
    "SqlAlchemyBookCoverQueries",
    "effective_book_cover_exists",
    "effective_book_cover_path",
]
