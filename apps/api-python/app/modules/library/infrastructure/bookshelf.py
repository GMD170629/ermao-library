"""SQLAlchemy adapter for the user-scoped bookshelf projection."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    book_visibility_predicate,
    resource_visibility_predicate,
)
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
)
from app.modules.library.application.bookshelf import (
    BookshelfItemQueryPort,
    BookshelfItemSummary,
)
from app.modules.library.infrastructure.book_covers import effective_book_cover_path
from app.modules.reader.public import (
    ReaderV5LibraryPresentationQueryPort,
    ResourceReadingState,
    choose_continue_resource_id,
)


class SqlAlchemyBookshelfItemQueries(BookshelfItemQueryPort):
    def __init__(
        self,
        db: Session,
        *,
        reader_queries: ReaderV5LibraryPresentationQueryPort,
    ) -> None:
        self._db = db
        self._reader_queries = reader_queries

    def list_items(
        self,
        *,
        context: AuthorizationContext,
        book_ids: tuple[str, ...],
    ) -> tuple[BookshelfItemSummary, ...]:
        book_rows = self._db.execute(
            select(
                LibraryBook.id,
                LibraryBook.updated_at,
                LibraryBookMetadata.title,
                LibraryBookMetadata.author,
                LibraryBookMetadata.cover_path,
                effective_book_cover_path(
                    LibraryBook.id,
                    LibraryBookMetadata.cover_path,
                    LibraryBookMetadata.cover_status,
                ).label("effective_cover_path"),
            )
            .select_from(LibraryBook)
            .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
            .where(
                LibraryBook.id.in_(book_ids),
                LibraryBook.visibility_state == "VISIBLE",
                book_visibility_predicate(context),
            )
        ).all()
        book_by_id = {str(row.id): row for row in book_rows}
        visible_book_ids = tuple(
            book_id for book_id in book_ids if book_id in book_by_id
        )
        if not visible_book_ids:
            return ()
        rows = self._db.execute(
            select(
                LibraryReadableResource.book_id,
                LibraryReadableResource.id.label("resource_id"),
                LibraryReadableResourceMetadata.resource_index,
            )
            .select_from(LibraryReadableResource)
            .join(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .where(
                LibraryReadableResource.book_id.in_(visible_book_ids),
                resource_visibility_predicate(context),
            )
            .order_by(
                LibraryReadableResource.book_id.asc(),
                LibraryReadableResourceMetadata.resource_index.asc(),
                LibraryReadableResource.id.asc(),
            )
        ).all()
        progress_by_resource = self._reader_queries.list_presentations(
            user_id=context.user_id,
            resource_ids=[str(row.resource_id) for row in rows],
        )
        states_by_book: dict[str, list[ResourceReadingState]] = defaultdict(list)
        percent_by_resource: dict[str, float] = {}
        for row in rows:
            book_id = str(row.book_id)
            resource_id = str(row.resource_id)
            progress = progress_by_resource.get(resource_id)
            percent = min(
                100.0,
                max(0.0, float(progress.display_percent if progress else 0)),
            )
            percent_by_resource[resource_id] = percent
            states_by_book[book_id].append(
                ResourceReadingState(
                    resource_id=resource_id,
                    sort_order=int(row.resource_index or 0),
                    percent=int(percent),
                    last_read_at=progress.updated_at if progress else None,
                )
            )

        summaries: list[BookshelfItemSummary] = []
        for book_id in visible_book_ids:
            book = book_by_id[book_id]
            continue_resource_id = choose_continue_resource_id(states_by_book[book_id])
            summaries.append(
                BookshelfItemSummary(
                    id=book_id,
                    title=str(book.title),
                    author=str(book.author or "未知作者"),
                    cover_path=book.effective_cover_path or book.cover_path,
                    updated_at=book.updated_at,
                    progress=(
                        percent_by_resource.get(continue_resource_id, 0.0)
                        if continue_resource_id is not None
                        else 0.0
                    ),
                )
            )
        return tuple(summaries)
