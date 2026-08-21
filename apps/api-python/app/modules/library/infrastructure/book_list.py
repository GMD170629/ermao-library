"""Resource-authorized ORM book listing."""

from __future__ import annotations

from typing import cast

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
    ReaderResourceProgress,
)
from app.models.auth import User
from app.modules.library.application.book_list import (
    BookListQuery,
    BookListResult,
    resolve_page_size,
)
from app.modules.library.infrastructure.books import _book_record
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    resolve_library_roots,
)


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
        if normalized == "READING":
            predicates.append(started)
        elif normalized == "UNREAD":
            predicates.append(~started)
        elif normalized == "FINISHED":
            predicates.append(_resource_exists(book_id=LibraryBook.id))
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
        predicates.append(
            or_(
                LibraryBookMetadata.cover_path.is_(None),
                func.trim(func.coalesce(LibraryBookMetadata.cover_path, "")) == "",
                LibraryBookMetadata.cover_status != "READY",
            )
        )
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


def _order(query: BookListQuery) -> list[ColumnElement[object]]:
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
    return [direction(LibraryBook.updated_at), direction(LibraryBook.id)]


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
        base.order_by(*_order(query)).limit(page_size).offset((page - 1) * page_size)
    ).all()
    return BookListResult(
        books=[_book_record(book, metadata) for book, metadata in rows],
        total=total,
        page=page,
        page_size=page_size,
        progress_sort=query.sort == "progress",
    )
