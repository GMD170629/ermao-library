"""Book catalog filtering contracts after the identity cutover."""

from __future__ import annotations

import hashlib
import json
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
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    ReaderResourceProgress,
)
from app.models.auth import User
from app.modules.library.application.catalog import CatalogBookFilter, ListCatalogBooks
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries

REMOVED_LIBRARY_FILTER_FIELDS = {
    "metadataQuality",
    "volumeTitle",
    "resourceTitle",
    "narrator",
    "fileSize",
    "pageCount",
    "chapterCount",
    "duration",
    "resourceCount",
    "publicationStatus",
    "trackingStatus",
    "organizeStatus",
    "organized",
    "createdAt",
    "updatedAt",
}


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


def _ready_resource(
    db: Session,
    *,
    book_id: str,
    resource_id: str,
) -> LibraryReadableResource:
    resource_path = f"{book_id}/{resource_id}.pdf"
    node = LibrarySourceNode(
        id=f"{resource_id}-node",
        library_id="test-library",
        relative_path=resource_path,
        path_key="v1:" + hashlib.sha256(resource_path.encode()).hexdigest(),
        name=f"{resource_id}.pdf",
        physical_kind="REGULAR_FILE",
        observed_size_bytes=1,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    resource = LibraryReadableResource(
        id=resource_id,
        library_id="test-library",
        book_id=book_id,
        source_node_id=node.id,
        adapter_id="pdf-file",
        adapter_version="1",
        format="PDF",
        import_state="READY",
    )
    db.add(node)
    db.flush()
    db.add(resource)
    db.flush()
    db.add(LibraryReadableResourceMetadata(resource_id=resource_id, title="PDF"))
    db.add(
        LibraryResourceAsset(
            id=f"{resource_id}-asset",
            library_id="test-library",
            resource_id=resource_id,
            source_node_id=node.id,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db.flush()
    return resource


def test_book_list_search_is_deterministic_and_keeps_empty_books(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    _book(db_session, book_id="alpha", title="Alpha", author="Author")
    _book(db_session, book_id="beta", title="Beta", author="Author")
    _book(db_session, book_id="empty", title="Empty Book", author=None)
    db_session.commit()

    response = client.get(
        "/api/books",
        params={"search": "Book", "pageSize": 100, "view": "management"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert [item["id"] for item in payload["books"]] == ["empty"]
    assert payload["total"] == 1
    assert payload["books"][0]["author"] is None
    assert payload["books"][0]["statusValue"] == "UNREAD"


def test_book_list_projections_expose_nullable_author_and_ready_resource(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    _book(db_session, book_id="ready-book", title="Ready Book", author=None)
    _ready_resource(db_session, book_id="ready-book", resource_id="ready-resource")
    db_session.commit()

    bookshelf = client.get(
        "/api/books",
        params={"view": "bookshelf", "pageSize": 100},
    )
    assert bookshelf.status_code == 200, bookshelf.text
    bookshelf_item = bookshelf.json()["data"]["books"][0]
    assert bookshelf_item == {
        "id": "ready-book",
        "title": "Ready Book",
        "author": None,
        "coverUrl": "/api/books/ready-book/cover?size=medium",
        "resourceImportSummary": {"ready": 1, "pending": 0, "failed": 0},
        "progress": 0.0,
    }

    search = client.get(
        "/api/books",
        params={"view": "search", "pageSize": 100},
    )
    assert search.status_code == 200, search.text
    assert search.json()["data"]["books"][0] == bookshelf_item

    management = client.get(
        "/api/books",
        params={"view": "management", "pageSize": 100},
    )
    assert management.status_code == 200, management.text
    management_item = management.json()["data"]["books"][0]
    assert management_item["author"] is None
    assert management_item["resourceImportSummary"] == {
        "ready": 1,
        "pending": 0,
        "failed": 0,
    }
    assert management_item["statusValue"] == "UNREAD"
    assert management_item["gradient"] == ""
    assert management_item["coverStatus"] == "PENDING"

    full = client.get("/api/books", params={"pageSize": 100})
    assert full.status_code == 200, full.text
    full_item = full.json()["data"]["books"][0]
    assert full_item["author"] is None
    assert [resource["id"] for resource in full_item["resources"]] == ["ready-resource"]
    assert full_item["resourceImportSummary"] == {
        "ready": 1,
        "pending": 0,
        "failed": 0,
    }


def test_book_list_rejects_unknown_projection(client: TestClient) -> None:
    response = client.get("/api/books", params={"view": "unknown"})

    assert response.status_code == 422


def test_library_filter_contract_removes_retired_dimensions_and_media_queries(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)

    schema_response = client.get("/api/library/filter-schema")

    assert schema_response.status_code == 200, schema_response.text
    fields = schema_response.json()["data"]["fields"]
    field_keys = {field["key"] for field in fields}
    assert "readingStatus" in field_keys
    assert field_keys.isdisjoint(REMOVED_LIBRARY_FILTER_FIELDS)
    assert {field["group"] for field in fields}.isdisjoint({"资源元数据"})

    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200, openapi_response.text
    book_query_parameters = {
        parameter["name"]
        for parameter in openapi_response.json()["paths"]["/api/books"]["get"][
            "parameters"
        ]
    }
    assert book_query_parameters.isdisjoint({"type", "media"})

    for field in REMOVED_LIBRARY_FILTER_FIELDS:
        response = client.get(
            "/api/books",
            params={
                "filters": json.dumps(
                    {
                        "combinator": "ALL",
                        "conditions": [
                            {"field": field, "operator": "is_empty"},
                        ],
                    }
                )
            },
        )
        assert response.status_code == 422, (field, response.text)


def test_book_list_filters_by_the_three_supported_reading_states(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    for book_id in ("unread-book", "reading-book", "finished-book"):
        _book(db_session, book_id=book_id, title=book_id, author="Author")
        _ready_resource(
            db_session,
            book_id=book_id,
            resource_id=f"{book_id}-resource",
        )
    now = datetime.now(UTC)
    db_session.add_all(
        [
            ReaderResourceProgress(
                id="reading-progress",
                user_id=user.id,
                resource_id="reading-book-resource",
                reader_type="reflowable",
                position="chapter-1",
                percent=50,
                extra="{}",
                progressed_at=now,
                source_protocol="SHUKU_WEB",
            ),
            ReaderResourceProgress(
                id="finished-progress",
                user_id=user.id,
                resource_id="finished-book-resource",
                reader_type="reflowable",
                position="chapter-2",
                percent=100,
                extra="{}",
                progressed_at=now,
                source_protocol="SHUKU_WEB",
            ),
        ]
    )
    db_session.commit()

    for status, expected_book_id in (
        ("UNREAD", "unread-book"),
        ("READING", "reading-book"),
        ("FINISHED", "finished-book"),
    ):
        response = client.get(
            "/api/books",
            params={"status": status, "view": "management", "pageSize": 100},
        )
        assert response.status_code == 200, response.text
        assert [book["id"] for book in response.json()["data"]["books"]] == [
            expected_book_id
        ]


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
