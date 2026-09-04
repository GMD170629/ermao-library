"""SQLAlchemy adapter for Reader-owned Library presentation queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import and_, exists, func, literal, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from app.core.authorization import AuthorizationContext, resource_visibility_predicate
from app.models import LibraryReadableResource
from app.models.common import cuid
from app.modules.reader.application.v5_library_queries import (
    ReaderV5LibraryPresentationQueryPort,
    ReaderV5PresentationView,
    ReaderV5StatusView,
)
from app.modules.reader.infrastructure.persistence.models import (
    ReaderResourceProgressV5,
    ReaderResourceReadingStatusV5,
)


def _presentation_view(row: ReaderResourceProgressV5) -> ReaderV5PresentationView:
    return ReaderV5PresentationView(
        resource_id=row.resource_id,
        display_percent=float(row.display_percent),
        total_progression=float(row.total_progression),
        current_href=row.current_href,
        chapter_href=row.chapter_href,
        chapter_title=row.chapter_title,
        chapter_index=row.chapter_index,
        page_number=row.page_number,
        page_total=row.page_total,
        playback_position_millis=row.playback_position_millis,
        playback_duration_millis=row.playback_duration_millis,
        captured_at=row.captured_at,
        updated_at=row.updated_at,
    )


def _status_view(row: ReaderResourceReadingStatusV5) -> ReaderV5StatusView:
    return ReaderV5StatusView(
        resource_id=row.resource_id,
        status=cast(Literal["UNREAD", "FINISHED"], row.status),
        updated_at=row.updated_at,
    )


def reader_v5_latest_read_at_expression(
    *,
    context: AuthorizationContext,
    user_id: str,
    book_id_expression: object,
) -> object:
    resource = aliased(LibraryReadableResource)
    progress = aliased(ReaderResourceProgressV5)
    return (
        select(func.max(progress.updated_at))
        .select_from(progress)
        .join(resource, resource.id == progress.resource_id)
        .where(
            progress.user_id == user_id,
            resource.book_id == book_id_expression,
            resource_visibility_predicate(context, resource),
        )
        .correlate_except(progress, resource)
        .scalar_subquery()
    )


def reader_v5_progress_expression(
    *,
    context: AuthorizationContext,
    user_id: str | None,
    book_id_expression: object,
    field: Literal["display_percent", "updated_at"],
) -> object:
    # A missing actor must never turn a user-private progress projection into
    # a cross-user aggregate.  Library callers that have no actor receive a
    # NULL scalar, which naturally does not satisfy progress/date filters.
    if user_id is None:
        return literal(None)
    resource = aliased(LibraryReadableResource)
    progress = aliased(ReaderResourceProgressV5)
    statement = (
        select(
            progress.display_percent
            if field == "display_percent"
            else progress.updated_at
        )
        .select_from(progress)
        .join(resource, resource.id == progress.resource_id)
        .where(
            resource.book_id == book_id_expression,
            resource_visibility_predicate(context, resource),
        )
        .order_by(progress.updated_at.desc(), progress.resource_id.desc())
        .limit(1)
    )
    statement = statement.where(progress.user_id == user_id)
    return statement.correlate_except(progress, resource).scalar_subquery()


def reader_v5_reading_status_expression(
    *,
    context: AuthorizationContext,
    user_id: str,
    book_id_expression: object,
    status: str,
) -> object:
    """Build a user-scoped, per-resource aggregate from independent v5 state.

    Each nested query has its own aliases and explicit correlation.  This is
    important for multi-resource books: a progress row for one book must not
    make another book ``READING``, and an explicit status on one resource must
    not accidentally be evaluated against every resource in the database.
    """

    resource = aliased(LibraryReadableResource)
    visible = and_(
        resource.book_id == book_id_expression,
        resource_visibility_predicate(context, resource),
    )
    has_resource = exists(select(resource.id).where(visible)).correlate_except(resource)

    # Per-resource explicit status predicates.  These subqueries correlate to
    # the resource row in ``unfinished`` rather than introducing a second
    # resource FROM clause.
    unfinished_resource = aliased(LibraryReadableResource)
    progress = aliased(ReaderResourceProgressV5)
    explicit_status = aliased(ReaderResourceReadingStatusV5)
    resource_unread = exists(
        select(explicit_status.id).where(
            explicit_status.user_id == user_id,
            explicit_status.resource_id == unfinished_resource.id,
            explicit_status.status == "UNREAD",
        )
    ).correlate(unfinished_resource)
    resource_finished = exists(
        select(explicit_status.id).where(
            explicit_status.user_id == user_id,
            explicit_status.resource_id == unfinished_resource.id,
            explicit_status.status == "FINISHED",
        )
    ).correlate(unfinished_resource)
    progress_finished = exists(
        select(progress.id).where(
            progress.user_id == user_id,
            progress.resource_id == unfinished_resource.id,
            progress.display_percent >= 100,
        )
    ).correlate(unfinished_resource)
    resource_completed = (~resource_unread) & (progress_finished | resource_finished)
    unfinished = exists(
        select(unfinished_resource.id).where(
            unfinished_resource.book_id == book_id_expression,
            resource_visibility_predicate(context, unfinished_resource),
            ~resource_completed,
        )
    ).correlate_except(unfinished_resource)

    # A progress row is considered started only when no explicit status has
    # reset or finished that same resource.  FINISHED without a progress row
    # still counts as activity so a multi-resource book is not UNREAD.
    started_resource = aliased(LibraryReadableResource)
    started_progress = aliased(ReaderResourceProgressV5)
    started_status = aliased(ReaderResourceReadingStatusV5)
    started_unread = exists(
        select(started_status.id).where(
            started_status.user_id == user_id,
            started_status.resource_id == started_resource.id,
            started_status.status == "UNREAD",
        )
    ).correlate(started_resource)
    started_finished = exists(
        select(started_status.id).where(
            started_status.user_id == user_id,
            started_status.resource_id == started_resource.id,
            started_status.status == "FINISHED",
        )
    ).correlate(started_resource)
    started_progress_exists = exists(
        select(started_progress.id).where(
            started_progress.user_id == user_id,
            started_progress.resource_id == started_resource.id,
            started_progress.display_percent > 0,
        )
    ).correlate(started_resource)
    started = exists(
        select(started_resource.id).where(
            started_resource.book_id == book_id_expression,
            resource_visibility_predicate(context, started_resource),
            started_progress_exists & ~started_unread & ~started_finished,
        )
    ).correlate_except(started_resource)
    explicit_finished_any = exists(
        select(explicit_status.id)
        .join(
            unfinished_resource,
            explicit_status.resource_id == unfinished_resource.id,
        )
        .where(
            explicit_status.user_id == user_id,
            explicit_status.status == "FINISHED",
            unfinished_resource.book_id == book_id_expression,
            resource_visibility_predicate(context, unfinished_resource),
        )
    ).correlate_except(explicit_status, unfinished_resource)
    active = started | explicit_finished_any

    normalized = status.upper()
    if normalized == "FINISHED":
        return has_resource & ~unfinished
    if normalized == "READING":
        return active & unfinished
    return ~active


class SqlAlchemyReaderV5LibraryPresentationQueries(
    ReaderV5LibraryPresentationQueryPort
):
    """Keep all Reader v5 ORM knowledge behind the Reader public query port."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_presentations(
        self, *, user_id: str, resource_ids: Sequence[str]
    ) -> Mapping[str, ReaderV5PresentationView]:
        normalized_ids = tuple(
            dict.fromkeys(str(resource_id) for resource_id in resource_ids)
        )
        if not normalized_ids:
            return {}
        rows = self._db.scalars(
            select(ReaderResourceProgressV5).where(
                ReaderResourceProgressV5.user_id == user_id,
                ReaderResourceProgressV5.resource_id.in_(normalized_ids),
            )
        ).all()
        return {row.resource_id: _presentation_view(row) for row in rows}

    def get_presentation(
        self, *, user_id: str, resource_id: str
    ) -> ReaderV5PresentationView | None:
        row = self._db.scalar(
            select(ReaderResourceProgressV5).where(
                ReaderResourceProgressV5.user_id == user_id,
                ReaderResourceProgressV5.resource_id == resource_id,
            )
        )
        return _presentation_view(row) if row is not None else None

    def latest_progress_at(self, *, user_id: str) -> datetime | None:
        return self._db.scalar(
            select(ReaderResourceProgressV5.updated_at)
            .where(ReaderResourceProgressV5.user_id == user_id)
            .order_by(
                ReaderResourceProgressV5.updated_at.desc(),
                ReaderResourceProgressV5.resource_id.desc(),
            )
            .limit(1)
        )

    def latest_read_at_expression(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
        book_id_expression: object,
    ) -> object:
        return reader_v5_latest_read_at_expression(
            context=context,
            user_id=user_id,
            book_id_expression=book_id_expression,
        )

    def progress_expression(
        self,
        *,
        context: AuthorizationContext,
        user_id: str | None,
        book_id_expression: object,
        field: Literal["display_percent", "updated_at"],
    ) -> object:
        return reader_v5_progress_expression(
            context=context,
            user_id=user_id,
            book_id_expression=book_id_expression,
            field=field,
        )

    def reading_status_expression(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
        book_id_expression: object,
        status: str,
    ) -> object:
        return reader_v5_reading_status_expression(
            context=context,
            user_id=user_id,
            book_id_expression=book_id_expression,
            status=status,
        )

    def list_statuses(
        self, *, user_id: str, resource_ids: Sequence[str]
    ) -> Mapping[str, ReaderV5StatusView]:
        normalized_ids = tuple(
            dict.fromkeys(str(resource_id) for resource_id in resource_ids)
        )
        if not normalized_ids:
            return {}
        rows = self._db.scalars(
            select(ReaderResourceReadingStatusV5).where(
                ReaderResourceReadingStatusV5.user_id == user_id,
                ReaderResourceReadingStatusV5.resource_id.in_(normalized_ids),
            )
        ).all()
        return {row.resource_id: _status_view(row) for row in rows}

    def upsert_statuses(
        self,
        *,
        user_id: str,
        resource_ids: Sequence[str],
        status: str,
        updated_at: datetime,
    ) -> None:
        if status not in {"UNREAD", "FINISHED"}:
            raise ValueError("invalid Reader v5 reading status")
        normalized_ids = tuple(
            dict.fromkeys(str(resource_id) for resource_id in resource_ids)
        )
        if not normalized_ids:
            return
        values = [
            {
                "id": cuid(),
                "user_id": user_id,
                "resource_id": resource_id,
                "status": status,
                "updated_at": updated_at,
            }
            for resource_id in normalized_ids
        ]
        self._db.execute(
            sqlite_insert(ReaderResourceReadingStatusV5)
            .values(values)
            .on_conflict_do_update(
                index_elements=[
                    ReaderResourceReadingStatusV5.user_id,
                    ReaderResourceReadingStatusV5.resource_id,
                ],
                set_={
                    ReaderResourceReadingStatusV5.status: status,
                    ReaderResourceReadingStatusV5.updated_at: updated_at,
                },
            )
        )


__all__ = [
    "SqlAlchemyReaderV5LibraryPresentationQueries",
    "reader_v5_latest_read_at_expression",
    "reader_v5_progress_expression",
    "reader_v5_reading_status_expression",
]
