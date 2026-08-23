"""Resource-authorized ORM book listing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    authorization_context,
    book_visibility_predicate,
    resource_visibility_predicate,
)
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    ReaderResourceProgress,
)
from app.models.auth import User
from app.modules.library.application.book_list import (
    BookListQuery,
    BookListResult,
    resolve_page_size,
)
from app.modules.library.infrastructure.book_covers import (
    SqlAlchemyBookCoverQueries,
    effective_book_cover_exists,
)
from app.modules.library.infrastructure.books import _book_record
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    resolve_library_roots,
)
from app.modules.reader.public import (
    MediaKind,
    ResourceReadingState,
    choose_continue_resource_id,
    completed_for_available_resources,
)


@dataclass(frozen=True, slots=True)
class _ResourceSummary:
    resource_id: str
    media_kind: MediaKind
    sort_order: int
    percent: float
    last_read_at: datetime | None


def _resource_exists(
    *,
    book_id: object,
    media_kinds: tuple[str, ...] = (),
    formats: tuple[str, ...] = (),
) -> ColumnElement[bool]:
    """Match readable resources belonging to an already-authorized Book.

    ``LibraryReadableResource`` has a composite foreign key from ``bookId`` and
    ``libraryId`` to ``LibraryBook``. The enclosing Book predicate therefore
    owns both the authorization scope and the library relationship. Keeping
    the correlated predicate on ``bookId`` lets SQLite use the dedicated
    ``LibraryReadableResource_bookId_idx`` instead of rescanning every resource
    through the separate library index for each Book.
    """
    predicates: list[ColumnElement[bool]] = [
        LibraryReadableResource.book_id == book_id,
        LibraryReadableResource.enablement_state == "ENABLED",
        LibraryReadableResource.import_state == "READY",
    ]
    if media_kinds:
        predicates.append(LibraryReadableResource.media_kind.in_(media_kinds))
    if formats:
        predicates.append(LibraryReadableResource.format.in_(formats))
    return exists(select(LibraryReadableResource.id).where(*predicates))


def _predicates(
    db: Session,
    context: AuthorizationContext,
    user: User,
    query: BookListQuery,
) -> list[ColumnElement[bool]]:
    predicates: list[ColumnElement[bool]] = [
        LibraryBook.visibility_state == "VISIBLE",
        book_visibility_predicate(context),
    ]
    if query.visibility == "ignored":
        return [
            LibraryBook.visibility_state == "HIDDEN",
            book_visibility_predicate(context),
        ]
    term = (query.search or query.keyword or "").strip().casefold()
    if term:
        pattern = f"%{term}%"
        predicates.append(
            or_(
                func.lower(LibraryBookMetadata.title).like(pattern),
                func.lower(func.coalesce(LibraryBookMetadata.author, "")).like(pattern),
                func.lower(func.coalesce(LibraryBookMetadata.series_name, "")).like(
                    pattern
                ),
                func.lower(func.coalesce(LibraryBookMetadata.description, "")).like(
                    pattern
                ),
            )
        )
    if query.type_filter:
        normalized = query.type_filter.strip().upper()
        media_values = {
            "EBOOK": "EBOOK",
            "AUDIO": "AUDIOBOOK",
            "AUDIOBOOK": "AUDIOBOOK",
            "COMIC": "COMIC",
        }
        if normalized in media_values:
            predicates.append(
                _resource_exists(
                    book_id=LibraryBook.id, media_kinds=(media_values[normalized],)
                )
            )
        else:
            predicates.append(
                _resource_exists(book_id=LibraryBook.id, formats=(normalized,))
            )
    if query.media_kinds:
        predicates.append(
            _resource_exists(book_id=LibraryBook.id, media_kinds=query.media_kinds)
        )
    statuses = tuple(
        dict.fromkeys(
            (*query.statuses, query.status) if query.status else query.statuses
        )
    )
    for status in statuses:
        normalized = status.upper()
        ready_resource = (
            LibraryReadableResource.book_id == LibraryBook.id,
            resource_visibility_predicate(context),
        )
        started = exists(
            select(ReaderResourceProgress.id)
            .join(
                LibraryReadableResource,
                LibraryReadableResource.id == ReaderResourceProgress.resource_id,
            )
            .where(
                LibraryReadableResource.book_id == LibraryBook.id,
                ReaderResourceProgress.user_id == user.id,
                ReaderResourceProgress.percent > 0,
                resource_visibility_predicate(context),
            )
        )
        unfinished = exists(
            select(LibraryReadableResource.id)
            .outerjoin(
                ReaderResourceProgress,
                and_(
                    ReaderResourceProgress.resource_id == LibraryReadableResource.id,
                    ReaderResourceProgress.user_id == user.id,
                ),
            )
            .where(
                *ready_resource,
                or_(
                    ReaderResourceProgress.id.is_(None),
                    ReaderResourceProgress.percent < 100,
                ),
            )
        )
        available = exists(select(LibraryReadableResource.id).where(*ready_resource))
        if normalized == "READING":
            predicates.extend((started, unfinished))
        elif normalized == "UNREAD":
            predicates.append(~started)
        elif normalized == "FINISHED":
            predicates.extend((available, ~unfinished))
    if query.publication_status:
        predicates.append(
            LibraryBookMetadata.publication_status == query.publication_status
        )
    if query.tracking_status:
        predicates.append(LibraryBookMetadata.tracking_status == query.tracking_status)
    if query.tag:
        predicates.append(
            exists(
                select(LibraryBookFacet.book_id)
                .join(LibraryFacet, LibraryFacet.id == LibraryBookFacet.facet_id)
                .where(
                    LibraryBookFacet.book_id == LibraryBook.id,
                    LibraryFacet.kind == "TAG",
                    LibraryFacet.name == query.tag,
                )
            )
        )
    if query.missing_cover:
        predicates.append(~effective_book_cover_exists(LibraryBook.id))
    if query.new_import:
        predicates.append(_resource_exists(book_id=LibraryBook.id))
    if query.series_name:
        predicates.append(
            func.trim(LibraryBookMetadata.series_name) == query.series_name.strip()
        )
    if query.facet_kind and query.facet_id:
        predicates.append(
            exists(
                select(LibraryBookFacet.book_id).where(
                    LibraryBookFacet.book_id == LibraryBook.id,
                    LibraryBookFacet.facet_id == query.facet_id,
                    exists(
                        select(LibraryFacet.id).where(
                            LibraryFacet.id == LibraryBookFacet.facet_id,
                            LibraryFacet.kind == query.facet_kind,
                        )
                    ),
                )
            )
        )
    if query.filter_expression is not None:
        dynamic = compile_filter_expression(
            query.filter_expression,
            context=context,
            user_id=user.id,
            shelf_owner_user_id=user.id,
            library_roots=resolve_library_roots(db, query.filter_expression, context),
        )
        if dynamic is not None:
            predicates.append(dynamic)
    return predicates


def _order(
    query: BookListQuery,
    *,
    user: User,
    context: AuthorizationContext,
) -> list[ColumnElement[object]]:
    descending = (query.sort_direction or "").lower() == "desc" or (
        not query.sort_direction
        and query.sort in {"updated", "recent_read", "recent_import", "progress"}
    )

    def direction(column: object) -> ColumnElement[object]:
        expression = cast(ColumnElement[object], column)
        return expression.desc() if descending else expression.asc()

    def ascending(column: object) -> ColumnElement[object]:
        return cast(ColumnElement[object], column).asc()

    if query.sort == "title":
        return [direction(LibraryBookMetadata.title), ascending(LibraryBook.id)]
    if query.sort == "author":
        return [
            direction(LibraryBookMetadata.author),
            ascending(LibraryBookMetadata.title),
            ascending(LibraryBook.id),
        ]
    if query.sort == "series":
        return [
            direction(LibraryBookMetadata.series_name),
            ascending(LibraryBookMetadata.series_index),
            ascending(LibraryBook.id),
        ]
    if query.sort == "series_index":
        return [
            direction(LibraryBookMetadata.series_index),
            ascending(LibraryBookMetadata.title),
            ascending(LibraryBook.id),
        ]
    if query.sort == "recent_read":
        latest_read_at = (
            select(func.max(ReaderResourceProgress.updated_at))
            .join(
                LibraryReadableResource,
                LibraryReadableResource.id == ReaderResourceProgress.resource_id,
            )
            .where(
                LibraryReadableResource.book_id == LibraryBook.id,
                ReaderResourceProgress.user_id == user.id,
                resource_visibility_predicate(context),
            )
            .correlate(LibraryBook)
            .scalar_subquery()
        )
        return [direction(latest_read_at), ascending(LibraryBook.id)]
    return [direction(LibraryBook.updated_at), direction(LibraryBook.id)]


def _resource_summaries(
    db: Session,
    *,
    context: AuthorizationContext,
    user: User,
    book_ids: tuple[str, ...],
) -> dict[str, list[_ResourceSummary]]:
    if not book_ids:
        return {}
    rows = db.execute(
        select(
            LibraryReadableResource.book_id,
            LibraryReadableResource.id.label("resource_id"),
            LibraryReadableResource.media_kind,
            LibraryReadableResourceMetadata.resource_index,
            ReaderResourceProgress.percent,
            ReaderResourceProgress.updated_at.label("progress_updated_at"),
        )
        .select_from(LibraryReadableResource)
        .outerjoin(
            LibraryReadableResourceMetadata,
            LibraryReadableResourceMetadata.resource_id == LibraryReadableResource.id,
        )
        .outerjoin(
            ReaderResourceProgress,
            and_(
                ReaderResourceProgress.resource_id == LibraryReadableResource.id,
                ReaderResourceProgress.user_id == user.id,
            ),
        )
        .where(
            LibraryReadableResource.book_id.in_(book_ids),
            resource_visibility_predicate(context),
        )
        .order_by(
            LibraryReadableResource.book_id.asc(),
            LibraryReadableResourceMetadata.resource_index.asc().nulls_last(),
            LibraryReadableResource.id.asc(),
        )
    ).all()
    result: dict[str, list[_ResourceSummary]] = {book_id: [] for book_id in book_ids}
    for row in rows:
        try:
            media_kind = MediaKind(str(row.media_kind))
        except ValueError:
            continue
        percent = min(100.0, max(0.0, float(row.percent or 0)))
        result[str(row.book_id)].append(
            _ResourceSummary(
                resource_id=str(row.resource_id),
                media_kind=media_kind,
                sort_order=int(row.resource_index or 0),
                percent=percent,
                last_read_at=row.progress_updated_at,
            )
        )
    return result


def _tag_names(
    db: Session,
    *,
    book_ids: tuple[str, ...],
) -> dict[str, list[str]]:
    if not book_ids:
        return {}
    rows = db.execute(
        select(LibraryBookFacet.book_id, LibraryFacet.name)
        .join(LibraryFacet, LibraryFacet.id == LibraryBookFacet.facet_id)
        .where(
            LibraryBookFacet.book_id.in_(book_ids),
            LibraryFacet.kind == "TAG",
        )
        .order_by(
            LibraryBookFacet.book_id.asc(),
            LibraryBookFacet.sort_order.asc(),
            LibraryFacet.name.asc(),
            LibraryFacet.id.asc(),
        )
    ).all()
    result: dict[str, list[str]] = {book_id: [] for book_id in book_ids}
    for row in rows:
        result[str(row.book_id)].append(str(row.name))
    return result


def _reading_summary(
    resources: list[_ResourceSummary],
) -> tuple[str, float, datetime | None]:
    states = [
        ResourceReadingState(
            resource_id=resource.resource_id,
            media_kind=resource.media_kind,
            sort_order=resource.sort_order,
            percent=int(resource.percent),
            last_read_at=resource.last_read_at,
        )
        for resource in resources
    ]
    if not states:
        return "UNREAD", 0.0, None
    status = (
        "FINISHED"
        if completed_for_available_resources(states)
        else (
            "READING"
            if any(resource.percent > 0 for resource in resources)
            else "UNREAD"
        )
    )
    continue_resource_id = choose_continue_resource_id(states)
    progress = next(
        (
            resource.percent
            for resource in resources
            if resource.resource_id == continue_resource_id
        ),
        0.0,
    )
    last_read_at = max(
        (resource.last_read_at for resource in resources if resource.last_read_at),
        default=None,
    )
    return status, progress, last_read_at


def _project_books(
    db: Session,
    *,
    context: AuthorizationContext,
    user: User,
    rows: list[tuple[LibraryBook, LibraryBookMetadata | None]],
    projection: str,
) -> list[dict[str, Any]]:
    book_ids = tuple(str(book.id) for book, _metadata in rows)
    cover_paths = SqlAlchemyBookCoverQueries(db).preferred_paths(book_ids)
    if projection == "full":
        return [
            _book_record(book, metadata, cover_paths.get(str(book.id)))
            for book, metadata in rows
        ]
    resources_by_book = _resource_summaries(
        db,
        context=context,
        user=user,
        book_ids=book_ids,
    )
    tags_by_book = _tag_names(db, book_ids=book_ids)
    projected: list[dict[str, Any]] = []
    media_priority = {"EBOOK": 0, "COMIC": 1, "AUDIOBOOK": 2}
    for book, metadata in rows:
        book_id = str(book.id)
        resources = resources_by_book[book_id]
        status, progress, last_read_at = _reading_summary(resources)
        media_kinds = sorted(
            {resource.media_kind.value for resource in resources},
            key=lambda kind: (media_priority.get(kind, 99), kind),
        )
        title = (
            str(metadata.title).strip()
            if metadata is not None and str(metadata.title).strip()
            else book_id
        )
        author = metadata.author if metadata is not None else None
        effective_cover_path = cover_paths.get(book_id)
        cover_path = effective_cover_path or (
            metadata.cover_path if metadata is not None else None
        )
        common: dict[str, object] = {
            "id": book_id,
            "title": title,
            "author": author,
            "coverPath": cover_path,
            "coverStatus": (
                "READY"
                if effective_cover_path
                else (metadata.cover_status if metadata is not None else "PENDING")
            ),
            "seriesName": metadata.series_name if metadata is not None else None,
            "tags": tags_by_book[book_id],
            "availableMediaKinds": media_kinds,
        }
        if projection == "bookshelf":
            projected.append(
                {
                    **common,
                    "progress": progress,
                }
            )
        else:
            projected.append(
                {
                    **common,
                    "gradient": "",
                    "statusValue": status,
                    "lastReadAt": last_read_at,
                    "importedAt": book.created_at,
                }
            )
    return projected


def list_books(db: Session, user: User, query: BookListQuery) -> BookListResult:
    context = authorization_context(db, user)
    predicates = _predicates(db, context, user, query)
    base = (
        select(LibraryBook, LibraryBookMetadata)
        .select_from(LibraryBook)
        .outerjoin(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(and_(*predicates))
    )
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    page = max(1, query.page)
    page_size = resolve_page_size(query.requested_page_size, total)
    rows = db.execute(
        base.order_by(
            *_order(
                query,
                user=user,
                context=context,
            )
        )
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    normalized_rows = [(book, metadata) for book, metadata in rows]
    total_pages = max(1, (total + page_size - 1) // page_size)
    return BookListResult(
        books=_project_books(
            db,
            context=context,
            user=user,
            rows=normalized_rows,
            projection=query.projection,
        ),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        progress_sort=query.sort == "progress",
    )
