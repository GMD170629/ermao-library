from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.auth import User
from app.models.shelf import Shelf, ShelfBook
from app.modules.shelf.application.catalog import (
    ListCatalogShelfBookIds,
    ListCatalogShelves,
)
from app.modules.shelf.infrastructure.catalog import SqlAlchemyCatalogShelfQueries


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _source_node(
    node_id: str,
    relative_path: str,
    *,
    physical_kind: str = "REGULAR_FILE",
    size: int | None = 1,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind=physical_kind,
        observed_size_bytes=size if physical_kind != "DIRECTORY" else None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _book_graph(db: Session, book_id: str, *, hidden: bool = False) -> LibraryBook:
    book_node = _source_node(
        f"{book_id}-node", f"{book_id}/", physical_kind="DIRECTORY", size=None
    )
    resource_node = _source_node(f"{book_id}-resource-node", f"{book_id}.epub")
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=book_node.id,
        visibility_state="HIDDEN" if hidden else "VISIBLE",
    )
    resource = LibraryReadableResource(
        id=f"{book_id}-resource",
        library_id="test-library",
        book_id=book_id,
        source_node_id=resource_node.id,
        adapter_id="epub-file",
        adapter_version="1",
        media_kind="EBOOK",
        format="EPUB",
        import_state="READY",
    )
    db.add_all([book_node, resource_node])
    db.flush()
    db.add(book)
    db.flush()
    db.add(
        LibraryBookMetadata(
            book_id=book_id,
            title=book_id.replace("-", " ").title(),
            normalized_title=book_id,
            author="Author",
        )
    )
    db.flush()
    db.add(resource)
    db.flush()
    db.add(
        LibraryReadableResourceMetadata(
            resource_id=resource.id,
            title=resource.id,
        )
    )
    db.flush()
    db.add(
        LibraryResourceAsset(
            id=f"{book_id}-asset",
            library_id="test-library",
            resource_id=resource.id,
            source_node_id=resource_node.id,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db.flush()
    return book


def test_catalog_shelves_are_owned_static_and_resource_graph_is_canonical(
    db_session: Session,
) -> None:
    owner = User(
        id="shelf-owner",
        email="shelf-owner@example.com",
        name="Shelf Owner",
        password_hash="unused",
        role="admin",
    )
    other = User(
        id="shelf-other",
        email="shelf-other@example.com",
        name="Shelf Other",
        password_hash="unused",
        role="admin",
    )
    _book_graph(db_session, "visible-book")
    _book_graph(db_session, "hidden-book", hidden=True)
    owned = Shelf(
        id="owned-static", owner_user_id=owner.id, name="Owned", kind="STATIC"
    )
    smart = Shelf(id="owned-smart", owner_user_id=owner.id, name="Smart", kind="SMART")
    foreign = Shelf(
        id="foreign-static", owner_user_id=other.id, name="Foreign", kind="STATIC"
    )
    db_session.add_all([owner, other])
    db_session.flush()
    db_session.add_all([owned, smart, foreign])
    db_session.flush()
    db_session.add_all(
        [
            ShelfBook(shelf_id=owned.id, book_id="visible-book"),
            ShelfBook(shelf_id=owned.id, book_id="hidden-book"),
        ]
    )
    db_session.commit()

    context = authorization_context(db_session, owner)
    queries = SqlAlchemyCatalogShelfQueries(
        db_session,
        smart_book_ids=lambda _rules, _user_id: ["visible-book"],
    )
    shelves = ListCatalogShelves(queries).execute(context=context)
    books = ListCatalogShelfBookIds(queries).execute(context=context, shelf_id=owned.id)

    assert {shelf.id for shelf in shelves.shelves} == {owned.id, smart.id}
    assert books is not None
    assert books.book_ids == ("visible-book",)
    smart_books = ListCatalogShelfBookIds(queries).execute(
        context=context, shelf_id=smart.id
    )
    assert smart_books is not None
    assert smart_books.book_ids == ("visible-book",)
    assert (
        ListCatalogShelfBookIds(queries).execute(context=context, shelf_id=foreign.id)
        is None
    )
