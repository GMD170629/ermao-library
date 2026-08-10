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
        work_ids: tuple[str, ...],
    ) -> tuple[BookshelfItemSummary, ...]:
        self.received_ids = work_ids
        return tuple(
            BookshelfItemSummary(
                id=work_id,
                title=work_id,
                author="Author",
                cover_path=None,
                updated_at=datetime(2026, 8, 10, tzinfo=UTC),
                available_media_kinds=("EBOOK",),
                progress=25,
            )
            for work_id in work_ids
        )


def test_list_bookshelf_items_normalizes_ids_without_reordering() -> None:
    queries = FakeBookshelfItemQueries()
    context = AuthorizationContext(
        user_id="user-1",
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        monitor_folder_ids=(),
        authz_version=1,
    )

    result = ListBookshelfItems(queries).execute(
        context=context,
        work_ids=(" work-b ", "work-a", "work-b", ""),
    )

    assert queries.received_ids == ("work-b", "work-a")
    assert [item.id for item in result] == ["work-b", "work-a"]
