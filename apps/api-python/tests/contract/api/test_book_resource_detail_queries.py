"""Contract coverage for the canonical Book/ReadableResource/Asset surface."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.core.auth import hash_password
from app.main import create_app
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    ReadableResourceNavigationUnit,
    ReaderResourceProgress,
)
from app.models.auth import User


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _source_node(
    node_id: str,
    relative_path: str,
    *,
    physical_kind: str = "REGULAR_FILE",
    size: int | None = 100,
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


def _add_book(
    db_session,
    *,
    book_id: str = "detail-book",
    resource_count: int = 3,
) -> tuple[LibraryBook, list[LibraryReadableResource]]:
    book_node = _source_node(
        f"{book_id}-node", f"{book_id}/", physical_kind="DIRECTORY", size=None
    )
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=book_node.id,
    )
    db_session.add_all(
        [
            book_node,
            book,
            LibraryBookMetadata(
                book_id=book_id,
                title="Detail book",
                normalized_title="detail book",
                author="Author",
            ),
        ]
    )
    db_session.flush()

    resources: list[LibraryReadableResource] = []
    for index in range(resource_count):
        resource_id = f"detail-resource-{index + 1:02d}"
        relative_path = f"{book_id}/resource-{index + 1:02d}.epub"
        source_node = _source_node(
            f"{resource_id}-node", relative_path, size=(index + 1) * 100
        )
        resource = LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book_id,
            source_node_id=source_node.id,
            adapter_id="epub-file",
            adapter_version="1",
            media_kind="EBOOK",
            format="EPUB",
            import_state="READY",
        )
        resources.append(resource)
        db_session.add_all(
            [
                source_node,
                resource,
                LibraryReadableResourceMetadata(
                    resource_id=resource_id,
                    title=f"Resource {index + 1}",
                    resource_index=index + 1,
                    chapter_count=index + 2,
                ),
                LibraryResourceAsset(
                    id=f"{resource_id}-asset",
                    library_id="test-library",
                    resource_id=resource_id,
                    source_node_id=source_node.id,
                    source_node_physical_kind="REGULAR_FILE",
                    role="PRIMARY",
                    import_state="READY",
                    sequence_index=0,
                ),
                LibraryResourceAssetMetadata(
                    asset_id=f"{resource_id}-asset",
                    mime_type="application/epub+zip",
                ),
            ]
        )
    db_session.flush()
    return book, resources


def _login(client, db_session, *, email: str = "detail@example.com") -> User:
    user = User(
        id=f"user-{email.split('@', 1)[0]}",
        email=email,
        name="Detail reader",
        password_hash=hash_password("detail-password"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "detail-password"},
    )
    assert response.status_code == 200, response.text
    return user


def test_book_detail_is_bounded_and_projects_resource_assets(client, db_session) -> None:
    user = _login(client, db_session)
    _book, resources = _add_book(db_session, resource_count=12)
    db_session.add(
        ReaderResourceProgress(
            id="detail-progress",
            user_id=user.id,
            resource_id=resources[1].id,
            reader_type="reflowable",
            position="chapter-2",
            percent=42.5,
            extra="{}",
            progressed_at=datetime.now(UTC),
            source_protocol="SHUKU_WEB",
        )
    )
    db_session.commit()

    response = client.get("/api/books/detail-book")
    assert response.status_code == 200, response.text
    payload = response.json()["data"]["book"]
    assert payload["id"] == "detail-book"
    assert payload["title"] == "Detail book"
    assert [item["id"] for item in payload["resources"]] == [
        "detail-resource-01",
        "detail-resource-02",
        "detail-resource-03",
        "detail-resource-04",
        "detail-resource-05",
        "detail-resource-06",
        "detail-resource-07",
        "detail-resource-08",
        "detail-resource-09",
        "detail-resource-10",
        "detail-resource-11",
        "detail-resource-12",
    ]
    selected = next(item for item in payload["resources"] if item["id"] == "detail-resource-02")
    assert selected["resourceCompleted"] is False
    assert selected["progress"] == 42.5
    assert selected["assets"][0]["resourceId"] == selected["id"]
    assert selected["assets"][0]["url"] == "/api/assets/detail-resource-02-asset"


def test_book_resource_query_pages_deterministically(client, db_session) -> None:
    _login(client, db_session, email="page@example.com")
    _add_book(db_session, resource_count=5)
    db_session.commit()

    response = client.get(
        "/api/books/detail-book/resources",
        params={"page": 2, "pageSize": 2},
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["bookId"] == "detail-book"
    assert payload["page"] == 2
    assert payload["pageSize"] == 2
    assert payload["total"] == 5
    assert payload["totalPages"] == 3
    assert [item["id"] for item in payload["resources"]] == [
        "detail-resource-03",
        "detail-resource-04",
    ]


def test_reading_units_are_scoped_to_one_book_resource(client, db_session) -> None:
    _login(client, db_session, email="units@example.com")
    _add_book(db_session, resource_count=2)
    db_session.add_all(
        [
            ReadableResourceNavigationUnit(
                id="unit-one",
                resource_id="detail-resource-01",
                unit_type="chapter",
                title="Chapter 1",
                href="chapter-1.xhtml",
                media_type="application/xhtml+xml",
                sort_order=0,
                metadata_json=json.dumps({"chapter": 1}),
            ),
            ReadableResourceNavigationUnit(
                id="unit-two",
                resource_id="detail-resource-02",
                unit_type="chapter",
                title="Other chapter",
                href="other.xhtml",
                media_type="application/xhtml+xml",
                sort_order=0,
                metadata_json="{}",
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/books/detail-book/resources/detail-resource-01/reading-units"
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["bookId"] == "detail-book"
    assert data["resourceId"] == "detail-resource-01"
    assert [unit["id"] for unit in data["units"]] == ["unit-one"]


def test_book_resource_contract_preserves_auth_and_retires_old_routes(
    client, db_session
) -> None:
    _add_book(db_session, resource_count=1)
    db_session.commit()

    assert client.get("/api/books/detail-book").status_code == 401
    assert client.get("/api/books/missing-book").status_code == 401
    assert client.get("/api/works/detail-book").status_code == 404
    assert client.get("/api/books/detail-book/versions").status_code == 404
    assert client.get("/api/books/detail-book/resources/missing-resource").status_code == 401


def test_openapi_exposes_only_canonical_book_resource_reader_paths() -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/books/{book_id}" in paths
    assert "/api/books/{book_id}/resources" in paths
    assert "/api/resources/{resource_id}" in paths
    assert "/api/reader/v4/resources/{resource_id}/bootstrap" in paths
    assert not any(
        path.startswith("/api/works")
        or "/versions" in path
        or "/volumes" in path
        for path in paths
    )
