"""HTTP request, SQLite queue, worker, and task detail share one task identity."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.auth import hash_password
from app.core.config import Settings
from app.models import Library, LibraryImportTask
from app.models.auth import User


def test_scan_then_reimport_creates_new_visible_execution(
    client: TestClient, db_session: Session, test_settings: Settings, tmp_path: Path,
) -> None:
    root = tmp_path / "books"
    root.mkdir()
    (root / "one.txt").write_text("Readable content", encoding="utf-8")
    library = db_session.get(Library, "test-library")
    assert library is not None
    library.root_path = str(root)
    library.min_file_size_bytes = 0
    user = User(
        id="reimport-user", email="reimport@example.com", name="Reimport",
        password_hash=hash_password("starshipnas"), role="admin",
    )
    db_session.add(user)
    db_session.commit()
    assert client.post("/api/auth/login", json={
        "email": user.email, "password": "starshipnas",
    }).status_code == 200

    response = client.post("/api/libraries/test-library/scan")
    assert response.status_code == 202, response.text
    scan_id = response.json()["data"]["taskId"]
    worker = build_readable_resource_worker(
        build_readable_resource_pipeline(db_session, test_settings)
    )
    assert worker.process_once() == "scan"
    book = db_session.scalar(select(LibraryImportTask).where(
        LibraryImportTask.kind == "IMPORT_BOOK",
    ))
    assert book is not None and book.state == "QUEUED"
    assert worker.process_once() == "book"
    old_id = book.id
    old_detail = client.get(f"/api/library-import-tasks/{old_id}")
    assert old_detail.status_code == 200
    assert old_detail.json()["data"]["task"]["id"] == old_id
    assert old_detail.json()["data"]["task"]["state"] == "SUCCEEDED"

    response = client.post(f"/api/library-import-tasks/{old_id}/reimport")
    assert response.status_code == 202, response.text
    new_id = response.json()["data"]["taskId"]
    assert new_id not in {scan_id, old_id}
    db_session.expire_all()
    assert db_session.get(LibraryImportTask, old_id).state == "SUCCEEDED"
    assert db_session.get(LibraryImportTask, new_id).state == "QUEUED"
    assert worker.process_once() == "book"
    assert worker.process_once() == "idle"
    db_session.expire_all()
    assert db_session.get(LibraryImportTask, old_id).state == "SUCCEEDED"
    assert db_session.get(LibraryImportTask, new_id).state == "SUCCEEDED"
    new_detail = client.get(f"/api/library-import-tasks/{new_id}")
    assert new_detail.status_code == 200
    assert new_detail.json()["data"]["task"]["id"] == new_id
