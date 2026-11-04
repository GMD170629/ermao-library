"""Resource-authorized ORM book listing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    ColumnElement,
    Select,
    exists,
    false,
    func,
    select,
    true,
)
from sqlalchemy.orm import InstrumentedAttribute, Session, load_only

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
)
from app.models.auth import User
from app.modules.library.application.book_list import (
    BookListQuery,
    BookListResult,
    resolve_page_size,
)
from app.modules.library.infrastructure.book_covers import (
    effective_book_cover_exists,
    effective_book_cover_path,
)
from app.modules.library.infrastructure.book_search import matching_search_book_ids
from app.modules.library.infrastructure.books import (
    _book_record,
    book_ids_statement,
    resource_import_summaries,
    selected_book_ids_statement,
)
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    reading_status_predicate,
    resolve_library_roots,
)
from app.modules.reader.public import (
    ReaderV5LibraryPresentationQueryPort,
    ResourceReadingState,
    choose_continue_resource_id,
    reading_status_for_available_resources,
)


def _resource_exists(
    *,
    book_id: object,
) -> ColumnElement[bool]:
    """Match readable resources belonging to an already-authorized Book.

    ``LibraryReadableResource`` has a composite foreign key from ``bookId`` and
    ``libraryId`` to ``LibraryBook``. The enclosing Book predicate therefore
    owns both the authorization scope and the library relationship. Keeping
    the correlated predicate on ``bookId`` lets SQLite use the dedicated
    ``LibraryReadableResource_bookId_idx`` instead of rescanning every resource
    through the separate library index for each Book.
    """
    return exists(
        select(LibraryReadableResource.id).where(
            LibraryReadableResource.book_id == book_id,
            LibraryReadableResource.enablement_state == "ENABLED",
            LibraryReadableResource.import_state == "READY",
        )
    )


def _predicates(
    db: Session,
    context: AuthorizationContext,
    user: User,
    query: BookListQuery,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
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
    # A pattern containing only '%' matches every row, including absent metadata
    # through the existing COALESCE branches. Other patterns need real metadata.
    if term and term.strip("%"):
        predicates.append(
            LibraryBook.id.in_(matching_search_book_ids(term))
        )
    if query.status:
        predicates.append(
            reading_status_predicate(
                context, user.id, query.status, reader_queries=reader_queries
            )
        )
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
            reader_queries=reader_queries,
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
    reader_queries: ReaderV5LibraryPresentationQueryPort,
    reverse: bool = False,
) -> list[ColumnElement[object]]:
    descending = (query.sort_direction or "").lower() == "desc" or (
        not query.sort_direction
        and query.sort in {"updated", "recent_read", "recent_import", "progress"}
    )

    if reverse:
        descending = not descending

    def direction(column: object) -> ColumnElement[object]:
        expression = cast(ColumnElement[object], column)
        return expression.desc() if descending else expression.asc()

    def ascending(column: object) -> ColumnElement[object]:
        expression = cast(ColumnElement[object], column)
        return expression.desc() if reverse else expression.asc()

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
        latest_read_at = reader_queries.latest_read_at_expression(
            context=context,
            user_id=user.id,
            book_id_expression=LibraryBook.id,
        )
        return [
            direction(cast(ColumnElement[object], latest_read_at)),
            ascending(LibraryBook.id),
        ]
    if query.sort == "recent_import":
        return [direction(LibraryBook.created_at), direction(LibraryBook.id)]
    return [direction(LibraryBook.updated_at), direction(LibraryBook.id)]


def _resource_summaries(
    db: Session,
    *,
    context: AuthorizationContext,
    user: User,
    book_ids: tuple[str, ...],
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> dict[str, list[ResourceReadingState]]:
    if not book_ids:
        return {}
    rows = db.execute(
        select(
            LibraryReadableResource.book_id,
            LibraryReadableResource.id.label("resource_id"),
            LibraryReadableResourceMetadata.resource_index,
        )
        .select_from(LibraryReadableResource)
        .outerjoin(
            LibraryReadableResourceMetadata,
            LibraryReadableResourceMetadata.resource_id == LibraryReadableResource.id,
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
    resource_ids = [str(row.resource_id) for row in rows]
    reading_states = reader_queries.list_reading_states(
        user_id=user.id,
        resource_ids=resource_ids,
    )
    result: dict[str, list[ResourceReadingState]] = {
        book_id: [] for book_id in book_ids
    }
    for row in rows:
        result[str(row.book_id)].append(
            replace(
                reading_states[str(row.resource_id)],
                sort_order=int(row.resource_index or 0),
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
    resources: list[ResourceReadingState],
) -> tuple[str, float, datetime | None]:
    if not resources:
        return "UNREAD", 0.0, None
    status = reading_status_for_available_resources(resources)
    continue_resource_id = choose_continue_resource_id(resources)
    progress = next(
        (
            resource.display_percent
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
    cover_paths: Mapping[str, str],
    projection: str,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> list[dict[str, Any]]:
    book_ids = tuple(str(book.id) for book, _metadata in rows)
    import_summaries = resource_import_summaries(db, book_ids)
    if projection == "import-status":
        return [
            {
                "id": book.id,
                "libraryId": book.library_id,
                "metadataState": metadata.metadata_state
                if metadata is not None
                else "WAITING_IMPORT",
                "resourceImportSummary": import_summaries[str(book.id)].as_record(),
            }
            for book, metadata in rows
        ]
    if projection == "full":
        return [
            _book_record(
                book,
                metadata,
                cover_paths.get(str(book.id)),
                import_summaries[str(book.id)],
            )
            for book, metadata in rows
        ]
    resources_by_book = _resource_summaries(
        db,
        context=context,
        user=user,
        book_ids=book_ids,
        reader_queries=reader_queries,
    )
    tags_by_book = (
        _tag_names(db, book_ids=book_ids) if projection == "management" else {}
    )
    projected: list[dict[str, Any]] = []
    for book, metadata in rows:
        book_id = str(book.id)
        resources = resources_by_book[book_id]
        status, progress, last_read_at = _reading_summary(resources)
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
            "coverStatus": "READY"
            if effective_cover_path
            else (metadata.cover_status if metadata is not None else "PENDING"),
            "resourceImportSummary": import_summaries[book_id].as_record(),
        }
        if projection in {"bookshelf", "search"}:
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
                    "seriesName": metadata.series_name
                    if metadata is not None
                    else None,
                    "tags": tags_by_book[book_id],
                    "gradient": "",
                    "statusValue": status,
                    "lastReadAt": last_read_at,
                    "importedAt": book.created_at,
                }
            )
    return projected


def list_books(
    db: Session,
    user: User,
    query: BookListQuery,
    *,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> BookListResult:
    context = authorization_context(db, user)
    predicates = _predicates(db, context, user, query, reader_queries)
    identities = book_ids_statement(predicates)
    page = max(1, query.page)
    complete_match_ids: tuple[str, ...] = ()
    if query.sort == "title" or (
        query.sort in {"recent_import", "updated"}
        and (query.search or query.keyword or query.filter_expression is not None)
    ):
        # Count and page the same authorized set, retaining only required sort
        # keys. Display metadata is read after selecting the page.
        date_sort = query.sort != "title"
        if date_sort:
            identities = identities.add_columns((
                LibraryBook.created_at if query.sort == "recent_import" else LibraryBook.updated_at
            ).label("ordered_at"))
        matches = identities.cte("matching_books").prefix_with("MATERIALIZED")
        totals = select(func.count().label("total")).select_from(matches).cte("matching_total")
        limit = resolve_page_size(query.requested_page_size, 0) if query.requested_page_size is not None else None
        if date_sort:
            descending = (query.sort_direction or "desc").lower() == "desc"
            page_query = select(matches.c.id).order_by(
                matches.c.ordered_at.desc() if descending else matches.c.ordered_at.asc(),
                matches.c.id.desc() if descending else matches.c.id.asc(),
            )
        else:
            titles = select(LibraryBookMetadata.book_id, LibraryBookMetadata.title).where(
                exists(select(matches.c.id).where(matches.c.id == LibraryBookMetadata.book_id)),
                select(totals.c.total).scalar_subquery() > limit if limit is not None else false(),
            ).cte("matching_titles").prefix_with("MATERIALIZED")
            title_order = titles.c.title.desc() if (query.sort_direction or "").lower() == "desc" else titles.c.title.asc()
            page_query = select(matches.c.id).select_from(
                matches.outerjoin(titles, titles.c.book_id == matches.c.id)
            ).order_by(title_order, matches.c.id.asc())
        page_ids = (
            page_query
            .limit(limit)
            .offset((page - 1) * (limit if limit is not None else select(totals.c.total).scalar_subquery()))
            .cte("matching_page")
        )
        count_rows = db.execute(select(totals.c.total, page_ids.c.id).select_from(
            totals.outerjoin(page_ids, true())
        )).all()
        total = int(count_rows[0].total)
        complete_match_ids = tuple(str(row.id) for row in count_rows if row.id is not None)
    elif query.search and page == 1 and query.requested_page_size is not None:
        # Reuse counting to return only a complete, page-sized identity set.
        # A selective search must not walk the full date index to find its
        # oldest matching book. Large searches still return only the count.
        matches = identities.cte("matching_books").prefix_with("MATERIALIZED")
        totals = select(func.count().label("total")).select_from(matches).cte("matching_total")
        count_rows = db.execute(
            select(totals.c.total, matches.c.id)
            .select_from(totals.outerjoin(matches, totals.c.total <= resolve_page_size(query.requested_page_size, 0)))
        ).all()
        total = int(count_rows[0].total)
        complete_match_ids = tuple(str(row.id) for row in count_rows if row.id is not None)
    else:
        total = int(db.scalar(select(func.count()).select_from(identities.subquery())) or 0)
    page_size = resolve_page_size(query.requested_page_size, total)
    offset = (page - 1) * page_size
    if offset >= total:
        return BookListResult(
            books=[],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=max(1, (total + page_size - 1) // page_size),
            progress_sort=query.sort == "progress",
        )
    order = _order(query, user=user, context=context, reader_queries=reader_queries)
    # The exact count is already needed for the response. Traverse from the
    # nearer end so a final page never scans every preceding book identity.
    page_limit = min(page_size, total - offset)
    reverse = offset > total // 2
    page_order = (
        _order(query, user=user, context=context, reader_queries=reader_queries, reverse=True)
        if reverse else order
    )
    page_offset = total - offset - page_limit if reverse else offset
    selected_page = (
        selected_book_ids_statement(complete_match_ids, predicates)
        if complete_match_ids else
        book_ids_statement(predicates, page_order)
        .limit(page_limit)
        .offset(page_offset)
        .subquery()
    )
    row_query: Select[Any] = (
        select(LibraryBook, LibraryBookMetadata)
        .select_from(selected_page)
        .join(LibraryBook, LibraryBook.id == selected_page.c.id)
        .outerjoin(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .order_by(*order)
    )
    if query.projection != "import-status":
        row_query = row_query.add_columns(
            effective_book_cover_path(
                LibraryBook.id,
                LibraryBookMetadata.cover_path,
                LibraryBookMetadata.cover_status,
            ).label("effective_cover_path")
        )
    metadata_columns: list[InstrumentedAttribute[Any]] = [
        LibraryBookMetadata.book_id,
        LibraryBookMetadata.title,
        LibraryBookMetadata.author,
        LibraryBookMetadata.cover_path,
        LibraryBookMetadata.cover_status,
    ]
    if query.projection == "import-status":
        metadata_columns = [
            LibraryBookMetadata.book_id,
            LibraryBookMetadata.metadata_state,
        ]
    elif query.projection == "full":
        metadata_columns += [
            LibraryBookMetadata.description,
            LibraryBookMetadata.generated_fields,
            LibraryBookMetadata.protected_fields,
            LibraryBookMetadata.series_name,
            LibraryBookMetadata.series_index,
            LibraryBookMetadata.metadata_quality,
            LibraryBookMetadata.metadata_state,
            LibraryBookMetadata.metadata_pending,
            LibraryBookMetadata.publication_status,
            LibraryBookMetadata.tracking_status,
        ]
    elif query.projection == "management":
        metadata_columns += [LibraryBookMetadata.series_name]
    row_query = row_query.options(load_only(*metadata_columns, raiseload=True))
    if query.projection != "full":
        book_columns: list[InstrumentedAttribute[Any]] = [LibraryBook.id]
        if query.projection == "import-status":
            book_columns.append(LibraryBook.library_id)
        if query.projection == "management":
            book_columns.append(LibraryBook.created_at)
        row_query = row_query.options(load_only(*book_columns, raiseload=True))
    rows = db.execute(row_query).all()
    normalized_rows = [(row[0], row[1]) for row in rows]
    cover_paths = (
        {str(row[0].id): str(row[2]) for row in rows if row[2]}
        if query.projection != "import-status"
        else {}
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return BookListResult(
        books=_project_books(
            db,
            context=context,
            user=user,
            rows=normalized_rows,
            cover_paths=cover_paths,
            projection=query.projection,
            reader_queries=reader_queries,
        ),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        progress_sort=query.sort == "progress",
    )
