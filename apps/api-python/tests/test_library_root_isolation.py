from __future__ import annotations

from datetime import UTC, datetime
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
from app.modules.library.application.volume_commands import (
    BatchVolumeCommand,
    CrossLibraryStructuralError,
    LibraryActor,
    VolumeContext,
    batch_volume_resources,
    move_volume_resource,
)
from app.modules.library.infrastructure.batch_volume_commands import (
    _prepare_reparent_batch,
    prepare_batch_volume_mutation,
)
from app.modules.library.infrastructure.implicit_version import (
    IMPLICIT_VERSION_SOURCE_KEY,
)
from app.services.download_executor import DownloadExecutionResult
from app.services.download_queue import process_next_download_task
from app.services.library_management import merge_works
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


def test_merge_works_rejects_cross_library_without_mutation(
    db_session: Session,
) -> None:
    library_a = Library(
        id="merge-lib-a",
        name="A",
        root_path="/merge-a",
        organization_mode="FLAT",
    )
    library_b = Library(
        id="merge-lib-b",
        name="B",
        root_path="/merge-b",
        organization_mode="FLAT",
    )
    work_a, media_a, volume_a = _work(
        work_id="merge-work-a", library_id=library_a.id, title="三体"
    )
    work_b, media_b, volume_b = _work(
        work_id="merge-work-b", library_id=library_b.id, title="三体"
    )
    db_session.add_all([library_a, library_b])
    db_session.flush()
    db_session.add_all([work_a, work_b])
    db_session.flush()
    db_session.add_all(
        [volume_a.version, media_a, volume_a, volume_b.version, media_b, volume_b]
    )
    db_session.commit()

    with pytest.raises(ValueError, match="跨书库"):
        merge_works(db_session, work_a.id, [work_b.id], None)

    db_session.expire_all()
    assert db_session.get(LibraryWork, work_a.id) is not None
    assert db_session.get(LibraryWork, work_b.id) is not None
    assert db_session.get(LibraryMediaVersion, media_b.id) is not None
    assert db_session.get(LibraryVolume, volume_b.id).version_id == volume_b.version_id
    assert db_session.scalar(select(func.count()).select_from(LibraryOperation)) == 0


def test_move_volume_rejects_cross_library_without_mutation(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    library_a = Library(
        id="move-lib-a",
        name="A",
        root_path="/move-a",
        organization_mode="FLAT",
    )
    library_b = Library(
        id="move-lib-b",
        name="B",
        root_path="/move-b",
        organization_mode="FLAT",
    )
    work_a, media_a, volume_a = _work(
        work_id="move-work-a", library_id=library_a.id, title="三体"
    )
    work_b, media_b, volume_b = _work(
        work_id="move-work-b", library_id=library_b.id, title="地球往事"
    )
    db_session.add_all([library_a, library_b])
    db_session.flush()
    db_session.add_all([work_a, work_b])
    db_session.flush()
    db_session.add_all(
        [volume_a.version, media_a, volume_a, volume_b.version, media_b, volume_b]
    )
    db_session.commit()

    moved = client.post(
        f"/api/works/{work_a.id}/volumes/{volume_a.id}/move-to",
        json={"targetWorkId": work_b.id},
    )
    assert moved.status_code == 400
    assert moved.json()["error"]["code"] == "CROSS_LIBRARY_OPERATION"

    db_session.expire_all()
    persisted = db_session.get(LibraryVolume, volume_a.id)
    assert persisted is not None
    assert persisted.version_id == volume_a.version_id
    assert db_session.get(LibraryWork, work_a.id) is not None
    assert db_session.get(LibraryWork, work_b.id) is not None
    assert db_session.scalar(select(func.count()).select_from(LibraryOperation)) == 0


def test_move_volume_resource_rolls_back_cross_library_attempt() -> None:
    class RecordingPort:
        moved = False

        def can_access_work(self, **_kwargs: object) -> bool:
            return True

        def work_library_id(self, *, work_id: str) -> str:
            return "library-a" if work_id == "source-work" else "library-b"

        def get_volume_context(self, **_kwargs: object) -> VolumeContext:
            return VolumeContext(
                id="volume",
                work_id="source-work",
                version_id="media",
                media_kind="EBOOK",
                title="Volume",
                sort_order=0,
                format="EPUB",
                library_id="library-a",
                author=None,
                work_title="Work",
                source_path=Path("volume.epub"),
            )

        def move_volume(self, **_kwargs: object) -> None:
            self.moved = True
            raise AssertionError("cross-library move must not reach persistence")

    class UnitOfWork:
        committed = False
        rolled_back = False

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            self.rolled_back = True

    port = RecordingPort()
    unit_of_work = UnitOfWork()
    actor = LibraryActor(
        user_id="actor",
        can_manage_system=True,
        is_admin=True,
        can_view_manual_imports=True,
        library_ids=(),
    )

    with pytest.raises(CrossLibraryStructuralError):
        move_volume_resource(
            port,
            unit_of_work,
            actor=actor,
            source_work_id="source-work",
            volume_id="volume",
            target_work_id="target-work",
            now=datetime.now(UTC),
        )

    assert port.moved is False
    assert unit_of_work.committed is False
    assert unit_of_work.rolled_back is True


def test_batch_transfer_rejects_cross_library_without_mutation(
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
    assert transferred.json()["error"]["code"] == "CROSS_LIBRARY_OPERATION"

    db_session.expire_all()
    persisted = db_session.get(LibraryVolume, volume_a.id)
    assert persisted is not None
    assert persisted.version_id == volume_a.version_id
    assert db_session.get(LibraryWork, work_a.id) is not None
    assert db_session.get(LibraryWork, work_b.id) is not None
    assert db_session.scalar(select(func.count()).select_from(LibraryOperation)) == 0


def test_batch_transfer_resource_rolls_back_cross_library_attempt() -> None:
    class RecordingPort:
        applied = False

        def can_access_work(self, **_kwargs: object) -> bool:
            return True

        def work_library_id(self, *, work_id: str) -> str:
            return "library-a" if work_id == "source-work" else "library-b"

        def get_volume_context(self, **_kwargs: object) -> VolumeContext:
            return VolumeContext(
                id="volume",
                work_id="source-work",
                version_id="media",
                media_kind="EBOOK",
                title="Volume",
                sort_order=0,
                format="EPUB",
                library_id="library-a",
                author=None,
                work_title="Work",
                source_path=Path("volume.epub"),
            )

        def get_volume_contexts(
            self, *, volume_ids: tuple[str, ...], **kwargs: object
        ) -> tuple[VolumeContext, ...]:
            return tuple(
                self.get_volume_context(volume_id=volume_id, **kwargs)
                for volume_id in volume_ids
            )

        def apply_batch(self, **_kwargs: object) -> None:
            self.applied = True
            raise AssertionError("cross-library batch transfer must not persist")

    class UnitOfWork:
        committed = False
        rolled_back = False

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            self.rolled_back = True

    port = RecordingPort()
    unit_of_work = UnitOfWork()
    actor = LibraryActor(
        user_id="actor",
        can_manage_system=True,
        is_admin=True,
        can_view_manual_imports=True,
        library_ids=(),
    )

    with pytest.raises(CrossLibraryStructuralError, match="CROSS_LIBRARY_OPERATION"):
        batch_volume_resources(
            port,
            unit_of_work,
            actor=actor,
            work_id="source-work",
            command=BatchVolumeCommand(
                action="TRANSFER",
                volume_ids=("volume",),
                target_work_id="target-work",
            ),
            now=datetime.now(UTC),
        )

    assert port.applied is False
    assert unit_of_work.committed is False
    assert unit_of_work.rolled_back is True


def test_batch_transfer_planner_rejects_cross_library(
    db_session: Session,
) -> None:
    work_a, _media_a, volume_a, work_b = _seed_cross_library_volume_pair(
        db_session, prefix="batch-planner"
    )
    now = datetime.now(UTC)
    context = VolumeContext(
        id=volume_a.id,
        work_id=work_a.id,
        version_id=volume_a.version_id,
        media_kind="EBOOK",
        title=volume_a.title,
        sort_order=volume_a.sort_order,
        format=volume_a.format,
        library_id=work_a.library_id,
        author=work_a.author,
        work_title=work_a.title,
        source_path=Path("volume.epub"),
    )
    command = BatchVolumeCommand(
        action="TRANSFER",
        volume_ids=(volume_a.id,),
        target_work_id=work_b.id,
    )

    with pytest.raises(ValueError, match="CROSS_LIBRARY_OPERATION"):
        prepare_batch_volume_mutation(
            db_session,
            actor_id="actor",
            source_work_id=work_a.id,
            contexts=(context,),
            command=command,
            now=now,
        )
    with pytest.raises(ValueError, match="CROSS_LIBRARY_OPERATION"):
        _prepare_reparent_batch(
            db_session,
            actor_id="actor",
            source_work_id=work_a.id,
            target_work_id=work_b.id,
            contexts=(context,),
            now=now,
        )

    db_session.expire_all()
    persisted = db_session.get(LibraryVolume, volume_a.id)
    assert persisted is not None
    assert persisted.version_id == volume_a.version_id
    assert db_session.get(LibraryWork, work_a.id) is not None
    assert db_session.get(LibraryWork, work_b.id) is not None
    assert db_session.scalar(select(func.count()).select_from(LibraryOperation)) == 0
