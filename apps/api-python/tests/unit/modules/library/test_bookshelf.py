from __future__ import annotations

from datetime import UTC, datetime

from app.core.authorization import AuthorizationContext
from app.modules.library.application.bookshelf import (
    BookshelfItemQueryPort,
    BookshelfItemSummary,
    ListBookshelfItems,
)


class FakeBookshelfItemQueries(BookshelfItemQueryPort):
    def __init__(self) -> None:
        self.received_ids: tuple[str, ...] = ()

    def list_items(
        self,
        *,
        context: AuthorizationContext,
        book_ids: tuple[str, ...],
    ) -> tuple[BookshelfItemSummary, ...]:
        self.received_ids = book_ids
        return tuple(
            BookshelfItemSummary(
                id=book_id,
                title=book_id,
                author="Author",
                cover_path=None,
                updated_at=datetime(2026, 8, 10, tzinfo=UTC),
                available_media_kinds=("EBOOK",),
                progress=25,
            )
            for book_id in book_ids
        )


def test_list_bookshelf_items_normalizes_book_ids_without_reordering() -> None:
    queries = FakeBookshelfItemQueries()
    context = AuthorizationContext(
        user_id="user-1",
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        library_ids=(),
        authz_version=1,
    )

    result = ListBookshelfItems(queries).execute(
        context=context,
        book_ids=(" book-b ", "book-a", "book-b", ""),
    )

    assert queries.received_ids == ("book-b", "book-a")
    assert [item.id for item in result] == ["book-b", "book-a"]
