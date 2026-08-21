"""SQLAlchemy adapter for the user-scoped bookshelf projection."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import and_, select
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
    ReaderResourceProgress,
)
from app.modules.library.application.bookshelf import (
    BookshelfItemQueryPort,
    BookshelfItemSummary,
)
from app.modules.reader.public import (
    MediaKind,
    ResourceReadingState,
    choose_continue_resource_id,
)

_MEDIA_KIND_ORDER = {"EBOOK": 0, "COMIC": 1, "AUDIOBOOK": 2}


class SqlAlchemyBookshelfItemQueries(BookshelfItemQueryPort):
    def __init__(self, db: Session) -> None:
        self._db = db

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
                LibraryReadableResource.media_kind,
                LibraryReadableResource.id.label("resource_id"),
                LibraryReadableResourceMetadata.resource_index,
                ReaderResourceProgress.percent,
                ReaderResourceProgress.updated_at.label("progress_updated_at"),
            )
            .select_from(LibraryReadableResource)
            .join(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .outerjoin(
                ReaderResourceProgress,
                and_(
                    ReaderResourceProgress.resource_id == LibraryReadableResource.id,
                    ReaderResourceProgress.user_id == context.user_id,
                ),
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
        media_kinds_by_book: dict[str, set[str]] = defaultdict(set)
        states_by_book: dict[str, list[ResourceReadingState]] = defaultdict(list)
        percent_by_resource: dict[str, float] = {}
        for row in rows:
            book_id = str(row.book_id)
            media_kind = MediaKind(str(row.media_kind))
            media_kinds_by_book[book_id].add(media_kind.value)
            percent = min(100.0, max(0.0, float(row.percent or 0)))
            resource_id = str(row.resource_id)
            percent_by_resource[resource_id] = percent
            states_by_book[book_id].append(
                ResourceReadingState(
                    resource_id=resource_id,
                    media_kind=media_kind,
                    sort_order=int(row.resource_index or 0),
                    percent=int(percent),
                    last_read_at=row.progress_updated_at,
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
                    cover_path=book.cover_path,
                    updated_at=book.updated_at,
                    available_media_kinds=tuple(
                        sorted(
                            media_kinds_by_book[book_id],
                            key=lambda kind: _MEDIA_KIND_ORDER.get(kind, 99),
                        )
                    ),
                    progress=(
                        percent_by_resource.get(continue_resource_id, 0.0)
                        if continue_resource_id is not None
                        else 0.0
                    ),
                )
            )
        return tuple(summaries)
