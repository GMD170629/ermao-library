"""Bounded ORM queries for library filter schema and suggestions."""

from __future__ import annotations

from typing import cast

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.authorization import (
    AuthorizationContext,
    book_visibility_predicate,
    library_visibility_predicate,
    resource_visibility_predicate,
)
from app.models import (
    Library,
    LibraryBook,
    LibraryBookFacet,
    LibraryFacet,
    LibraryReadableResource,
)
from app.models.shelf import Shelf
from app.modules.library.application.filter_options import (
    LibraryFilterOption,
    LibraryFilterOptionPage,
    LibraryFilterOptionSource,
    LibraryFilterSchemaOptions,
    LibraryNavigationSource,
)


class SqlAlchemyLibraryFilterQueries:
    """Apply authorization while aggregating bounded filter values in SQLite."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def schema_options(
        self, context: AuthorizationContext
    ) -> LibraryFilterSchemaOptions:
        formats, statuses = self._resource_options(context)
        return LibraryFilterSchemaOptions(
            formats=formats,
            import_statuses=statuses,
            origins=(),
            libraries=self._library_options(context),
            shelves=self._shelf_options(context),
        )

    def navigation_sources(
        self, context: AuthorizationContext
    ) -> tuple[LibraryNavigationSource, ...]:
        rows = self._db.execute(
            select(Library.id, Library.name)
            .where(library_visibility_predicate(context, cast(ColumnElement[str], Library.id)))
            .order_by(Library.sort_order.asc(), Library.created_at.desc(), Library.id.desc())
        )
        return tuple(LibraryNavigationSource(row.id, row.name) for row in rows)

    def search_options(
        self,
        context: AuthorizationContext,
        *,
        source: LibraryFilterOptionSource,
        query: str,
        limit: int,
    ) -> LibraryFilterOptionPage:
        kind = {"authors": "AUTHOR", "tags": "TAG", "series": "SERIES"}[source]
        options, has_more = self._facet_options(context, kind, query, limit)
        return LibraryFilterOptionPage(
            source=source,
            query=query,
            options=options,
            has_more=has_more,
            index_ready=True,
        )

    def _resource_options(
        self, context: AuthorizationContext,
    ) -> tuple[tuple[LibraryFilterOption, ...], tuple[LibraryFilterOption, ...]]:
        # Both selectors describe the same authorized readable resources.
        # Aggregate their compact index once instead of fetching resource rows.
        source_format = func.trim(func.coalesce(LibraryReadableResource.format, ""))
        import_state = func.trim(func.coalesce(LibraryReadableResource.import_state, ""))
        rows = self._db.execute(
            select(source_format.label("source_format"), import_state.label("import_state"), func.count().label("option_count"))
            .where(resource_visibility_predicate(context))
            .group_by(source_format, import_state)
        ).all()
        formats: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for row in rows:
            for counts, value in [(formats, row.source_format), (statuses, row.import_state)]:
                if value:
                    counts[value] = counts.get(value, 0) + int(row.option_count)

        def options(counts: dict[str, int]) -> tuple[LibraryFilterOption, ...]:
            # Match SQLite's built-in ASCII lower() ordering for wire identifiers.
            ascii_lower = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
            return tuple(LibraryFilterOption(value, value, counts[value]) for value in sorted(
                counts, key=lambda value: (-counts[value], value.translate(ascii_lower), value),
            ))

        return options(formats), options(statuses)

    def _library_options(
        self, context: AuthorizationContext
    ) -> tuple[LibraryFilterOption, ...]:
        statement = select(Library.id, Library.name, Library.root_path).where(Library.deletion_requested_at.is_(None))
        if not context.is_admin:
            if not context.library_ids:
                return ()
            statement = statement.where(Library.id.in_(context.library_ids))
        rows = self._db.execute(
            statement.order_by(
                Library.sort_order.asc(), Library.created_at.desc(), Library.id.desc()
            )
        ).all()
        return tuple(
            LibraryFilterOption(
                str(row.id), str(row.name), root_path=str(row.root_path)
            )
            for row in rows
        )

    def _shelf_options(
        self, context: AuthorizationContext
    ) -> tuple[LibraryFilterOption, ...]:
        rows = self._db.execute(
            select(Shelf.id, Shelf.name)
            .where(
                Shelf.owner_user_id == context.user_id,
                func.upper(func.coalesce(Shelf.kind, "STATIC")) == "STATIC",
            )
            .order_by(func.lower(Shelf.name).asc(), Shelf.id.asc())
        ).all()
        return tuple(
            LibraryFilterOption(value=str(row.id), label=str(row.name)) for row in rows
        )

    def _facet_options(
        self,
        context: AuthorizationContext,
        kind: str,
        query: str,
        limit: int,
    ) -> tuple[tuple[LibraryFilterOption, ...], bool]:
        count = func.count(distinct(LibraryBook.id)).label("option_count")
        rows = self._db.execute(
            select(LibraryFacet.id, LibraryFacet.name, count)
            .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
            .join(LibraryBook, LibraryBook.id == LibraryBookFacet.book_id)
            .where(
                LibraryFacet.kind == kind,
                func.lower(LibraryFacet.name).contains(query.lower(), autoescape=True),
                LibraryBook.visibility_state == "VISIBLE",
                book_visibility_predicate(context),
            )
            .group_by(LibraryFacet.id)
            .order_by(
                count.desc(), LibraryFacet.normalized_name.asc(), LibraryFacet.id.asc()
            )
            .limit(limit + 1)
        ).all()
        return tuple(
            LibraryFilterOption(str(row.name), str(row.name), int(row.option_count))
            for row in rows[:limit]
        ), len(rows) > limit
