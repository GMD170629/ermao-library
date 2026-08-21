from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.auth import User, UserLibraryAccess
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryBookFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    ReaderResourceProgress,
)
from app.modules.library.application.bookshelf import ListBookshelfItems
from app.modules.library.application.book_list import BookListQuery
from app.modules.library.infrastructure.bookshelf import SqlAlchemyBookshelfItemQueries
from app.modules.library.infrastructure.dashboard import (
    continue_reading_progress,
    recent_books,
)
from app.modules.library.infrastructure.groupings import (
    SqlAlchemyLibraryGroupingQueries,
)
from app.modules.library.infrastructure.book_list import list_books

_ResultT = TypeVar("_ResultT")


def _seed_manual_library(db: Session, *, book_count: int) -> None:
    now = datetime.now(UTC)
    chunk_size = 500
    for start in range(0, book_count, chunk_size):
        stop = min(book_count, start + chunk_size)
        db.execute(
            insert(LibrarySourceNode),
            [
                {
                    "id": f"scale-book-node-{index:06d}",
                    "library_id": "test-library",
                    "relative_path": f"scale-book-{index:06d}/",
                    "path_key": "v1:" + f"{index:064x}",
                    "name": f"scale-book-{index:06d}",
                    "physical_kind": "DIRECTORY",
                    "observed_size_bytes": None,
                    "observed_mtime_ns": 1,
                    "observed_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db.execute(
            insert(LibrarySourceNode),
            [
                {
                    "id": f"scale-resource-node-{index:06d}",
                    "library_id": "test-library",
                    "relative_path": f"scale-book-{index:06d}.epub",
                    "path_key": "v1:" + f"{book_count + index:064x}",
                    "name": f"scale-book-{index:06d}.epub",
                    "physical_kind": "REGULAR_FILE",
                    "observed_size_bytes": 10,
                    "observed_mtime_ns": 1,
                    "observed_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db.execute(
            insert(LibraryBook),
            [
                {
                    "id": f"scale-book-{index:06d}",
                    "library_id": "test-library",
                    "source_node_id": f"scale-book-node-{index:06d}",
                    "visibility_state": "VISIBLE",
                    "curation_state": "PENDING",
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db.execute(
            insert(LibraryBookMetadata),
            [
                {
                    "book_id": f"scale-book-{index:06d}",
                    "title": f"Scale book {index}",
                    "normalized_title": f"scalebook{index}",
                    "author": "Scale author",
                    "normalized_author": "scaleauthor",
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db.execute(
            insert(LibraryReadableResource),
            [
                {
                    "id": f"scale-resource-{index:06d}",
                    "library_id": "test-library",
                    "book_id": f"scale-book-{index:06d}",
                    "source_node_id": f"scale-resource-node-{index:06d}",
                    "adapter_id": "epub-file",
                    "adapter_version": "1",
                    "media_kind": "EBOOK",
                    "format": "EPUB",
                    "enablement_state": "ENABLED",
                    "import_state": "READY",
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db.execute(
            insert(LibraryReadableResourceMetadata),
            [
                {
                    "resource_id": f"scale-resource-{index:06d}",
                    "title": f"Scale book {index}",
                    "resource_index": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
        db.execute(
            insert(LibraryResourceAsset),
            [
                {
                    "id": f"scale-asset-{index:06d}",
                    "library_id": "test-library",
                    "resource_id": f"scale-resource-{index:06d}",
                    "source_node_id": f"scale-resource-node-{index:06d}",
                    "source_node_physical_kind": "REGULAR_FILE",
                    "role": "PRIMARY",
                    "import_state": "READY",
                    "sequence_index": 0,
                    "sort_key": "0",
                    "created_at": now,
                    "updated_at": now,
                }
                for index in range(start, stop)
            ],
        )
    db.commit()


def _sqlite_vm_steps(
    db: Session, operation: Callable[[], _ResultT]
) -> tuple[_ResultT, int]:
    driver_connection = db.connection().connection.driver_connection
    callback_count = 0

    def count_steps() -> int:
        nonlocal callback_count
        callback_count += 1
        return 0

    step_interval = 1_000
    driver_connection.set_progress_handler(count_steps, step_interval)
    try:
        result = operation()
    finally:
        driver_connection.set_progress_handler(None, 0)
    return result, callback_count * step_interval


def test_member_recent_import_listing_has_bounded_query_work(
    db_session: Session,
) -> None:
    user = User(
        id="scale-member",
        email="scale-member@example.test",
        name="Scale member",
        password_hash="test",
        role="member",
        can_view_manual_imports=True,
    )
    db_session.add_all(
        [
            user,
            UserLibraryAccess(user_id=user.id, library_id="test-library"),
        ]
    )
    _seed_manual_library(db_session, book_count=2_000)

    result, vm_steps = _sqlite_vm_steps(
        db_session,
        lambda: list_books(
            db_session,
            user,
            BookListQuery(
                page=1,
                requested_page_size=50,
                visibility="active",
                sort="recent_import",
                sort_direction="desc",
            ),
        ),
    )

    assert result.total == 2_000
    assert len(result.books) == 50
    assert vm_steps < 1_000_000

    context = AuthorizationContext(
        user_id=user.id,
        is_admin=False,
        can_manage_system=False,
        can_view_manual_imports=True,
        library_ids=("test-library",),
        authz_version=1,
    )
    recent, recent_vm_steps = _sqlite_vm_steps(
        db_session,
        lambda: recent_books(db_session, context, limit=10),
    )

    assert len(recent) == 10
    assert recent_vm_steps < 500_000

    select_count = 0

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        views = ListBookshelfItems(SqlAlchemyBookshelfItemQueries(db_session)).execute(
            context=context,
            book_ids=tuple(str(book["id"]) for book in recent),
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert len(views) == 10
    assert select_count == 2

    filtered_result, filtered_vm_steps = _sqlite_vm_steps(
        db_session,
        lambda: list_books(
            db_session,
            user,
            BookListQuery(
                page=1,
                requested_page_size=50,
                visibility="active",
                sort="recent_import",
                sort_direction="desc",
                type_filter="EPUB",
                media_kinds=("EBOOK",),
            ),
        ),
    )

    assert filtered_result.total == 2_000
    assert len(filtered_result.books) == 50
    assert filtered_vm_steps < 1_500_000

    now = datetime.now(UTC)
    author_count = 100
    db_session.execute(
        insert(LibraryFacet),
        [
            {
                "id": f"scale-author-{index:03d}",
                "kind": "AUTHOR",
                "name": f"Scale author {index:03d}",
                "normalized_name": f"scaleauthor{index:03d}",
                "aliases": "[]",
                "created_at": now,
                "updated_at": now,
            }
            for index in range(author_count)
        ],
    )
    db_session.execute(
        insert(LibraryBookFacet),
        [
            {
                "facet_id": f"scale-author-{index % author_count:03d}",
                "book_id": f"scale-book-{index:06d}",
                "sort_order": 0,
                "created_at": now,
            }
            for index in range(2_000)
        ],
    )
    db_session.commit()
    grouping_page, grouping_vm_steps = _sqlite_vm_steps(
        db_session,
        lambda: SqlAlchemyLibraryGroupingQueries(db_session).list_groupings(
            kind="AUTHOR",
            context=context,
            search="",
            page=1,
            page_size=48,
        ),
    )

    assert grouping_page.total == author_count
    assert len(grouping_page.groups) == 48
    assert grouping_vm_steps < 2_000_000


def test_continue_reading_does_not_scan_every_visible_resource(
    db_session: Session,
) -> None:
    user = User(
        id="scale-reader",
        email="scale-reader@example.test",
        name="Scale reader",
        password_hash="test",
        role="admin",
    )
    db_session.add(user)
    _seed_manual_library(db_session, book_count=2_000)
    now = datetime.now(UTC)
    db_session.add(
        ReaderResourceProgress(
            id="scale-reader-progress",
            user_id=user.id,
            resource_id="scale-resource-001999",
            reader_type="epub",
            position="1",
            percent=40,
            extra="{}",
            progressed_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    db_session.commit()
    context = AuthorizationContext(
        user_id=user.id,
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        library_ids=(),
        authz_version=1,
    )

    progress, vm_steps = _sqlite_vm_steps(
        db_session,
        lambda: continue_reading_progress(db_session, context, user.id),
    )

    assert progress is not None
    assert progress["bookId"] == "scale-book-001999"
    assert progress["resourceId"] == "scale-resource-001999"
    assert vm_steps < 75_000
