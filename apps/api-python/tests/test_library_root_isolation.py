from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models import (
    DownloadTask,
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.auth import User
from app.models.library import Library
from app.services.download_executor import DownloadExecutionResult
from app.services.download_queue import process_next_download_task
from tests.support.import_fixtures import add_library


def _login_admin(client: TestClient, db_session: Session) -> User:
    user = User(
        email="library-root@example.com",
        name="Library Root",
        password_hash=hash_password("starshipnas"),
        role="admin",
        can_manage_system=True,
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert response.status_code == 200
    return user


def _path_key(value: str) -> str:
    return "v1:" + hashlib.sha256(value.encode()).hexdigest()


def _book_graph(
    *,
    book_id: str,
    library_id: str,
    title: str,
) -> tuple[
    LibrarySourceNode,
    LibraryBook,
    LibraryBookMetadata,
    LibrarySourceNode,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
]:
    observed_at = datetime.now(UTC)
    book_source = LibrarySourceNode(
        id=f"source-{book_id}",
        library_id=library_id,
        relative_path=title,
        path_key=_path_key(f"{library_id}/{title}"),
        name=title,
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=1,
        observed_at=observed_at,
        updated_at=observed_at,
    )
    resource_source = LibrarySourceNode(
        id=f"source-{book_id}-resource",
        library_id=library_id,
        relative_path=f"{title}.epub",
        path_key=_path_key(f"{library_id}/{title}.epub"),
        name=f"{title}.epub",
        physical_kind="REGULAR_FILE",
        observed_size_bytes=5,
        observed_mtime_ns=1,
        observed_at=observed_at,
        updated_at=observed_at,
    )
    book = LibraryBook(
        id=book_id,
        library_id=library_id,
        source_node_id=book_source.id,
    )
    book_metadata = LibraryBookMetadata(
        book_id=book.id,
        title=title,
        normalized_title=title.casefold().replace(" ", ""),
        author="刘慈欣",
        normalized_author="刘慈欣",
    )
    resource = LibraryReadableResource(
        id=f"resource-{book_id}",
        library_id=library_id,
        book_id=book.id,
        source_node_id=resource_source.id,
        adapter_id="epub",
        adapter_version="1",
        format="EPUB",
        enablement_state="ENABLED",
        import_state="READY",
    )
    resource_metadata = LibraryReadableResourceMetadata(
        resource_id=resource.id,
        title=title,
        resource_index=0,
    )
    asset = LibraryResourceAsset(
        id=f"asset-{book_id}",
        library_id=library_id,
        resource_id=resource.id,
        source_node_id=resource_source.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
    )
    resource.book = book
    book.source_node = book_source
    resource.source_node = resource_source
    asset.resource = resource
    asset.source_node = resource_source
    return (
        book_source,
        book,
        book_metadata,
        resource_source,
        resource,
        resource_metadata,
        asset,
    )


def _add_book_graph(db_session: Session, graph: tuple[object, ...]) -> None:
    (
        book_source,
        book,
        book_metadata,
        resource_source,
        resource,
        resource_metadata,
        asset,
    ) = graph
    db_session.add_all([book_source, resource_source])
    db_session.flush()
    db_session.add(book)
    db_session.flush()
    db_session.add(book_metadata)
    db_session.add(resource)
    db_session.flush()
    db_session.add(resource_metadata)
    db_session.add(asset)
    db_session.flush()


def test_patch_library_organization_mode_persists_enum_value(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login_admin(client, db_session)
    root = tmp_path / "mode-library"
    root.mkdir()
    created = client.post(
        "/api/libraries",
        json={
            "name": "Mode Library",
            "rootPath": str(root),
            "organizationMode": "FLAT",
            "enabled": True,
        },
    )
    assert created.status_code == 201
    library_id = created.json()["data"]["library"]["id"]
    assert created.json()["data"]["library"]["organizationMode"] == "FLAT"

    patched = client.patch(
        f"/api/libraries/{library_id}",
        json={"organizationMode": "VOLUMES"},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["library"]["organizationMode"] == "VOLUMES"

    listed = client.get("/api/libraries")
    assert listed.status_code == 200
    matching = [
        item for item in listed.json()["data"]["libraries"] if item["id"] == library_id
    ]
    assert len(matching) == 1
    assert matching[0]["organizationMode"] == "VOLUMES"

    db_session.expire_all()
    stored = db_session.get(Library, library_id)
    assert stored is not None
    assert stored.organization_mode == "VOLUMES"
    assert stored.organization_mode != "LibraryOrganizationMode.VOLUMES"

    _add_book_graph(
        db_session,
        _book_graph(
            book_id="mode-library-book", library_id=library_id, title="Mode Book"
        ),
    )
    db_session.commit()
    locked = client.patch(
        f"/api/libraries/{library_id}",
        json={"organizationMode": "FLAT"},
    )
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "LIBRARY_TOPOLOGY_LOCKED"

    invalid = client.patch(
        f"/api/libraries/{library_id}",
        json={"organizationMode": "AUDIOBOOK"},
    )
    assert invalid.status_code == 422


def test_library_scan_request_always_schedules_the_library_root(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login_admin(client, db_session)
    root = tmp_path / "root-scan-library"
    nested = root / "Book" / "Resource"
    nested.mkdir(parents=True)
    library = Library(
        id="root-scan-library",
        name="Root scan library",
        root_path=str(root),
        organization_mode="VOLUMES",
        enabled=True,
        min_file_size_bytes=0,
    )
    db_session.add(library)
    db_session.commit()

    response = client.post(f"/api/libraries/{library.id}/scan")

    assert response.status_code == 202, response.text
    task_payload = response.json()["data"]
    assert task_payload["libraryId"] == library.id
    assert task_payload["enqueued"] is True
    stored = db_session.get(LibraryImportTask, task_payload["taskId"])
    assert stored is not None
    assert stored.library_id == library.id
    assert stored.kind == "SCAN_LIBRARY"
    assert stored.source_node_id is None
    assert stored.resource_id is None


def test_delete_library_cancels_queued_and_running_import_tasks(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login_admin(client, db_session)
    root = tmp_path / "delete-library"
    root.mkdir()
    source_file = root / "book.epub"
    source_file.write_bytes(b"publication")
    library = Library(
        id="delete-library",
        name="Delete library",
        root_path=str(root),
        organization_mode="FLAT",
        enabled=True,
    )
    db_session.add(library)
    db_session.flush()
    db_session.add_all(
        [
            LibraryImportTask(
                id="delete-library-queued",
                kind="SCAN_LIBRARY",
                library_id=library.id,
                state="QUEUED",
            ),
            LibraryImportTask(
                id="delete-library-running",
                kind="SCAN_LIBRARY",
                library_id=library.id,
                state="RUNNING",
                started_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.commit()

    response = client.delete(f"/api/libraries/{library.id}")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"deleted": True, "id": library.id}
    assert db_session.get(Library, library.id) is None
    assert db_session.get(LibraryImportTask, "delete-library-queued") is None
    assert db_session.get(LibraryImportTask, "delete-library-running") is None
    assert source_file.read_bytes() == b"publication"


def test_download_outside_enabled_library_does_not_enqueue_import(
    db_session: Session,
    test_settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloaded = tmp_path / "inbox" / "book.epub"
    downloaded.parent.mkdir()
    downloaded.write_bytes(b"ebook")
    library_root = tmp_path / "library"
    library_root.mkdir()
    add_library(db_session, library_root, library_id="enabled-library")
    task = DownloadTask(
        id="download-outside-library",
        task_type="http",
        status="downloaded",
        display_name="book.epub",
        remote_ref="{}",
        file_path=str(downloaded),
        progress=100,
    )
    db_session.add(task)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.download_queue.next_queued_task",
        lambda _db: {"id": task.id},
    )
    monkeypatch.setattr(
        "app.services.download_queue.execute_download_task",
        lambda _db, _settings, _task_id: DownloadExecutionResult(
            {
                "id": task.id,
                "status": "downloaded",
                "filePath": str(downloaded),
            }
        ),
    )
    assert process_next_download_task(db_session, test_settings) is True
    assert (
        db_session.scalar(select(func.count()).select_from(LibraryImportTask)) or 0
    ) == 0
    stored = db_session.get(DownloadTask, task.id)
    assert stored is not None
    assert stored.status == "downloaded"


def test_download_inside_library_schedules_library_scan_task(
    db_session: Session,
    test_settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    downloaded = library_root / "book.epub"
    downloaded.write_bytes(b"ebook")
    add_library(db_session, library_root, library_id="download-scan-library")
    task = DownloadTask(
        id="download-inside-library",
        task_type="http",
        status="downloaded",
        display_name="book.epub",
        remote_ref="{}",
        file_path=str(downloaded),
        progress=100,
    )
    db_session.add(task)
    db_session.commit()
    monkeypatch.setattr(
        "app.services.download_queue.next_queued_task",
        lambda _db: {"id": task.id},
    )
    monkeypatch.setattr(
        "app.services.download_queue.execute_download_task",
        lambda _db, _settings, _task_id: DownloadExecutionResult(
            {
                "id": task.id,
                "status": "downloaded",
                "filePath": str(downloaded),
            }
        ),
    )

    assert process_next_download_task(db_session, test_settings) is True

    db_session.expire_all()
    stored = db_session.get(DownloadTask, task.id)
    assert stored is not None
    assert stored.status == "importing"
    scan_task = db_session.scalar(
        select(LibraryImportTask).where(
            LibraryImportTask.library_id == "download-scan-library"
        )
    )
    assert scan_task is not None
    assert scan_task.kind == "SCAN_LIBRARY"
    assert scan_task.state == "QUEUED"
    assert db_session.scalar(select(func.count()).select_from(LibraryImportTask)) == 1
