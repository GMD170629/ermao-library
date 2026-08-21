"""Book catalog filtering contracts after the identity cutover."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.authorization import authorization_context
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibrarySourceNode,
)
from app.models.auth import User
from app.modules.library.application.catalog import CatalogBookFilter, ListCatalogBooks
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries


def _book(
    db: Session,
    *,
    book_id: str,
    title: str,
    author: str | None,
    visibility_state: str = "VISIBLE",
) -> LibraryBook:
    path = f"{book_id}/"
    node = LibrarySourceNode(
        id=f"{book_id}-node",
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=book_id,
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=node.id,
        visibility_state=visibility_state,
    )
    db.add(node)
    db.flush()
    db.add(book)
    db.flush()
    db.add(
        LibraryBookMetadata(
            book_id=book_id,
            title=title,
            normalized_title=title.casefold(),
            author=author,
            normalized_author=author.casefold() if author else None,
            series_name="Series" if book_id != "empty" else None,
        )
    )
    db.flush()
    return book


def _login(client: TestClient, db: Session) -> User:
    user = User(
        id="smart-filter-admin",
        email="smart-filter@example.com",
        name="Smart filter admin",
        password_hash=hash_password("smart-filter-password"),
        role="admin",
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "smart-filter-password"},
    )
    assert response.status_code == 200, response.text
    return user


def test_book_list_search_is_deterministic_and_keeps_empty_books(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    _book(db_session, book_id="alpha", title="Alpha", author="Author")
    _book(db_session, book_id="beta", title="Beta", author="Author")
    _book(db_session, book_id="empty", title="Empty Book", author=None)
    db_session.commit()

    response = client.get("/api/books", params={"search": "Book", "pageSize": 100})

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert [item["id"] for item in payload["books"]] == ["empty"]
    assert payload["total"] == 1
    assert payload["books"][0]["resources"] == []
    assert payload["books"][0]["completed"] is False


def test_catalog_facet_filter_uses_book_ids_and_stable_title_order(
    db_session: Session,
) -> None:
    user = User(
        id="smart-filter-user",
        email="smart-filter-user@example.com",
        name="Smart filter user",
        password_hash="unused",
        role="admin",
    )
    _book(db_session, book_id="book-b", title="Beta", author="Author")
    _book(db_session, book_id="book-a", title="Alpha", author="Author")
    facet = LibraryFacet(
        id="facet-tag-fiction",
        kind="TAG",
        name="Fiction",
        normalized_name="fiction",
    )
    db_session.add_all([user, facet])
    db_session.flush()
    db_session.add_all(
        [
            LibraryBookFacet(facet_id=facet.id, book_id="book-a"),
            LibraryBookFacet(facet_id=facet.id, book_id="book-b"),
        ]
    )
    db_session.commit()
    context = authorization_context(db_session, user)

    result = ListCatalogBooks(SqlAlchemyCatalogQueries(db_session)).execute(
        context=context,
        filters=CatalogBookFilter(facet_kind="TAG", facet_id=facet.id),
        page=1,
        page_size=10,
    )

    assert result.total == 2
    assert [item.id for item in result.books] == ["book-a", "book-b"]


def test_catalog_filter_contract_rejects_only_one_facet_dimension(
    db_session: Session,
) -> None:
    user = User(
        id="smart-filter-validation-user",
        email="smart-filter-validation@example.com",
        name="Validation user",
        password_hash="unused",
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    context = authorization_context(db_session, user)

    try:
        ListCatalogBooks(SqlAlchemyCatalogQueries(db_session)).execute(
            context=context,
            filters=CatalogBookFilter(facet_kind="TAG"),
            page=1,
            page_size=10,
        )
    except ValueError as exc:
        assert "facet" in str(exc)
    else:
        raise AssertionError("a facet kind without an id must be rejected")


def test_removed_identity_routes_are_not_filtering_aliases(client: TestClient) -> None:
    assert client.get("/api/works").status_code == 404
    assert client.get("/api/versions").status_code == 404
    assert client.get("/api/volumes").status_code == 404
