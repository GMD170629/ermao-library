"""Bounded ORM queries for library filter schema and suggestions."""

from __future__ import annotations

from sqlalchemy import ColumnElement, distinct, func, select, union_all
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.library import (
    Library,
    LibraryFacet,
    LibraryVolume,
    LibraryWork,
    LibraryWorkFacet,
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
            formats=self._volume_options(context, LibraryVolume.format),
            import_statuses=self._volume_options(context, LibraryVolume.import_status),
            origins=self._origin_options(context),
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
            index_ready = True
            options, has_more = (
                self._tag_options(context, query, limit) if query else ((), False)
            )
        else:
            index_ready = True
            column = (
                LibraryWork.author if source == "authors" else LibraryWork.series_name
            )
            options, has_more = (
                self._work_text_options(context, column, query, limit)
                if query
                else ((), False)
            )
        return LibraryFilterOptionPage(
            source=source,
            query=query,
            options=options,
            has_more=has_more,
            index_ready=index_ready,
        )

    def _volume_options(
        self,
        context: AuthorizationContext,
        column: ColumnElement[str],
    ) -> tuple[LibraryFilterOption, ...]:
        value = func.trim(func.coalesce(column, ""))
        count = func.count().label("option_count")
        rows = self._db.execute(
            select(value.label("value"), count)
            .where(
                LibraryVolume.hidden.is_(False),
                volume_visibility_predicate(context),
                value != "",
            )
            .group_by(value)
            .order_by(count.desc(), func.lower(value).asc(), value.asc())
        ).all()
        return tuple(
            LibraryFilterOption(str(row.value), str(row.value), int(row.option_count))
            for row in rows
        )

    def _origin_options(
        self, context: AuthorizationContext
    ) -> tuple[LibraryFilterOption, ...]:
        work_value = func.trim(func.coalesce(LibraryWork.origin, ""))
        volume_value = func.trim(func.coalesce(LibraryVolume.origin, ""))
        work_counts = (
            select(work_value.label("value"), func.count().label("option_count"))
            .where(
                func.coalesce(LibraryWork.hidden, False).is_(False),
                work_visibility_predicate(context),
                work_value != "",
            )
            .group_by(work_value)
        )
        volume_counts = (
            select(volume_value.label("value"), func.count().label("option_count"))
            .where(
                LibraryVolume.hidden.is_(False),
                volume_visibility_predicate(context),
                volume_value != "",
            )
            .group_by(volume_value)
        )
        combined = union_all(work_counts, volume_counts).subquery()
        total = func.sum(combined.c.option_count).label("option_count")
        rows = self._db.execute(
            select(combined.c.value, total)
            .group_by(combined.c.value)
            .order_by(
                total.desc(),
                func.lower(combined.c.value).asc(),
                combined.c.value.asc(),
            )
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
                value=str(row.id),
                label=str(row.name),
                root_path=str(row.root_path),
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

    def _work_text_options(
        self,
        context: AuthorizationContext,
        column: ColumnElement[str | None],
        query: str,
        limit: int,
    ) -> tuple[tuple[LibraryFilterOption, ...], bool]:
        value = func.trim(func.coalesce(column, ""))
        normalized_value = func.lower(value)
        count = func.count(distinct(LibraryWork.id)).label("option_count")
        stable_id = func.min(LibraryWork.id).label("stable_id")
        rows = self._db.execute(
            select(value.label("value"), count, stable_id)
            .where(
                func.coalesce(LibraryWork.hidden, False).is_(False),
                work_visibility_predicate(context),
                value != "",
                normalized_value.contains(query.lower(), autoescape=True),
            )
            .group_by(value)
            .order_by(
                count.desc(), normalized_value.asc(), value.asc(), stable_id.asc()
            )
            .limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        return (
            tuple(
                LibraryFilterOption(
                    str(row.value), str(row.value), int(row.option_count)
                )
                for row in rows[:limit]
            ),
            has_more,
        )

    def _tag_options(
        self,
        context: AuthorizationContext,
        query: str,
        limit: int,
    ) -> tuple[tuple[LibraryFilterOption, ...], bool]:
        count = func.count(distinct(LibraryWork.id)).label("option_count")
        rows = self._db.execute(
            select(LibraryFacet.id, LibraryFacet.name, count)
            .join(
                LibraryWorkFacet,
                LibraryWorkFacet.facet_id == LibraryFacet.id,
            )
            .join(LibraryWork, LibraryWork.id == LibraryWorkFacet.work_id)
            .where(
                LibraryFacet.kind == "TAG",
                func.lower(LibraryFacet.name).contains(query.lower(), autoescape=True),
                func.coalesce(LibraryWork.hidden, False).is_(False),
                work_visibility_predicate(context),
            )
            .group_by(LibraryFacet.id)
            .order_by(
                count.desc(),
                LibraryFacet.normalized_name.asc(),
                LibraryFacet.id.asc(),
            )
            .limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        return (
            tuple(
                LibraryFilterOption(str(row.name), str(row.name), int(row.option_count))
                for row in rows[:limit]
            ),
            has_more,
        )
