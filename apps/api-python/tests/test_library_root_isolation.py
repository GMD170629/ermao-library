from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap.imports import import_managed_book
from app.core.auth import hash_password
from app.models.auth import User
from app.models.import_pipeline import DownloadTask, ImportTask
from app.models.library import (
    Library,
    LibraryMediaVersion,
    LibraryOperation,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.imports.application.dto import ImportOptions
from app.modules.library.infrastructure.implicit_version import (
    IMPLICIT_VERSION_SOURCE_KEY,
)
from app.services.download_executor import DownloadExecutionResult
from app.services.download_queue import process_next_download_task
from tests.test_worker_importer import add_library, write_epub_metadata_fixture


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


def _work(
    *,
    work_id: str,
    library_id: str,
    title: str,
) -> tuple[LibraryWork, LibraryMediaVersion, LibraryVolume]:
    work = LibraryWork(
        id=work_id,
        library_id=library_id,
        origin="MANUAL",
        title=title,
        normalized_title=title.casefold().replace(" ", ""),
        author="刘慈欣",
        normalized_author="刘慈欣",
        tags="[]",
        merge_key=f"{title.casefold()}:刘慈欣",
    )
    version = LibraryVersion(
        id=f"version-{work_id}",
        work_id=work.id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    media = LibraryMediaVersion(
        id=f"media-{work_id}",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volume = LibraryVolume(
        id=f"volume-{work_id}",
        version_id=version.id,
        title=title,
        sort_order=0,
        format="EPUB",
        resource_key=f"{work_id}:volume",
        import_status="COMPLETED",
    )
    volume.version = version
    return work, media, volume


def _seed_cross_library_volume_pair(
    db_session: Session,
    *,
    prefix: str,
) -> tuple[LibraryWork, LibraryMediaVersion, LibraryVolume, LibraryWork]:
    library_a = Library(
        id=f"{prefix}-lib-a",
        name="A",
        root_path=f"/{prefix}-a",
        organization_mode="FLAT",
    )
    library_b = Library(
        id=f"{prefix}-lib-b",
        name="B",
        root_path=f"/{prefix}-b",
        organization_mode="FLAT",
    )
    work_a, media_a, volume_a = _work(
        work_id=f"{prefix}-work-a", library_id=library_a.id, title="三体"
    )
    work_b, media_b, volume_b = _work(
        work_id=f"{prefix}-work-b", library_id=library_b.id, title="地球往事"
    )
    db_session.add_all([library_a, library_b])
    db_session.flush()
    db_session.add_all([work_a, work_b])
    db_session.flush()
    db_session.add_all(
        [volume_a.version, media_a, volume_a, volume_b.version, media_b, volume_b]
    )
    db_session.commit()
    return work_a, media_a, volume_a, work_b


def test_identical_title_and_merge_key_create_separate_works_per_library(
    db_session: Session,
    test_settings,
    tmp_path: Path,
) -> None:
    library_a_root = tmp_path / "library-a"
    library_b_root = tmp_path / "library-b"
    library_a_root.mkdir()
    library_b_root.mkdir()
    add_library(db_session, library_a_root, folder_id="library-a")
    add_library(db_session, library_b_root, folder_id="library-b")
    book_a = library_a_root / "三体.epub"
    book_b = library_b_root / "三体.epub"
    write_epub_metadata_fixture(book_a, "三体", "刘慈欣")
    write_epub_metadata_fixture(book_b, "三体", "刘慈欣")

    first = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=book_a,
            origin="WATCH",
            original_name=book_a.name,
            library_id="library-a",
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=book_b,
            origin="WATCH",
            original_name=book_b.name,
            library_id="library-b",
        ),
    )

    assert first.work_id != second.work_id
    work_a = db_session.get(LibraryWork, first.work_id)
    work_b = db_session.get(LibraryWork, second.work_id)
    assert work_a is not None and work_b is not None
    assert work_a.title == work_b.title == "三体"
    assert work_a.merge_key == work_b.merge_key
    assert work_a.library_id == "library-a"
    assert work_b.library_id == "library-b"
    assert db_session.scalar(select(func.count()).select_from(LibraryWork)) == 2
    versions = db_session.scalars(select(LibraryVersion)).all()
    assert len(versions) == 2
    assert {version.work_id for version in versions} == {first.work_id, second.work_id}
    assert {version.source_key for version in versions} == {IMPLICIT_VERSION_SOURCE_KEY}
    volume_a = db_session.get(LibraryVolume, first.volume_id)
    volume_b = db_session.get(LibraryVolume, second.volume_id)
    assert volume_a is not None and volume_b is not None
    version_by_work = {version.work_id: version.id for version in versions}
    assert volume_a.version_id == version_by_work[first.work_id]
    assert volume_b.version_id == version_by_work[second.work_id]


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
    add_library(db_session, library_root, folder_id="enabled-library")
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
    enqueue_calls: list[object] = []
    monkeypatch.setattr(
        "app.services.download_queue.enqueue_download_import_command",
        lambda *_args, **kwargs: enqueue_calls.append(kwargs),
    )

    assert process_next_download_task(db_session, test_settings) is True
    assert enqueue_calls == []
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 0
    stored = db_session.get(DownloadTask, task.id)
    assert stored is not None
    assert stored.status == "downloaded"


def test_batch_transfer_is_rejected_without_mutation(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work_a, _media_a, volume_a, work_b = _seed_cross_library_volume_pair(
        db_session, prefix="batch-transfer"
    )

    transferred = client.post(
        f"/api/works/{work_a.id}/volumes/batch",
        json={
            "action": "TRANSFER",
            "volumeIds": [volume_a.id],
            "targetWorkId": work_b.id,
        },
    )
    assert transferred.status_code == 400
    assert transferred.json()["error"]["code"] == "INVALID_BATCH_OPERATION"

    db_session.expire_all()
    persisted = db_session.get(LibraryVolume, volume_a.id)
    assert persisted is not None
    assert persisted.version_id == volume_a.version_id
    assert db_session.get(LibraryWork, work_a.id) is not None
    assert db_session.get(LibraryWork, work_b.id) is not None
    assert db_session.scalar(select(func.count()).select_from(LibraryOperation)) == 0
