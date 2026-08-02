from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import ReaderBookmark, User, UserMonitorFolderAccess
from app.models.import_pipeline import ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.models.settings import MonitorFolder
from app.modules.library.application.volume_commands import (
    LibraryActor,
    VolumeContext,
    delete_volume_resource,
)
from app.modules.library.presentation.work_ops import (
    _delete_import_linked_library_scope,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _login_admin(client: TestClient, db: Session) -> User:
    user = User(
        id="volume-structure-admin",
        email="volume-structure@example.com",
        name="Volume Structure",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert response.status_code == 200
    return user


def _volume_aggregate(db: Session, user: User) -> None:
    work = LibraryWork(
        id="delete-volume-work",
        origin="MANUAL",
        title="Delete volume",
        normalized_title="deletevolume",
        author="Author",
        normalized_author="author",
        work_type="BOOK",
        tags="[]",
    )
    media_version = LibraryMediaVersion(
        id="delete-volume-media",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volume = LibraryVolume(
        id="delete-volume-resource",
        media_version_id=media_version.id,
        title="Volume",
        sort_order=0,
        format="EPUB",
        resource_key="manual:delete-volume",
        import_status="COMPLETED",
    )
    file = LibraryFile(
        id="delete-volume-file",
        volume_id=volume.id,
        path="library/delete-volume.epub",
        fingerprint="delete-volume",
        hash_status="COMPLETED",
        mtime_ms=1,
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=1,
        sort_order=0,
    )
    progress = LibraryReadingProgress(
        id="delete-volume-progress",
        user_id=user.id,
        volume_id=volume.id,
        reader_type="epub",
        position="epubcfi(/6/2)",
        percent=25,
        extra="{}",
    )
    bookmark = ReaderBookmark(
        id="delete-volume-bookmark",
        user_id=user.id,
        volume_id=volume.id,
        content_fingerprint="delete-volume",
        bookmark_id="bookmark-1",
        location_json="{}",
        label="Saved",
        percent=25,
        bookmark_created_at="2026-08-01T00:00:00Z",
    )
    task = ImportTask(
        id="delete-volume-import",
        work_id=work.id,
        volume_id=volume.id,
        origin="MANUAL",
        status="COMPLETED",
        source_path="/imports/delete-volume.epub",
    )
    db.add_all([work, media_version, volume, file, progress, bookmark, task])
    db.commit()


def test_delete_last_volume_cascades_and_undo_restores_volume_resources(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _volume_aggregate(db_session, user)

    response = client.delete(
        "/api/works/delete-volume-work/volumes/delete-volume-resource"
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["deletedMediaVersion"] is True
    assert payload["deletedWork"] is True
    assert payload["operation"]["action"] == "DELETE_VOLUME"
    db_session.expire_all()
    assert db_session.get(LibraryWork, "delete-volume-work") is None
    assert db_session.get(LibraryMediaVersion, "delete-volume-media") is None
    assert db_session.get(LibraryVolume, "delete-volume-resource") is None
    assert db_session.get(LibraryFile, "delete-volume-file") is None
    assert db_session.get(LibraryReadingProgress, "delete-volume-progress") is None
    assert db_session.get(ReaderBookmark, "delete-volume-bookmark") is None
    task = db_session.get(ImportTask, "delete-volume-import")
    assert task is not None
    assert task.work_id is None
    assert task.volume_id is None

    undo = client.post(f"/api/library/operations/{payload['operation']['id']}/undo")
    assert undo.status_code == 200
    assert undo.json()["data"]["restored"] is True
    db_session.expire_all()
    assert db_session.get(LibraryWork, "delete-volume-work") is not None
    assert db_session.get(LibraryMediaVersion, "delete-volume-media") is not None
    assert db_session.get(LibraryVolume, "delete-volume-resource") is not None
    assert db_session.get(LibraryFile, "delete-volume-file") is not None
    assert db_session.get(LibraryReadingProgress, "delete-volume-progress") is not None
    assert db_session.get(ReaderBookmark, "delete-volume-bookmark") is not None
    restored_task = db_session.get(ImportTask, "delete-volume-import")
    assert restored_task is not None
    assert restored_task.work_id == "delete-volume-work"
    assert restored_task.volume_id == "delete-volume-resource"


def test_volume_structure_openapi_has_explicit_volume_only_contract(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    path = "/api/works/{work_id}/volumes/{volume_id}"
    assert "delete" in schema["paths"][path]
    assert "requestBody" in schema["paths"][path]["patch"]
    move = schema["paths"][f"{path}/move"]["post"]
    split = schema["paths"][f"{path}/split"]["post"]
    assert "requestBody" in move
    assert "requestBody" in split
    volume_contract = str(
        {
            path: schema["paths"][path],
            f"{path}/move": schema["paths"][f"{path}/move"],
            f"{path}/split": schema["paths"][f"{path}/split"],
        }
    )
    assert "editionId" not in volume_contract
    assert "SplitEdition" not in volume_contract


def test_continue_reading_uses_recent_unfinished_media_and_includes_zero_percent(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    now = datetime.now(UTC)
    work = LibraryWork(
        id="continue-work",
        origin="MANUAL",
        title="Continue",
        normalized_title="continue",
        author="Author",
        normalized_author="author",
        work_type="BOOK",
        tags="[]",
    )
    ebook = LibraryMediaVersion(
        id="continue-ebook",
        work_id=work.id,
        media_kind="EBOOK",
    )
    comic = LibraryMediaVersion(
        id="continue-comic",
        work_id=work.id,
        media_kind="COMIC",
    )
    ebook_volume = LibraryVolume(
        id="continue-ebook-volume",
        media_version_id=ebook.id,
        title="Ebook",
        sort_order=0,
        format="EPUB",
        resource_key="continue:ebook",
        import_status="COMPLETED",
    )
    comic_first = LibraryVolume(
        id="continue-comic-first",
        media_version_id=comic.id,
        title="Comic first",
        sort_order=0,
        format="CBZ",
        resource_key="continue:comic:first",
        import_status="COMPLETED",
    )
    comic_second = LibraryVolume(
        id="continue-comic-second",
        media_version_id=comic.id,
        title="Comic second",
        sort_order=1000,
        format="CBZ",
        resource_key="continue:comic:second",
        import_status="COMPLETED",
    )
    db_session.add_all(
        [
            work,
            ebook,
            comic,
            ebook_volume,
            comic_first,
            comic_second,
            LibraryReadingProgress(
                id="continue-comic-progress",
                user_id=user.id,
                volume_id=comic_second.id,
                reader_type="comic",
                position="5",
                percent=50,
                extra="{}",
                updated_at=now,
            ),
            UserMediaHistory(
                id="continue-ebook-history",
                user_id=user.id,
                media_version_id=ebook.id,
                last_volume_id=ebook_volume.id,
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            ),
            UserMediaHistory(
                id="continue-comic-history",
                user_id=user.id,
                media_version_id=comic.id,
                last_volume_id=comic_second.id,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    db_session.commit()
    history_count = int(
        db_session.scalar(select(func.count()).select_from(UserMediaHistory)) or 0
    )

    response = client.get("/api/dashboard/continue-reading")

    assert response.status_code == 200
    item = response.json()["data"]["item"]
    assert item["mediaKind"] == "COMIC"
    assert item["resumeVolumeId"] == comic_first.id
    assert item["progress"] == 0
    assert (
        int(db_session.scalar(select(func.count()).select_from(UserMediaHistory)) or 0)
        == history_count
    )


def test_import_task_cleanup_uses_volume_target_and_removes_empty_parents(
    db_session: Session,
    test_settings: Settings,
) -> None:
    work = LibraryWork(
        id="import-cleanup-work",
        origin="MANUAL",
        title="Import cleanup",
        normalized_title="importcleanup",
        author="Author",
        normalized_author="author",
        work_type="BOOK",
        tags="[]",
    )
    media = LibraryMediaVersion(
        id="import-cleanup-media",
        work_id=work.id,
        media_kind="EBOOK",
    )
    first = LibraryVolume(
        id="import-cleanup-first",
        media_version_id=media.id,
        title="First",
        sort_order=0,
        format="EPUB",
        resource_key="import-cleanup:first",
        import_status="COMPLETED",
    )
    second = LibraryVolume(
        id="import-cleanup-second",
        media_version_id=media.id,
        title="Second",
        sort_order=1000,
        format="PDF",
        resource_key="import-cleanup:second",
        import_status="COMPLETED",
    )
    db_session.add_all([work, media, first, second])
    db_session.commit()

    first_result = _delete_import_linked_library_scope(
        db_session,
        {"workId": work.id, "volumeId": first.id},
        test_settings,
    )
    db_session.commit()
    assert first_result["deleted"] is True
    assert first_result["deletedWorkRecord"] is False
    assert db_session.get(LibraryWork, work.id) is not None
    assert db_session.get(LibraryMediaVersion, media.id) is not None
    assert db_session.get(LibraryVolume, second.id) is not None

    second_result = _delete_import_linked_library_scope(
        db_session,
        {"workId": work.id, "volumeId": second.id},
        test_settings,
    )
    db_session.commit()
    db_session.expire_all()
    assert second_result["deleted"] is True
    assert second_result["deletedWorkRecord"] is True
    assert db_session.get(LibraryWork, work.id) is None
    assert db_session.get(LibraryMediaVersion, media.id) is None


def test_move_volume_hides_an_unauthorized_target_work(
    client: TestClient,
    db_session: Session,
) -> None:
    user = User(
        id="scoped-volume-manager",
        email="scoped-volume-manager@example.com",
        name="Scoped volume manager",
        password_hash=hash_password("starshipnas"),
        role="member",
        can_manage_system=True,
    )
    source_folder = MonitorFolder(
        id="source-folder",
        name="Source",
        root_path="/source",
    )
    target_folder = MonitorFolder(
        id="target-folder",
        name="Target",
        root_path="/target",
    )
    access = UserMonitorFolderAccess(
        user_id=user.id,
        monitor_folder_id=source_folder.id,
    )

    def aggregate(prefix: str, folder_id: str) -> tuple[LibraryWork, LibraryVolume]:
        work = LibraryWork(
            id=f"{prefix}-work",
            monitor_folder_id=folder_id,
            origin="WATCH",
            title=prefix,
            normalized_title=prefix,
            author="Author",
            normalized_author="author",
            work_type="BOOK",
            tags="[]",
        )
        media = LibraryMediaVersion(
            id=f"{prefix}-media",
            work_id=work.id,
            media_kind="EBOOK",
        )
        volume = LibraryVolume(
            id=f"{prefix}-volume",
            media_version_id=media.id,
            monitor_folder_id=folder_id,
            title=prefix,
            sort_order=0,
            format="EPUB",
            resource_key=f"{prefix}:volume",
            import_status="COMPLETED",
        )
        db_session.add_all([work, media, volume])
        return work, volume

    db_session.add_all([user, source_folder, target_folder, access])
    source_work, source_volume = aggregate("source", source_folder.id)
    target_work, _target_volume = aggregate("target", target_folder.id)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert response.status_code == 200

    move = client.post(
        f"/api/works/{source_work.id}/volumes/{source_volume.id}/move-to",
        json={"targetWorkId": target_work.id},
    )

    assert move.status_code == 404
    assert move.json()["error"]["code"] == "WORK_NOT_FOUND"
    db_session.expire_all()
    persisted = db_session.get(LibraryVolume, source_volume.id)
    assert persisted is not None
    assert persisted.media_version_id == "source-media"


def test_delete_volume_rolls_back_when_persistence_fails() -> None:
    class FailingPort:
        def can_access_work(self, **_kwargs: object) -> bool:
            return True

        def get_volume_context(self, **_kwargs: object) -> VolumeContext:
            return VolumeContext(
                id="volume",
                work_id="work",
                media_version_id="media",
                media_kind="EBOOK",
                title="Volume",
                format="EPUB",
                monitor_folder_id=None,
                author=None,
                source_path=Path("volume.epub"),
            )

        def delete_volume(self, **_kwargs: object) -> None:
            raise RuntimeError("persistence failed")

    class UnitOfWork:
        committed = False
        rolled_back = False

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            self.rolled_back = True

    unit_of_work = UnitOfWork()
    actor = LibraryActor(
        user_id="actor",
        can_manage_system=True,
        is_admin=True,
        can_view_manual_imports=True,
        monitor_folder_ids=(),
    )

    with pytest.raises(RuntimeError, match="persistence failed"):
        delete_volume_resource(
            FailingPort(),
            unit_of_work,
            actor=actor,
            work_id="work",
            volume_id="volume",
            now=datetime.now(UTC),
        )

    assert unit_of_work.rolled_back is True
    assert unit_of_work.committed is False


def test_move_and_split_operations_restore_the_original_volume_parent(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)

    def aggregate(prefix: str) -> tuple[LibraryWork, LibraryVolume]:
        work = LibraryWork(
            id=f"undo-{prefix}-work",
            origin="MANUAL",
            title=prefix,
            normalized_title=prefix,
            author="Author",
            normalized_author="author",
            work_type="BOOK",
            tags="[]",
        )
        media = LibraryMediaVersion(
            id=f"undo-{prefix}-media",
            work_id=work.id,
            media_kind="EBOOK",
        )
        volume = LibraryVolume(
            id=f"undo-{prefix}-volume",
            media_version_id=media.id,
            title=prefix,
            sort_order=0,
            format="EPUB",
            resource_key=f"undo:{prefix}",
            import_status="COMPLETED",
        )
        db_session.add_all([work, media, volume])
        return work, volume

    source_work, source_volume = aggregate("source")
    target_work, _target_volume = aggregate("target")
    db_session.commit()

    moved = client.post(
        f"/api/works/{source_work.id}/volumes/{source_volume.id}/move-to",
        json={"targetWorkId": target_work.id},
    )
    assert moved.status_code == 200
    moved_data = moved.json()["data"]
    db_session.expire_all()
    assert db_session.get(LibraryWork, source_work.id) is None
    assert db_session.get(LibraryVolume, source_volume.id).media_version_id == (
        "undo-target-media"
    )
    undo_move = client.post(
        f"/api/library/operations/{moved_data['operation']['id']}/undo"
    )
    assert undo_move.status_code == 200
    db_session.expire_all()
    assert db_session.get(LibraryWork, source_work.id) is not None
    assert db_session.get(LibraryVolume, source_volume.id).media_version_id == (
        "undo-source-media"
    )

    split = client.post(
        f"/api/works/{source_work.id}/volumes/{source_volume.id}/split",
        json={"title": "Split work"},
    )
    assert split.status_code == 200
    split_data = split.json()["data"]
    split_work_id = split_data["targetWorkId"]
    db_session.expire_all()
    assert db_session.get(LibraryWork, source_work.id) is None
    assert db_session.get(LibraryWork, split_work_id) is not None
    undo_split = client.post(
        f"/api/library/operations/{split_data['operation']['id']}/undo"
    )
    assert undo_split.status_code == 200
    db_session.expire_all()
    assert db_session.get(LibraryWork, source_work.id) is not None
    assert db_session.get(LibraryWork, split_work_id) is None
    assert db_session.get(LibraryVolume, source_volume.id).media_version_id == (
        "undo-source-media"
    )
