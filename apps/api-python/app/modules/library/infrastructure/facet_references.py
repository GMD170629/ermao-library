"""ORM queries for stable, authorization-safe library facet references."""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from app.core.authorization import AuthorizationContext, work_visibility_predicate
from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.application.facet_references import (
    LibraryFacetReference,
    WorkFacetReferences,
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
        linked_work = aliased(LibraryWork)
        linked_facet = aliased(LibraryWorkFacet)
        has_visible_work = exists(
            select(linked_facet.work_id)
            .join(linked_work, linked_work.id == linked_facet.work_id)
            .where(
                linked_facet.facet_id == LibraryFacet.id,
                linked_work.hidden.is_(False),
                work_visibility_predicate(context, linked_work),
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

    def for_visible_work(self, work_id: str) -> WorkFacetReferences:
        rows = self._db.execute(
            select(LibraryFacet.id, LibraryFacet.kind, LibraryFacet.name)
            .join(LibraryWorkFacet, LibraryWorkFacet.facet_id == LibraryFacet.id)
            .where(
                LibraryWorkFacet.work_id == work_id,
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
        return WorkFacetReferences(
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
