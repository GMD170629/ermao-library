from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    ReaderResourceProgress,
)
from app.models.auth import User
from app.modules.library.application.bookshelf import ListBookshelfItems
from app.modules.library.infrastructure.bookshelf import SqlAlchemyBookshelfItemQueries


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 1,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def test_bookshelf_projection_uses_current_users_continue_resource_progress(
    db_session: Session,
) -> None:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    current_user = User(
        id="bookshelf-user",
        email="bookshelf-user@example.test",
        name="Bookshelf user",
        password_hash="test",
        role="admin",
    )
    other_user = User(
        id="other-bookshelf-user",
        email="other-bookshelf-user@example.test",
        name="Other user",
        password_hash="test",
        role="member",
    )
    book_node = _node("bookshelf-book-node", "bookshelf/", directory=True)
    first_node = _node("bookshelf-resource-node-1", "bookshelf/one.epub")
    second_node = _node("bookshelf-resource-node-2", "bookshelf/two.epub")
    book = LibraryBook(
        library_id="test-library",
        id="bookshelf-book",
        source_node_id=book_node.id,
        created_at=now,
        updated_at=now,
    )
    first_resource = LibraryReadableResource(
        id="bookshelf-resource-1",
        library_id="test-library",
        book_id=book.id,
        source_node_id=first_node.id,
        adapter_id="epub-file",
        adapter_version="1",
        format="EPUB",
        import_state="READY",
        created_at=now,
        updated_at=now,
    )
    second_resource = LibraryReadableResource(
        id="bookshelf-resource-2",
        library_id="test-library",
        book_id=book.id,
        source_node_id=second_node.id,
        adapter_id="epub-file",
        adapter_version="1",
        format="EPUB",
        import_state="READY",
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([current_user, other_user])
    db_session.flush()
    db_session.add_all([book_node, first_node, second_node])
    db_session.flush()
    db_session.add(book)
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book.id,
            title="Bookshelf book",
            normalized_title="bookshelf book",
            author="Author",
        )
    )
    db_session.flush()
    db_session.add_all([first_resource, second_resource])
    db_session.flush()
    db_session.add_all(
        [
            LibraryReadableResourceMetadata(
                resource_id=first_resource.id,
                title="Resource one",
                resource_index=1,
            ),
            LibraryReadableResourceMetadata(
                resource_id=second_resource.id,
                title="Resource two",
                resource_index=2,
            ),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            LibraryResourceAsset(
                id="bookshelf-asset-1",
                library_id="test-library",
                resource_id=first_resource.id,
                source_node_id=first_node.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            ),
            LibraryResourceAsset(
                id="bookshelf-asset-2",
                library_id="test-library",
                resource_id=second_resource.id,
                source_node_id=second_node.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            ),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            ReaderResourceProgress(
                id="bookshelf-progress-current-1",
                user_id=current_user.id,
                resource_id=first_resource.id,
                reader_type="reflowable",
                position="first",
                percent=35.5,
                extra="{}",
                progressed_at=now,
                created_at=now,
                updated_at=now,
            ),
            ReaderResourceProgress(
                id="bookshelf-progress-current-2",
                user_id=current_user.id,
                resource_id=second_resource.id,
                reader_type="reflowable",
                position="second",
                percent=100,
                extra="{}",
                progressed_at=now + timedelta(minutes=1),
                created_at=now,
                updated_at=now + timedelta(minutes=1),
            ),
            ReaderResourceProgress(
                id="bookshelf-progress-other",
                user_id=other_user.id,
                resource_id=first_resource.id,
                reader_type="reflowable",
                position="other",
                percent=88,
                extra="{}",
                progressed_at=now,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    db_session.commit()

    context = AuthorizationContext(
        user_id=current_user.id,
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        library_ids=(),
        authz_version=1,
    )
    result = ListBookshelfItems(SqlAlchemyBookshelfItemQueries(db_session)).execute(
        context=context, book_ids=(book.id,)
    )

    assert len(result) == 1
    assert result[0].id == book.id
    assert result[0].progress == 35.5
