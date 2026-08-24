from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models import (
    Library,
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.models.auth import User, UserLibraryAccess
from app.modules.library.application.catalog import (
    CatalogBookFilter,
    GetCatalogBook,
    ListCatalogBooks,
    ListCatalogFacets,
)
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _node(
    node_id: str,
    relative_path: str,
    *,
    library_id: str = "test-library",
    directory: bool = False,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id=library_id,
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 123,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _book_graph(
    db: Session,
    book_id: str,
    title: str,
    *,
    library_id: str = "test-library",
    author: str = "Catalog Author",
) -> LibraryBook:
    book_node = _node(
        f"{book_id}-node", f"{book_id}/", library_id=library_id, directory=True
    )
    resource_node = _node(
        f"{book_id}-resource-node", f"{book_id}.epub", library_id=library_id
    )
    book = LibraryBook(
        id=book_id,
        library_id=library_id,
        source_node_id=book_node.id,
    )
    resource_id = f"{book_id}-resource"
    resource = LibraryReadableResource(
        id=resource_id,
        library_id=library_id,
        book_id=book_id,
        source_node_id=resource_node.id,
        adapter_id="book-file",
        adapter_version="1",
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
            title=title,
            normalized_title=title.casefold(),
            author=author,
            normalized_author=author.casefold(),
        )
    )
    db.flush()
    db.add(resource)
    db.flush()
    db.add(LibraryReadableResourceMetadata(resource_id=resource_id, title=title))
    db.flush()
    db.add(
        LibraryResourceAsset(
            id=f"{resource_id}-asset",
            library_id=library_id,
            resource_id=resource_id,
            source_node_id=resource_node.id,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db.flush()
    db.add(
        LibraryResourceAssetMetadata(
            asset_id=f"{resource_id}-asset",
            mime_type="application/epub+zip",
        )
    )
    return book


def test_catalog_lists_authorized_books_resources_assets_and_facets(
    db_session: Session,
) -> None:
    admin = User(
        id="catalog-admin",
        email="catalog-admin@example.com",
        name="Catalog Admin",
        password_hash="unused",
        role="admin",
    )
    _book_graph(db_session, "ebook", "Alpha")
    _book_graph(db_session, "audio", "Audio")
    facet = LibraryFacet(
        id="facet-catalog-author",
        kind="AUTHOR",
        name="Catalog Author",
        normalized_name="catalog author",
    )
    db_session.add_all([admin, facet])
    db_session.flush()
    db_session.add_all(
        [
            LibraryBookFacet(facet_id=facet.id, book_id="ebook"),
            LibraryBookFacet(facet_id=facet.id, book_id="audio"),
        ]
    )
    db_session.commit()

    context = authorization_context(db_session, admin)
    queries = SqlAlchemyCatalogQueries(db_session)
    page = ListCatalogBooks(queries).execute(
        context=context,
        filters=CatalogBookFilter(search="alpha", sort="title"),
        page=1,
        page_size=10,
    )
    assert page.total == 1
    assert [book.id for book in page.books] == ["ebook"]
    assert page.books[0].resources[0].asset.id == "ebook-resource-asset"

    facet_page = ListCatalogFacets(queries).execute(
        context=context, kind="AUTHOR", page=1, page_size=10
    )
    assert [(item.id, item.book_count) for item in facet_page.facets] == [
        ("facet-catalog-author", 2)
    ]


def test_catalog_scope_is_applied_inside_book_queries(db_session: Session) -> None:
    member = User(
        id="catalog-member",
        email="catalog-member@example.com",
        name="Catalog Member",
        password_hash="unused",
        role="member",
    )
    other_library = Library(
        id="other-library",
        name="Other",
        root_path="/other",
        organization_mode="FLAT",
    )
    db_session.add(other_library)
    db_session.flush()
    _book_graph(db_session, "member-book", "Member", library_id="test-library")
    _book_graph(db_session, "foreign-book", "Foreign", library_id="other-library")
    db_session.add_all(
        [member, UserLibraryAccess(user_id=member.id, library_id="test-library")]
    )
    db_session.commit()

    context = authorization_context(db_session, member)
    result = ListCatalogBooks(SqlAlchemyCatalogQueries(db_session)).execute(
        context=context, page=1, page_size=10
    )
    assert [book.id for book in result.books] == ["member-book"]
    assert (
        GetCatalogBook(SqlAlchemyCatalogQueries(db_session)).execute(
            context=context, book_id="foreign-book"
        )
        is None
    )


def test_empty_book_id_filter_does_not_expand_to_every_book(
    db_session: Session,
) -> None:
    admin = User(
        id="empty-filter-admin",
        email="empty-filter-admin@example.com",
        name="Empty filter admin",
        password_hash="unused",
        role="admin",
    )
    _book_graph(db_session, "one-book", "One")
    db_session.add(admin)
    db_session.commit()
    context = authorization_context(db_session, admin)

    result = ListCatalogBooks(SqlAlchemyCatalogQueries(db_session)).execute(
        context=context,
        filters=CatalogBookFilter(book_ids=()),
        page=1,
        page_size=10,
    )
    assert result.total == 1
