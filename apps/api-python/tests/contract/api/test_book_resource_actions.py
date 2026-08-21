from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.core.auth import hash_password
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.auth import User


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _node(node_id: str, relative_path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 10,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _add_graph(db_session, book_id: str, resource_id: str) -> None:
    book_node = _node(f"{book_id}-node", f"{book_id}/", directory=True)
    resource_node = _node(f"{resource_id}-node", f"{book_id}/{resource_id}.pdf")
    db_session.add_all([book_node, resource_node])
    db_session.flush()
    db_session.add(
        LibraryBook(id=book_id, library_id="test-library", source_node_id=book_node.id)
    )
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book_id,
            title="Action book",
            normalized_title="action book",
            author="Author",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book_id,
            source_node_id=resource_node.id,
            adapter_id="pdf-file",
            adapter_version="1",
            media_kind="EBOOK",
            format="PDF",
            import_state="READY",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResourceMetadata(resource_id=resource_id, title="Action resource")
    )
    db_session.flush()
    db_session.add(
        LibraryResourceAsset(
            id=f"{resource_id}-asset",
            library_id="test-library",
            resource_id=resource_id,
            source_node_id=resource_node.id,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db_session.flush()


def _login(client, db_session) -> None:
    db_session.add(
        User(
            id="resource-action-admin",
            email="resource-actions@example.com",
            name="Resource actions admin",
            password_hash=hash_password("resource-actions-password"),
            role="admin",
        )
    )
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "resource-actions@example.com",
            "password": "resource-actions-password",
        },
    )
    assert response.status_code == 200, response.text


def test_resource_metadata_update_uses_resource_identity(client, db_session) -> None:
    _login(client, db_session)
    _add_graph(db_session, "metadata-book", "metadata-resource")
    db_session.commit()

    response = client.patch(
        "/api/books/metadata-book/resources/metadata-resource",
        json={"publisher": "New Publisher", "language": "zh-CN"},
    )

    assert response.status_code == 200, response.text
    metadata = db_session.get(LibraryReadableResourceMetadata, "metadata-resource")
    assert metadata is not None
    assert (metadata.publisher, metadata.language) == ("New Publisher", "zh-CN")
    assert response.json()["data"]["resource"]["id"] == "metadata-resource"


def test_book_update_uses_book_mutation_transaction(client, db_session) -> None:
    _login(client, db_session)
    _add_graph(db_session, "update-book", "update-resource")
    db_session.commit()

    response = client.patch(
        "/api/books/update-book",
        json={"title": "Updated book title", "seriesName": "A series"},
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    metadata = db_session.get(LibraryBookMetadata, "update-book")
    assert metadata is not None
    assert (metadata.title, metadata.series_name) == (
        "Updated book title",
        "A series",
    )


def test_resource_cover_regeneration_commits_pending_state_before_enqueue(
    client, db_session
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "cover-book", "cover-resource")
    metadata = db_session.get(LibraryReadableResourceMetadata, "cover-resource")
    assert metadata is not None
    metadata.cover_path = "/covers/old.jpg"
    metadata.cover_status = "READY"
    db_session.commit()

    response = client.post(
        "/api/books/cover-book/resources/cover-resource/cover/regenerate"
    )

    assert response.status_code == 202, response.text
    db_session.expire_all()
    metadata = db_session.get(LibraryReadableResourceMetadata, "cover-resource")
    assert metadata is not None
    assert (metadata.cover_path, metadata.cover_status) == (None, "PENDING")


def test_resource_asset_delete_marks_resource_failed_when_last_asset_is_removed(
    client, db_session
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "delete-book", "delete-resource")
    db_session.commit()

    response = client.delete("/api/assets/delete-resource-asset")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "assetId": "delete-resource-asset",
        "deleted": True,
    }
    resource = db_session.get(LibraryReadableResource, "delete-resource")
    assert resource is not None
    assert resource.import_state == "FAILED"
    assert db_session.get(LibraryResourceAsset, "delete-resource-asset") is None


def test_resource_actions_use_canonical_routes_and_do_not_restore_legacy_paths(
    client, db_session
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "route-book", "route-resource")
    db_session.commit()

    assert client.patch("/api/works/route-book/versions/route-resource", json={}).status_code == 404
    assert (
        client.post(
            "/api/books/route-book/resources/route-resource/cover/regenerate"
        ).status_code
        == 202
    )
    assert (
        client.post("/api/books/route-book/resources/route-resource/rescan").status_code
        == 404
    )
