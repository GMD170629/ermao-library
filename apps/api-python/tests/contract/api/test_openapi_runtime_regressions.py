from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.bootstrap.system import record_system_event
from app.core.auth import hash_password
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.models.auth import User

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session


ADMIN_EMAIL = "openapi-regression@example.com"
ADMIN_PASSWORD = "OpenApiRegression123!"


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _source_node(
    node_id: str,
    relative_path: str,
    *,
    physical_kind: str = "REGULAR_FILE",
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind=physical_kind,
        observed_size_bytes=None if physical_kind == "DIRECTORY" else 1024,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _login_admin(client: TestClient, db_session: Session) -> User:
    user = User(
        id="openapi-regression-admin",
        email=ADMIN_EMAIL,
        name="OpenAPI Regression",
        password_hash=hash_password(ADMIN_PASSWORD),
        role="admin",
        can_manage_system=True,
    )
    db_session.add(user)
    db_session.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return user


def _seed_book_resource(
    db_session: Session,
) -> tuple[LibraryBook, LibraryReadableResource]:
    book_id = "openapi-book"
    resource_id = "openapi-resource"
    book_node = _source_node(
        "openapi-book-node", "openapi-book", physical_kind="DIRECTORY"
    )
    resource_node = _source_node("openapi-resource-node", "openapi-book/book.epub")
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=book_node.id,
    )
    resource = LibraryReadableResource(
        id=resource_id,
        library_id="test-library",
        book_id=book_id,
        source_node_id=resource_node.id,
        adapter_id="epub-file",
        adapter_version="1",
        media_kind="EBOOK",
        format="EPUB",
        enablement_state="ENABLED",
        import_state="READY",
    )
    db_session.add_all([book_node, resource_node])
    db_session.flush()
    db_session.add(book)
    db_session.flush()
    db_session.add_all(
        [
            LibraryBookMetadata(
                book_id=book_id,
                title="OpenAPI 回归图书",
                normalized_title="openapi 回归图书",
                author="测试作者",
                normalized_author="测试作者",
            ),
            resource,
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            LibraryReadableResourceMetadata(
                resource_id=resource_id,
                title="OpenAPI 回归资源",
                resource_index=1,
            ),
            LibraryResourceAsset(
                id="openapi-asset",
                library_id="test-library",
                resource_id=resource_id,
                source_node_id=resource_node.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
                sequence_index=0,
            ),
        ]
    )
    db_session.flush()
    db_session.add(
        LibraryResourceAssetMetadata(
            asset_id="openapi-asset",
            mime_type="application/epub+zip",
        )
    )
    db_session.commit()
    return book, resource


def test_management_events_and_overview_accept_real_event_metadata(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    metadata = {
        "sourceFormat": "TXT",
        "skipped": [],
        "nested": {"ids": ["book-a", "book-b"], "ratio": None},
    }
    record_system_event(
        db_session,
        source="library",
        action="IMPORT_COMPLETED",
        level="info",
        message="OpenAPI metadata regression",
        actor_type="user",
        actor_id=user.id,
        metadata=metadata,
    )
    db_session.commit()

    events_response = client.get("/api/management/events")
    assert events_response.status_code == 200
    assert events_response.json()["data"]["events"][0]["metadata"] == metadata



def test_canonical_book_resource_contract_has_only_target_identities(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    _seed_book_resource(db_session)

    response = client.get("/api/books/openapi-book")
    assert response.status_code == 200, response.text
    payload = response.json()["data"]["book"]
    assert payload["id"] == "openapi-book"
    assert payload["resources"][0]["id"] == "openapi-resource"
    assert payload["resources"][0]["assets"][0]["id"] == "openapi-asset"
    assert not {
        "workId",
        "versionId",
        "volumeId",
        "fileId",
        "work_id",
        "version_id",
        "volume_id",
        "file_id",
    }.intersection(payload)


def test_retired_identity_routes_are_unregistered_and_return_404(
    client: TestClient,
) -> None:
    for path in (
        "/api/works/openapi-book",
        "/api/versions/openapi-resource",
        "/api/volumes/openapi-resource",
        "/api/files/openapi-asset",
    ):
        assert client.get(path).status_code == 404, path


def test_openapi_has_no_retired_identity_or_generic_import_task_contracts(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert not any(
        any(segment in path.split("/") for segment in ("works", "versions", "volumes"))
        for path in paths
    )
    assert not any("/import-tasks" in path for path in paths)

    components = schema.get("components", {}).get("schemas", {})
    assert not any(name.startswith("ImportTask") for name in components)
    wire = json.dumps(schema, ensure_ascii=False)
    for token in (
        '"workId"',
        '"versionId"',
        '"volumeId"',
        '"fileId"',
        '"work_id"',
        '"version_id"',
        '"volume_id"',
        '"file_id"',
    ):
        assert token not in wire
