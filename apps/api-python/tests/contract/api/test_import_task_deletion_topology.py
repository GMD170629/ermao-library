from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.import_pipeline import ImportTask
from app.models.library import (
    Library,
    LibraryFile,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)


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
    assert response.status_code == 200


def test_deleting_import_task_preserves_directory_owned_topology_and_source(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login_system_manager(client, db_session)
    library_root = tmp_path / "library"
    work_directory = library_root / "The Book"
    work_directory.mkdir(parents=True)
    source_file = work_directory / "The Book.epub"
    source_file.write_bytes(b"publication")

    library = Library(
        id="library",
        name="Library",
        root_path=str(library_root),
        organization_mode="FLAT",
    )
    work = LibraryWork(
        id="work",
        library_id=library.id,
        source_key="The Book",
        title="The Book",
        normalized_title="the book",
        author=None,
        normalized_author=None,
        tags="[]",
    )
    version = LibraryVersion(
        id="version",
        work_id=work.id,
        source_key="__implicit__",
    )
    volume = LibraryVolume(
        id="volume",
        version_id=version.id,
        title="The Book",
        format="EPUB",
        resource_key="The Book.epub",
    )
    library_file = LibraryFile(
        id="file",
        volume_id=volume.id,
        path=str(source_file),
        kind="publication",
        mime_type="application/epub+zip",
        size_bytes=source_file.stat().st_size,
    )
    task = ImportTask(
        id="task",
        library_id=library.id,
        work_id=work.id,
        volume_id=volume.id,
        origin="SCAN",
        status="COMPLETED",
        source_path=str(source_file),
    )
    for row in (library, work, version, volume, library_file, task):
        db_session.add(row)
        db_session.flush()
    db_session.commit()

    response = client.delete("/api/import-tasks/task")

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "data": {"deleted": True, "id": "task"}}
    db_session.expire_all()
    assert db_session.get(ImportTask, task.id) is None
    assert db_session.get(LibraryWork, work.id) is not None
    assert db_session.get(LibraryVersion, version.id) is not None
    assert db_session.get(LibraryVolume, volume.id) is not None
    assert db_session.get(LibraryFile, library_file.id) is not None
    assert source_file.read_bytes() == b"publication"
