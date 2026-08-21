"""Bounded ORM queries for library filter schema and suggestions."""

from __future__ import annotations

from sqlalchemy import ColumnElement, distinct, func, select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    book_visibility_predicate,
    resource_visibility_predicate,
)
from app.models import (
    Library,
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
)
from app.models.shelf import Shelf
from app.modules.library.application.filter_options import (
    LibraryFilterOption,
    LibraryFilterOptionPage,
    LibraryFilterOptionSource,
    LibraryFilterSchemaOptions,
)


class SqlAlchemyLibraryFilterQueries:
    """Apply authorization while aggregating bounded filter values in SQLite."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def schema_options(
        self, context: AuthorizationContext
    ) -> LibraryFilterSchemaOptions:
        return LibraryFilterSchemaOptions(
            formats=self._resource_options(context, LibraryReadableResource.format),
            import_statuses=self._resource_options(
                context, LibraryReadableResource.import_state
            ),
            origins=(),
            libraries=self._library_options(context),
            shelves=self._shelf_options(context),
        )

    def search_options(
        self,
        context: AuthorizationContext,
        *,
        source: LibraryFilterOptionSource,
        query: str,
        limit: int,
    ) -> LibraryFilterOptionPage:
        if source == "tags":
            options, has_more = self._tag_options(context, query, limit)
        else:
            column = (
                LibraryBookMetadata.author
                if source == "authors"
                else LibraryBookMetadata.series_name
            )
            options, has_more = self._book_text_options(context, column, query, limit)
        return LibraryFilterOptionPage(
            source=source,
            query=query,
            options=options,
            has_more=has_more,
            index_ready=True,
        )

    def _resource_options(
        self,
        context: AuthorizationContext,
        column: ColumnElement[str],
    ) -> tuple[LibraryFilterOption, ...]:
        value = func.trim(func.coalesce(column, ""))
        count = func.count().label("option_count")
        rows = self._db.execute(
            select(value.label("value"), count)
            .where(resource_visibility_predicate(context), value != "")
            .group_by(value)
            .order_by(count.desc(), func.lower(value).asc(), value.asc())
        ).all()
        return tuple(
            LibraryFilterOption(str(row.value), str(row.value), int(row.option_count))
            for row in rows
        )

    def _library_options(
        self, context: AuthorizationContext
    ) -> tuple[LibraryFilterOption, ...]:
        statement = select(Library.id, Library.name, Library.root_path)
        if not context.is_admin:
            if not context.library_ids:
                return ()
            statement = statement.where(Library.id.in_(context.library_ids))
        rows = self._db.execute(
            statement.order_by(func.lower(Library.name).asc(), Library.id.asc())
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

    def _book_text_options(
        self,
        context: AuthorizationContext,
        column: ColumnElement[str | None],
        query: str,
        limit: int,
    ) -> tuple[tuple[LibraryFilterOption, ...], bool]:
        value = func.trim(func.coalesce(column, ""))
        normalized = func.lower(value)
        count = func.count(distinct(LibraryBook.id)).label("option_count")
        rows = self._db.execute(
            select(
                value.label("value"), count, func.min(LibraryBook.id).label("stable_id")
            )
            .select_from(LibraryBook)
            .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
            .where(
                LibraryBook.visibility_state == "VISIBLE",
                book_visibility_predicate(context),
                value != "",
                normalized.contains(query.lower(), autoescape=True),
            )
            .group_by(value)
            .order_by(count.desc(), normalized.asc(), value.asc())
            .limit(limit + 1)
        ).all()
        return tuple(
            LibraryFilterOption(str(row.value), str(row.value), int(row.option_count))
            for row in rows[:limit]
        ), len(rows) > limit

    def _tag_options(
        self,
        context: AuthorizationContext,
        query: str,
        limit: int,
    ) -> tuple[tuple[LibraryFilterOption, ...], bool]:
        count = func.count(distinct(LibraryBook.id)).label("option_count")
        rows = self._db.execute(
            select(LibraryFacet.id, LibraryFacet.name, count)
            .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
            .join(LibraryBook, LibraryBook.id == LibraryBookFacet.book_id)
            .where(
                LibraryFacet.kind == "TAG",
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
