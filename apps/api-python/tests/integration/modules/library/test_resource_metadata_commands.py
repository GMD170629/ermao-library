from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

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


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 1,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _resource_graph(db: Session) -> tuple[LibraryBook, list[LibraryReadableResource]]:
    book_node = _node("resource-command-book-node", "resource-command/", directory=True)
    book = LibraryBook(
        id="resource-command-book",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    resources: list[LibraryReadableResource] = []
    db.add(book_node)
    db.flush()
    db.add(book)
    db.flush()
    db.add(
        LibraryBookMetadata(
            book_id=book.id,
            title="Resource command book",
            normalized_title="resource command book",
            author="Author",
        )
    )
    db.flush()
    for index in range(2):
        resource_id = f"resource-command-{index + 1}"
        source_node = _node(
            f"{resource_id}-node", f"resource-command/{resource_id}.epub"
        )
        resource = LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book.id,
            source_node_id=source_node.id,
            adapter_id="epub-file",
            adapter_version="1",
            format="EPUB",
            import_state="READY",
        )
        resources.append(resource)
        db.add(source_node)
        db.flush()
        db.add(resource)
        db.flush()
        db.add(
            LibraryReadableResourceMetadata(
                resource_id=resource.id,
                title=f"Resource {index + 1}",
                resource_index=index + 1,
            )
        )
        db.add(
            LibraryResourceAsset(
                id=f"{resource.id}-asset",
                library_id="test-library",
                resource_id=resource.id,
                source_node_id=source_node.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            )
        )
        db.flush()
    return book, resources


def _login_admin(client, db: Session) -> None:
    db.add(
        User(
            id="resource-command-admin",
            email="resource-command@example.com",
            name="Resource command admin",
            password_hash=hash_password("starshipnas"),
            role="admin",
        )
    )
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "resource-command@example.com", "password": "starshipnas"},
    )
    assert response.status_code == 200, response.text


def test_resource_metadata_update_preserves_identity_owned_fields(
    client, db_session: Session
) -> None:
    _login_admin(client, db_session)
    book, resources = _resource_graph(db_session)
    db_session.commit()

    response = client.patch(
        f"/api/books/{book.id}/resources/{resources[0].id}",
        json={"description": "Curated description", "publisher": "Publisher"},
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    updated = db_session.get(LibraryReadableResourceMetadata, resources[0].id)
    assert updated is not None
    assert updated.description == "Curated description"
    assert updated.publisher == "Publisher"
    assert updated.title == "Resource 1"
    assert updated.resource_index == 1
