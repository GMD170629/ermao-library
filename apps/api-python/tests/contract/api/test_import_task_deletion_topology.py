from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.auth import User


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _login_system_manager(client: TestClient, db: Session) -> None:
    db.add(
        User(
            email="import-deletion@example.com",
            name="Import deletion",
            password_hash=hash_password("ImportDeletion123!"),
            role="admin",
            can_manage_system=True,
        )
    )
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "import-deletion@example.com",
            "password": "ImportDeletion123!",
        },
    )
    assert response.status_code == 200, response.text


def test_import_task_delete_does_not_mutate_source_owned_topology(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Import tasks are not a record-deletion API for Books or Resources."""

    _login_system_manager(client, db_session)
    library_root = tmp_path / "library"
    book_directory = library_root / "The Book"
    book_directory.mkdir(parents=True)
    source_file = book_directory / "The Book.epub"
    source_file.write_bytes(b"publication")
    observed_at = datetime.now(UTC)

    library = Library(
        id="library",
        name="Library",
        root_path=str(library_root),
        organization_mode="FLAT",
    )
    book_node = LibrarySourceNode(
        id="book-node",
        library_id=library.id,
        relative_path="The Book",
        path_key=_path_key("The Book"),
        name="The Book",
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=0,
        observed_at=observed_at,
    )
    asset_node = LibrarySourceNode(
        id="asset-node",
        library_id=library.id,
        parent_id=book_node.id,
        parent_physical_kind="DIRECTORY",
        relative_path="The Book/The Book.epub",
        path_key=_path_key("The Book/The Book.epub"),
        name="The Book.epub",
        physical_kind="REGULAR_FILE",
        observed_size_bytes=source_file.stat().st_size,
        observed_mtime_ns=0,
        observed_at=observed_at,
    )
    book = LibraryBook(
        id="book",
        library_id=library.id,
        source_node_id=book_node.id,
    )
    book_metadata = LibraryBookMetadata(
        book_id=book.id,
        title="The Book",
        normalized_title="the book",
    )
    resource = LibraryReadableResource(
        id="resource",
        library_id=library.id,
        book_id=book.id,
        source_node_id=asset_node.id,
        adapter_id="epub",
        adapter_version="1",
        media_kind="EBOOK",
        format="EPUB",
        import_state="READY",
    )
    resource_metadata = LibraryReadableResourceMetadata(
        resource_id=resource.id,
        title="The Book",
    )
    asset = LibraryResourceAsset(
        id="asset",
        library_id=library.id,
        resource_id=resource.id,
        source_node_id=asset_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
    )
    task = LibraryImportTask(
        id="task",
        kind="IMPORT_ASSET",
        library_id=library.id,
        resource_id=resource.id,
        source_node_id=asset_node.id,
        role="PRIMARY",
        state="SUCCEEDED",
    )
    db_session.add(library)
    db_session.flush()
    db_session.add(book_node)
    db_session.flush()
    db_session.add(asset_node)
    db_session.flush()
    db_session.add(book)
    db_session.flush()
    db_session.add(book_metadata)
    db_session.flush()
    db_session.add(resource)
    db_session.flush()
    db_session.add(resource_metadata)
    db_session.add(asset)
    db_session.flush()
    db_session.add(task)
    db_session.commit()

    response = client.delete("/api/import-tasks/task")

    assert response.status_code == 404, response.text
    db_session.expire_all()
    assert db_session.get(LibraryImportTask, task.id) is not None
    assert db_session.get(LibraryBook, book.id) is not None
    assert db_session.get(LibraryReadableResource, resource.id) is not None
    assert db_session.get(LibraryResourceAsset, asset.id) is not None
    assert db_session.get(LibrarySourceNode, book_node.id) is not None
    assert db_session.get(LibrarySourceNode, asset_node.id) is not None
    assert source_file.read_bytes() == b"publication"
