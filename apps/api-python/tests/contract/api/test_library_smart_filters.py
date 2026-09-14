"""Book catalog filtering contracts after the identity cutover."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
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
    ReaderResourceProgressV5,
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
    library_id: str = "test-library",
) -> LibraryBook:
    path = f"{book_id}/"
    node = LibrarySourceNode(
        id=f"{book_id}-node",
        library_id=library_id,
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
        library_id=library_id,
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
        "coverUrl": "",
        "resourceImportSummary": {
            "ready": 1,
            "pending": 0,
            "failed": 0,
            "failedFiles": 0,
        },
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
        "failedFiles": 0,
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
        "failedFiles": 0,
    }


def test_recent_import_orders_by_created_at_with_deterministic_id_tiebreaker(
    client: TestClient, db_session: Session
) -> None:
    """The import sort follows the book creation/import timestamp, not edits."""

    _login(client, db_session)
    books = {
        book_id: _book(
            db_session,
            book_id=book_id,
            title=book_id,
            author="Author",
        )
        for book_id in ("older", "newer", "tie-a", "tie-b")
    }
    books["older"].created_at = datetime(2026, 1, 1, tzinfo=UTC)
    books["older"].updated_at = datetime(2026, 12, 1, tzinfo=UTC)
    books["newer"].created_at = datetime(2026, 2, 1, tzinfo=UTC)
    books["newer"].updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    for book_id in ("tie-a", "tie-b"):
        books[book_id].created_at = datetime(2026, 2, 1, tzinfo=UTC)
        books[book_id].updated_at = datetime(2025, 1, 1, tzinfo=UTC)
    db_session.commit()

    descending = client.get(
        "/api/books",
        params={
            "sort": "recent_import",
            "sortDirection": "desc",
            "view": "management",
            "pageSize": 100,
        },
    )
    assert descending.status_code == 200, descending.text
    assert [book["id"] for book in descending.json()["data"]["books"]] == [
        "tie-b",
        "tie-a",
        "newer",
        "older",
    ]

    ascending = client.get(
        "/api/books",
        params={
            "sort": "recent_import",
            "sortDirection": "asc",
            "view": "management",
            "pageSize": 100,
        },
    )
    assert ascending.status_code == 200, ascending.text
    assert [book["id"] for book in ascending.json()["data"]["books"]] == [
        "older",
        "newer",
        "tie-a",
        "tie-b",
    ]


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
            ReaderResourceProgressV5(
                id="reading-progress",
                user_id=user.id,
                resource_id="reading-book-resource",
                client_id="smart-filter-client",
                mutation_id="00000000-0000-4000-8000-000000000001",
                locator_json="{}",
                presentation_json=(
                    '{"chapter":null,"currentHref":null,"displayPercent":50,'
                    '"page":null,"playback":null,"totalProgression":0.5}'
                ),
                display_percent=50,
                total_progression=0.5,
                captured_at=now,
                revision=1,
            ),
            ReaderResourceProgressV5(
                id="finished-progress",
                user_id=user.id,
                resource_id="finished-book-resource",
                client_id="smart-filter-client",
                mutation_id="00000000-0000-4000-8000-000000000002",
                locator_json="{}",
                presentation_json=(
                    '{"chapter":null,"currentHref":null,"displayPercent":100,'
                    '"page":null,"playback":null,"totalProgression":1.0}'
                ),
                display_percent=100,
                total_progression=1.0,
                captured_at=now,
                revision=1,
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
        from app.bootstrap.library import smart_shelf_book_ids

        assert smart_shelf_book_ids(
            db_session, {"statuses": [status]}, user_id=user.id
        ) == [expected_book_id]


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
    from app.bootstrap.library import smart_shelf_book_ids

    assert set(
        smart_shelf_book_ids(db_session, {"tags": ["Fiction"]}, user_id=user.id)
    ) == {"book-a", "book-b"}
    assert (
        smart_shelf_book_ids(db_session, {"tags": ["Nonfiction"]}, user_id=user.id)
        == []
    )


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


@pytest.mark.parametrize(
    "combinator,field,value,expected",
    [
        ("ALL", "sourcePath", "岛田庄司", {"岛田庄司-a", "岛田庄司-b"}),
        ("ALL", "title", "螺丝人", {"岛田庄司-a"}),
        ("ANY", "title", "螺丝人", {"岛田庄司-a", "other"}),
    ],
)
def test_smart_shelf_matches_library_filters_and_pagination(
    client: TestClient,
    db_session: Session,
    combinator: str,
    field: str,
    value: str,
    expected: set[str],
) -> None:
    _login(client, db_session)
    for book_id, title in (
        ("岛田庄司-a", "螺丝人"),
        ("岛田庄司-b", "斜屋犯罪"),
        ("other", "其他作品"),
        ("hidden", "螺丝人"),
    ):
        _book(
            db_session,
            book_id=book_id,
            title=title,
            author="Author",
            visibility_state="HIDDEN" if book_id == "hidden" else "VISIBLE",
        )
        _ready_resource(db_session, book_id=book_id, resource_id=f"{book_id}-pdf")
    db_session.commit()
    conditions = [{"field": field, "operator": "contains", "value": value}]
    if combinator == "ANY":
        conditions.append({"field": "title", "operator": "equals", "value": "其他作品"})
    rules = {"combinator": combinator, "conditions": conditions}
    preview = client.get(
        "/api/books", params={"filters": json.dumps(rules), "view": "search"}
    )
    assert preview.status_code == 200, preview.text
    assert {book["id"] for book in preview.json()["data"]["books"]} == expected
    created = client.post(
        "/api/shelves", json={"name": "岛田庄司作品集", "kind": "SMART", "rules": rules}
    )
    assert created.status_code in (200, 201), created.text
    shelf = created.json()["data"]["shelf"]
    assert shelf["bookCount"] == len(expected)
    assert set(shelf["bookIds"]) == expected
    summaries = client.get("/api/shelves").json()["data"]["shelves"]
    summary = next(item for item in summaries if item["id"] == shelf["id"])
    assert summary["bookCount"] == len(expected)
    seen = []
    for page in range(1, len(expected) + 1):
        detail = client.get(
            f"/api/shelves/{shelf['id']}",
            params={"page": page, "pageSize": 1, "includeBookIds": False},
        )
        assert detail.status_code == 200, detail.text
        payload = detail.json()["data"]["shelf"]
        assert payload["bookCount"] == payload["total"] == len(expected)
        assert payload["totalPages"] == len(expected)
        assert len(payload["books"]) == 1
        seen.extend(book["id"] for book in payload["books"])
    assert len(seen) == len(set(seen)) and set(seen) == expected


def test_smart_shelf_admin_scope_and_member_authorization(db_session: Session) -> None:
    from app.bootstrap.library import smart_shelf_book_ids
    from app.models.auth import UserLibraryAccess
    from app.models.library import Library

    admin = User(
        id="scope-admin",
        email="scope-admin@example.com",
        name="Admin",
        password_hash="unused",
        role="admin",
    )
    member = User(
        id="scope-member",
        email="scope-member@example.com",
        name="Member",
        password_hash="unused",
        role="member",
    )
    db_session.add_all([admin, member])
    db_session.add(
        Library(
            id="other-library",
            name="Other library",
            root_path="/other-library",
            organization_mode="FLAT",
        )
    )
    db_session.flush()
    _book(
        db_session,
        book_id="other-visible",
        title="Other",
        author="Other",
        library_id="other-library",
    )
    _book(db_session, book_id="visible", title="Visible", author="Author")
    _book(
        db_session,
        book_id="hidden",
        title="Hidden",
        author="Author",
        visibility_state="HIDDEN",
    )
    db_session.commit()
    assert set(smart_shelf_book_ids(db_session, {}, user_id=admin.id)) == {
        "visible",
        "other-visible",
    }
    assert smart_shelf_book_ids(db_session, {}, user_id=member.id) == []
    assert smart_shelf_book_ids(db_session, {}, user_id="nonexistent") == []
    db_session.add(UserLibraryAccess(user_id=member.id, library_id="test-library"))
    db_session.commit()
    assert smart_shelf_book_ids(db_session, {}, user_id=member.id) == ["visible"]
    assert (
        smart_shelf_book_ids(db_session, {"authors": ["No match"]}, user_id=member.id)
        == []
    )
    assert smart_shelf_book_ids(
        db_session, {"search": "Visible", "authors": ["Author"]}, user_id=member.id
    ) == ["visible"]
