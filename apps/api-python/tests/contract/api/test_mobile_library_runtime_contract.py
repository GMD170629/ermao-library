"""FastAPI fixtures for the current mobile library wire contracts.

These checks intentionally exercise the HTTP routes instead of only validating
the Pydantic models.  The mobile host tests use the same response shapes as the
fixture strings in ``CurrentLibraryApiContractFixtureTest``.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
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


def _seed_book(db: Session) -> LibraryBook:
    book_id = "mobile-contract-book"
    book_path = f"{book_id}/"
    book_node = LibrarySourceNode(
        id=f"{book_id}-node",
        library_id="test-library",
        relative_path=book_path,
        path_key="v1:" + hashlib.sha256(book_path.encode()).hexdigest(),
        name=book_id,
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=book_node.id,
        visibility_state="VISIBLE",
    )
    metadata = LibraryBookMetadata(
        book_id=book_id,
        title="Mobile contract book",
        normalized_title="mobile contract book",
        author="Contract author",
        normalized_author="contract author",
        series_name="Contract series",
    )
    db.add_all([book_node, book])
    db.flush()
    db.add(metadata)
    db.flush()
    return book


def _seed_ready_resource(db: Session, book: LibraryBook) -> LibraryReadableResource:
    resource_id = "mobile-contract-resource"
    resource_path = f"{book.id}/{resource_id}.pdf"
    resource_node = LibrarySourceNode(
        id=f"{resource_id}-node",
        library_id=book.library_id,
        relative_path=resource_path,
        path_key="v1:" + hashlib.sha256(resource_path.encode()).hexdigest(),
        name=f"{resource_id}.pdf",
        physical_kind="REGULAR_FILE",
        observed_size_bytes=1024,
        observed_mtime_ns=1_724_470_400_000_000_000,
        observed_at=datetime.now(UTC),
    )
    resource = LibraryReadableResource(
        id=resource_id,
        library_id=book.library_id,
        book_id=book.id,
        source_node_id=resource_node.id,
        adapter_id="pdf-file",
        adapter_version="1",
        format="PDF",
        import_state="READY",
    )
    metadata = LibraryReadableResourceMetadata(
        resource_id=resource_id,
        title="Contract resource",
        resource_index=1,
    )
    asset = LibraryResourceAsset(
        id="mobile-contract-asset",
        library_id=book.library_id,
        resource_id=resource_id,
        source_node_id=resource_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
    )
    db.add(resource_node)
    db.flush()
    db.add(resource)
    db.flush()
    db.add_all([metadata, asset])
    db.flush()
    return resource


def _login(client: TestClient, db: Session) -> User:
    user = User(
        id="mobile-contract-user",
        email="mobile-contract@example.com",
        name="Mobile contract user",
        password_hash=hash_password("mobile-contract-password"),
        role="admin",
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "mobile-contract-password"},
    )
    assert response.status_code == 200, response.text
    return user


def test_mobile_library_routes_emit_current_wire_shapes(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    book = _seed_book(db_session)
    resource = _seed_ready_resource(db_session, book)
    now = datetime(2026, 8, 12, tzinfo=UTC)
    db_session.add(
        ReaderResourceProgressV5(
            id="mobile-contract-progress",
            user_id=user.id,
            resource_id=resource.id,
            client_id="mobile-contract-client",
            mutation_id="00000000-0000-4000-8000-000000000001",
            locator_json='{"page":3}',
            presentation_json=(
                '{"displayPercent":42,"totalProgression":0.42,'
                '"currentHref":null,"chapter":null,"page":null,"playback":null}'
            ),
            display_percent=42,
            total_progression=0.42,
            captured_at=now,
            received_at=now,
            updated_at=now,
            revision=1,
        )
    )
    facet = LibraryFacet(
        id="mobile-contract-author",
        kind="AUTHOR",
        name="Contract author",
        normalized_name="contract author",
    )
    db_session.add(facet)
    db_session.flush()
    db_session.add(LibraryBookFacet(facet_id=facet.id, book_id=book.id))
    db_session.commit()

    recent_books = client.get("/api/dashboard/recent-books", params={"limit": 10})
    assert recent_books.status_code == 200, recent_books.text
    recent_book = recent_books.json()["data"]["books"][0]
    assert set(recent_book) == {
        "id",
        "title",
        "author",
        "coverUrl",
        "resourceImportSummary",
        "progress",
    }
    assert recent_book["resourceImportSummary"] == {
        "ready": 0,
        "pending": 0,
        "failed": 0,
    }

    recent_reading = client.get("/api/dashboard/recent-reading", params={"limit": 10})
    assert recent_reading.status_code == 200, recent_reading.text
    assert set(recent_reading.json()["data"]["books"][0]) == set(recent_book)

    continue_reading = client.get("/api/dashboard/continue-reading")
    assert continue_reading.status_code == 200, continue_reading.text
    continue_item = continue_reading.json()["data"]["item"]
    assert set(continue_item) == {
        "bookId",
        "title",
        "author",
        "coverUrl",
        "resourceFormat",
        "readerType",
        "resumeResourceId",
        "progress",
        "lastReadAt",
        "chapter",
        "resourceTitle",
        "narrator",
    }
    assert "mediaKind" not in continue_item

    books = client.get(
        "/api/books",
        params={"view": "search", "pageSize": 100},
    )
    assert books.status_code == 200, books.text
    search_book = books.json()["data"]["books"][0]
    assert set(search_book) == set(recent_book)

    groupings = client.get(
        "/api/library/groupings",
        params={"kind": "AUTHOR", "pageSize": 48},
    )
    assert groupings.status_code == 200, groupings.text
    grouping_payload = groupings.json()["data"]
    assert "kind" not in grouping_payload
    assert grouping_payload["groups"][0]["representativeBooks"][0]["id"] == book.id

    detail = client.get(f"/api/books/{book.id}")
    assert detail.status_code == 200, detail.text
    detail_book = detail.json()["data"]["book"]
    assert detail_book["resourceImportSummary"] == {
        "ready": 1,
        "pending": 0,
        "failed": 0,
    }
    assert "availableMediaKinds" not in detail_book
    detail_resource = detail_book["resources"][0]
    assert "mediaKind" not in detail_resource
    assert "classification" not in detail_resource
    assert detail_resource["assets"][0]["title"] == "mobile-contract-resource.pdf"
    assert "path" not in detail_resource["assets"][0]

    resources = client.get(f"/api/books/{book.id}/resources")
    assert resources.status_code == 200, resources.text
    resource_payload = resources.json()["data"]
    assert resource_payload["bookId"] == book.id
    assert "mediaKind" not in resource_payload["resources"][0]
    assert resource_payload["resources"][0]["assets"][0]["title"] == (
        "mobile-contract-resource.pdf"
    )
    assert "path" not in resource_payload["resources"][0]["assets"][0]
