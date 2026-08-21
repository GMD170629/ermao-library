"""ORM queries for stable, authorization-safe library facet references."""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from app.core.authorization import AuthorizationContext, book_visibility_predicate
from app.models import LibraryFacet, LibraryBook, LibraryBookFacet
from app.modules.library.application.facet_references import (
    LibraryFacetReference,
    BookFacetReferences,
)


class SqlAlchemyLibraryFacetReferenceQueries:
    def __init__(self, db: Session) -> None:
        self._db = db

    def visible_facet(
        self,
        *,
        context: AuthorizationContext,
        kind: str,
        facet_id: str,
    ) -> LibraryFacetReference | None:
        linked_work = aliased(LibraryBook)
        linked_facet = aliased(LibraryBookFacet)
        has_visible_work = exists(
            select(linked_facet.book_id)
            .join(linked_work, linked_work.id == linked_facet.book_id)
            .where(
                linked_facet.facet_id == LibraryFacet.id,
                linked_work.hidden.is_(False),
                book_visibility_predicate(context, linked_work),
            )
        )
        row = self._db.execute(
            select(LibraryFacet.id, LibraryFacet.kind, LibraryFacet.name).where(
                LibraryFacet.id == facet_id,
                LibraryFacet.kind == kind,
                has_visible_work,
            )
        ).one_or_none()
        return (
            self._reference(row.id, row.kind, row.name) if row is not None else None
        )

    def for_visible_work(self, book_id: str) -> BookFacetReferences:
        rows = self._db.execute(
            select(LibraryFacet.id, LibraryFacet.kind, LibraryFacet.name)
            .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
            .where(
                LibraryBookFacet.book_id == book_id,
                LibraryFacet.kind.in_(("AUTHOR", "SERIES")),
            )
            .order_by(
                LibraryFacet.kind.asc(),
                LibraryFacet.normalized_name.asc(),
                LibraryFacet.id.asc(),
            )
        ).all()
        references = tuple(
            self._reference(row.id, row.kind, row.name) for row in rows
        )
        return BookFacetReferences(
            series=next((item for item in references if item.kind == "SERIES"), None),
            authors=tuple(item for item in references if item.kind == "AUTHOR"),
        )

    @staticmethod
    def _reference(
        id_value: object,
        kind_value: object,
        name_value: object,
    ) -> LibraryFacetReference:
        return LibraryFacetReference(
            id=str(id_value),
            kind=str(kind_value),
            name=str(name_value),
        )
