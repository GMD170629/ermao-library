from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.auth import hash_password
from app.core.authorization import (
    can_access_asset,
    can_access_book,
    can_access_library,
    can_access_resource,
)
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    ReaderResourceProgress,
)
from app.models.auth import User, UserLibraryAccess, UserPreference
from app.models.shelf import Shelf, ShelfBook

PASSWORD = "starshipnas"


def _node(
    node_id: str,
    path: str,
    library_id: str,
    *,
    directory: bool = False,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id=library_id,
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 10,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _add_book_graph(
    db_session,
    *,
    book_id: str,
    library_id: str,
    with_resource: bool = True,
) -> tuple[LibraryBook, LibraryReadableResource | None, LibraryResourceAsset | None]:
    book_node = _node(f"{book_id}-node", f"{book_id}/", library_id, directory=True)
    book = LibraryBook(
        id=book_id,
        library_id=library_id,
        source_node_id=book_node.id,
    )
    db_session.add_all(
        [
            book_node,
            book,
            LibraryBookMetadata(
                book_id=book_id,
                title=book_id,
                normalized_title=book_id,
                author="Author",
            ),
        ]
    )
    if not with_resource:
        return book, None, None

    resource_node = _node(f"{book_id}-resource-node", f"{book_id}.epub", library_id)
    resource = LibraryReadableResource(
        id=f"{book_id}-resource",
        library_id=library_id,
        book_id=book_id,
        source_node_id=resource_node.id,
        adapter_id="epub-file",
        adapter_version="1",
        media_kind="EBOOK",
        format="EPUB",
        import_state="READY",
    )
    asset = LibraryResourceAsset(
        id=f"{book_id}-asset",
        library_id=library_id,
        resource_id=resource.id,
        source_node_id=resource_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
    )
    db_session.add_all(
        [
            resource_node,
            resource,
            LibraryReadableResourceMetadata(resource_id=resource.id, title=book_id),
            asset,
        ]
    )
    return book, resource, asset


def _seed_scoped_graph(db_session) -> tuple[User, User, LibraryReadableResource, LibraryResourceAsset]:
    folder_a = Library(
        id="folder-a",
        name="A Library",
        root_path="/library/folder-a",
        organization_mode="FLAT",
    )
    folder_b = Library(
        id="folder-b",
        name="B Library",
        root_path="/library/folder-b",
        organization_mode="FLAT",
    )
    member = User(
        id="scope-member",
        email="scope-member@example.com",
        name="Scope member",
        password_hash=hash_password(PASSWORD),
        role="member",
    )
    admin = User(
        id="scope-admin",
        email="scope-admin@example.com",
        name="Scope admin",
        password_hash=hash_password(PASSWORD),
        role="admin",
    )
    _add_book_graph(db_session, book_id="book-a", library_id=folder_a.id)
    _add_book_graph(db_session, book_id="book-b", library_id=folder_b.id)
    db_session.add_all(
        [
            folder_a,
            folder_b,
            member,
            admin,
            UserLibraryAccess(user_id=member.id, library_id=folder_a.id),
        ]
    )
    db_session.flush()
    resource = db_session.get(LibraryReadableResource, "book-a-resource")
    asset = db_session.get(LibraryResourceAsset, "book-a-asset")
    assert resource is not None and asset is not None
    return member, admin, resource, asset


def test_library_scope_controls_book_resource_and_asset_access(db_session) -> None:
    member, admin, resource, asset = _seed_scoped_graph(db_session)
    db_session.commit()

    assert can_access_library(db_session, admin, "folder-a")
    assert can_access_library(db_session, admin, "folder-b")
    assert can_access_library(db_session, member, "folder-a")
    assert not can_access_library(db_session, member, "folder-b")
    assert can_access_book(db_session, member, "book-a")
    assert not can_access_book(db_session, member, "book-b")
    assert can_access_resource(db_session, member, resource.id)
    assert not can_access_resource(db_session, member, "book-b-resource")
    assert can_access_asset(db_session, member, asset.id)
    assert not can_access_asset(db_session, member, "book-b-asset")


def test_member_can_access_empty_book_without_readable_resources(db_session) -> None:
    library = Library(
        id="empty-library",
        name="Empty library",
        root_path="/library/empty",
        organization_mode="FLAT",
    )
    member = User(
        id="empty-book-member",
        email="empty-book@example.com",
        name="Empty book member",
        password_hash=hash_password(PASSWORD),
        role="member",
    )
    book, _, _ = _add_book_graph(
        db_session, book_id="empty-book", library_id=library.id, with_resource=False
    )
    db_session.add_all(
        [library, member, UserLibraryAccess(user_id=member.id, library_id=library.id)]
    )
    db_session.commit()

    assert can_access_book(db_session, member, book.id)
    assert not can_access_book(db_session, member, "missing-book")


def test_deleting_a_book_cascades_its_resource_and_asset_graph(db_session) -> None:
    book, resource, asset = _add_book_graph(
        db_session, book_id="cascade-book", library_id="test-library"
    )
    assert resource is not None and asset is not None
    db_session.commit()

    db_session.delete(book)
    db_session.commit()

    assert db_session.get(LibraryBook, book.id) is None
    assert db_session.get(LibraryReadableResource, resource.id) is None
    assert db_session.get(LibraryResourceAsset, asset.id) is None


def test_preferences_progress_bookmarks_and_shelves_are_user_isolated(
    db_session,
) -> None:
    first = User(
        id="first-reader",
        email="first-reader@example.com",
        name="First reader",
        password_hash=hash_password(PASSWORD),
        role="member",
    )
    second = User(
        id="second-reader",
        email="second-reader@example.com",
        name="Second reader",
        password_hash=hash_password(PASSWORD),
        role="member",
    )
    book, resource, _asset = _add_book_graph(
        db_session, book_id="shared-book", library_id="test-library"
    )
    assert resource is not None
    shelf = Shelf(id="first-shelf", owner_user_id=first.id, name="First", kind="STATIC")
    db_session.add_all(
        [
            first,
            second,
            UserLibraryAccess(user_id=first.id, library_id="test-library"),
            UserLibraryAccess(user_id=second.id, library_id="test-library"),
            UserPreference(user_id=first.id, key="locale", value='"en-US"'),
            UserPreference(user_id=second.id, key="locale", value='"zh-CN"'),
            shelf,
            ShelfBook(shelf_id=shelf.id, book_id=book.id),
            ReaderResourceProgress(
                id="first-progress",
                user_id=first.id,
                resource_id=resource.id,
                reader_type="reflowable",
                position="chapter-1",
                percent=50,
                extra="{}",
                progressed_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.commit()

    first_preferences = db_session.scalars(
        select(UserPreference).where(UserPreference.user_id == first.id)
    ).all()
    second_preferences = db_session.scalars(
        select(UserPreference).where(UserPreference.user_id == second.id)
    ).all()
    assert [(row.key, row.value) for row in first_preferences] == [("locale", '"en-US"')]
    assert [(row.key, row.value) for row in second_preferences] == [("locale", '"zh-CN"')]
    assert db_session.scalar(
        select(ReaderResourceProgress.percent).where(
            ReaderResourceProgress.user_id == first.id,
            ReaderResourceProgress.resource_id == resource.id,
        )
    ) == 50
    assert db_session.scalar(
        select(ReaderResourceProgress.percent).where(
            ReaderResourceProgress.user_id == second.id,
            ReaderResourceProgress.resource_id == resource.id,
        )
    ) is None
    assert db_session.scalar(
        select(ShelfBook.book_id)
        .join(Shelf, Shelf.id == ShelfBook.shelf_id)
        .where(Shelf.owner_user_id == first.id)
    ) == book.id
    assert db_session.scalar(
        select(ShelfBook.book_id)
        .join(Shelf, Shelf.id == ShelfBook.shelf_id)
        .where(Shelf.owner_user_id == second.id)
    ) is None
