"""ORM queries for dashboard and management overview surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.contracts.media_capabilities import require_reader_type_for_format
from app.core.authorization import (
    AuthorizationContext,
    book_visibility_predicate,
    library_visibility_predicate,
    resource_visibility_predicate,
)
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.library.application.dashboard import (
    DashboardActivityQueryPort,
    DashboardContinueReading,
)
from app.modules.library.infrastructure.book_covers import SqlAlchemyBookCoverQueries
from app.modules.reader.public import ReaderV5LibraryPresentationQueryPort


def _visible_book_filter(context: AuthorizationContext):
    return (
        LibraryBook.visibility_state == "VISIBLE",
        book_visibility_predicate(context),
    )


def dashboard_summary(
    db: Session,
    context: AuthorizationContext,
    user_id: str,
    *,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> dict[str, Any]:
    visible_book = _visible_book_filter(context)
    total_books = int(
        db.scalar(select(func.count()).select_from(LibraryBook).where(*visible_book))
        or 0
    )

    latest_progress_at = reader_queries.latest_progress_at(user_id=user_id)
    storage = int(
        db.scalar(
            select(func.coalesce(func.sum(LibrarySourceNode.observed_size_bytes), 0))
            .select_from(LibraryResourceAsset)
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
                library_visibility_predicate(
                    context,
                    cast(ColumnElement[str], LibrarySourceNode.library_id),
                ),
            )
        )
        or 0
    )
    library_count = (
        int(
            db.scalar(
                select(func.count())
                .select_from(Library)
                .where(Library.enabled.is_(True))
            )
            or 0
        )
        if context.is_admin
        else len(context.library_ids)
    )
    return {
        "totalBooks": total_books,
        "storageUsedBytes": storage,
        "libraryCount": library_count,
        "lastImportAt": None,
        "latestSyncAt": latest_progress_at,
    }


def recent_books(
    db: Session, context: AuthorizationContext, *, limit: int
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryBook.id,
            LibraryBookMetadata.title,
            LibraryBookMetadata.author,
            LibraryBookMetadata.cover_status,
            LibraryBookMetadata.cover_path,
            LibraryBook.created_at,
        )
        .select_from(LibraryBook)
        .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(*_visible_book_filter(context))
        .order_by(LibraryBook.created_at.desc(), LibraryBook.id.desc())
        .limit(limit)
    ).all()
    cover_paths = SqlAlchemyBookCoverQueries(db).preferred_paths(
        tuple(str(row.id) for row in rows)
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "author": row.author,
            "coverStatus": (
                "READY" if cover_paths.get(str(row.id)) else row.cover_status
            ),
            "coverPath": cover_paths.get(str(row.id)) or row.cover_path,
            "createdAt": row.created_at,
        }
        for row in rows
    ]


def recent_reading(
    db: Session,
    context: AuthorizationContext,
    user_id: str,
    *,
    limit: int,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> list[dict[str, Any]]:
    latest_read_at = cast(
        ColumnElement[object],
        reader_queries.latest_read_at_expression(
            context=context,
            user_id=user_id,
            book_id_expression=LibraryBook.id,
        ),
    ).label("lastReadAt")
    rows = db.execute(
        select(
            LibraryBook.id,
            LibraryBookMetadata.title,
            LibraryBookMetadata.author,
            LibraryBookMetadata.cover_status,
            LibraryBookMetadata.cover_path,
            latest_read_at,
        )
        .select_from(LibraryBook)
        .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(
            *_visible_book_filter(context),
            latest_read_at.is_not(None),
        )
        .order_by(latest_read_at.desc(), LibraryBook.id.desc())
        .limit(limit)
    ).all()
    cover_paths = SqlAlchemyBookCoverQueries(db).preferred_paths(
        tuple(str(row.id) for row in rows)
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "author": row.author,
            "coverStatus": (
                "READY" if cover_paths.get(str(row.id)) else row.cover_status
            ),
            "coverPath": cover_paths.get(str(row.id)) or row.cover_path,
            "lastReadAt": row.lastReadAt,
        }
        for row in rows
    ]


def continue_reading_progress(
    db: Session,
    context: AuthorizationContext,
    user_id: str,
    *,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> dict[str, Any] | None:
    rows = db.execute(
        select(
            LibraryReadableResource.id.label("resource_id"),
            LibraryReadableResourceMetadata.title.label("resource_title"),
            LibraryReadableResourceMetadata.narrator,
            LibraryReadableResource.format.label("resource_format"),
            LibraryBook.id.label("book_id"),
            LibraryBookMetadata.title.label("book_title"),
            LibraryBookMetadata.author,
            LibraryBookMetadata.cover_path,
            LibraryBookMetadata.cover_status,
            LibraryBook.updated_at.label("book_updated_at"),
        )
        .select_from(LibraryReadableResource)
        .join(
            LibraryReadableResourceMetadata,
            LibraryReadableResourceMetadata.resource_id == LibraryReadableResource.id,
        )
        .join(LibraryBook, LibraryBook.id == LibraryReadableResource.book_id)
        .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(*_visible_book_filter(context), resource_visibility_predicate(context))
    ).all()
    presentations = reader_queries.list_presentations(
        user_id=user_id,
        resource_ids=[str(row.resource_id) for row in rows],
    )
    candidates = [
        (row, presentations[str(row.resource_id)])
        for row in rows
        if str(row.resource_id) in presentations
    ]
    if not candidates:
        return None
    unfinished = [
        candidate for candidate in candidates if candidate[1].display_percent < 100
    ]
    selected, selected_progress = max(
        unfinished or candidates,
        key=lambda candidate: (candidate[1].updated_at, str(candidate[0].resource_id)),
    )
    cover_path = (
        SqlAlchemyBookCoverQueries(db)
        .preferred_paths((str(selected.book_id),))
        .get(str(selected.book_id))
    )
    reader_type = require_reader_type_for_format(str(selected.resource_format))
    return {
        "bookId": selected.book_id,
        "title": selected.book_title,
        "author": selected.author,
        "coverPath": cover_path or selected.cover_path,
        "coverStatus": "READY" if cover_path else selected.cover_status,
        "bookUpdatedAt": selected.book_updated_at,
        "resourceFormat": selected.resource_format,
        "readerType": reader_type.value,
        "resourceId": selected.resource_id,
        "resourceTitle": selected.resource_title,
        "narrator": selected.narrator,
        "percent": float(selected_progress.display_percent),
        "updatedAt": selected_progress.updated_at,
    }


def list_management_books(db: Session, *, limit: int = 300) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryBook.id,
            LibraryBookMetadata.title,
            LibraryBookMetadata.author,
            LibraryBookMetadata.series_name,
            LibraryBook.library_id,
            LibraryBook.visibility_state,
            LibraryBook.updated_at,
        )
        .select_from(LibraryBook)
        .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(LibraryBook.visibility_state == "VISIBLE")
        .order_by(LibraryBook.updated_at.desc(), LibraryBook.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "author": row.author,
            "seriesName": row.series_name,
            "libraryId": row.library_id,
            "visibilityState": row.visibility_state,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


class SqlAlchemyDashboardActivityQueries(DashboardActivityQueryPort):
    def __init__(
        self,
        db: Session,
        *,
        reader_queries: ReaderV5LibraryPresentationQueryPort,
    ) -> None:
        self._db = db
        self._reader_queries = reader_queries

    def recent_book_ids(
        self,
        *,
        context: AuthorizationContext,
        limit: int,
    ) -> tuple[str, ...]:
        return tuple(
            str(row["id"]) for row in recent_books(self._db, context, limit=limit)
        )

    def recent_reading_book_ids(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
        limit: int,
    ) -> tuple[str, ...]:
        return tuple(
            str(row["id"])
            for row in recent_reading(
                self._db,
                context,
                user_id,
                limit=limit,
                reader_queries=self._reader_queries,
            )
        )

    def continue_reading(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
    ) -> DashboardContinueReading | None:
        row = continue_reading_progress(
            self._db,
            context,
            user_id,
            reader_queries=self._reader_queries,
        )
        if row is None:
            return None
        return DashboardContinueReading(
            book_id=str(row["bookId"]),
            title=str(row["title"]),
            author=str(row.get("author") or "未知作者"),
            resource_format=str(row["resourceFormat"]),
            reader_type=cast(
                Literal["reflowable", "comic", "pdf", "audio"],
                str(row["readerType"]),
            ),
            resource_id=str(row["resourceId"]),
            resource_title=str(row.get("resourceTitle") or ""),
            narrator=str(row["narrator"]) if row.get("narrator") else None,
            progress=float(row.get("percent") or 0),
            updated_at=(
                row["updatedAt"] if isinstance(row.get("updatedAt"), datetime) else None
            ),
        )
