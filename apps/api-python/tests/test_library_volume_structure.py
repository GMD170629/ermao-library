import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import ReaderBookmark, User, UserLibraryAccess
from app.models.import_pipeline import ImportTask
from app.models.library import (
    Library,
    LibraryFile,
    LibraryMediaVersion,
    LibraryOperation,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.modules.library.application.volume_commands import (
    BatchVolumeCommand,
    BatchVolumeOutcome,
    LibraryActor,
    OperationSummary,
    VolumeContext,
    VolumeDeleteOutcome,
    batch_volume_resources,
    delete_volume_resource,
)
from app.modules.library.presentation.work_ops import (
    _delete_import_linked_library_scope,
)
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
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


def _ensure_test_library(db: Session) -> None:
    if db.get(Library, "test-library") is None:
        db.add(
            Library(
                id="test-library",
                name="Test Library",
                root_path="/test-library",
                organization_mode="FLAT",
            )
        )
        db.flush()


def _volume_aggregate(db: Session, user: User) -> None:
    _ensure_test_library(db)
    work = LibraryWork(
        library_id="test-library",
        id="delete-volume-work",
        origin="MANUAL",
        title="Delete volume",
        normalized_title="deletevolume",
        author="Author",
        normalized_author="author",
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
    db.add(work)
    db.flush()
    db.add_all([media_version, volume])
    db.flush()
    db.add_all([file, progress, bookmark, task])
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


def test_reclassify_volume_preserves_volume_data_merges_history_and_undoes(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _ensure_test_library(db_session)
    now = datetime.now(UTC)
    work = LibraryWork(
        library_id="test-library",
        id="reclassify-work",
        origin="MANUAL",
        title="Reclassify",
        normalized_title="reclassify",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    ebook = LibraryMediaVersion(
        id="reclassify-ebook", work_id=work.id, media_kind="EBOOK"
    )
    comic = LibraryMediaVersion(
        id="reclassify-comic", work_id=work.id, media_kind="COMIC"
    )
    moved = LibraryVolume(
        id="reclassify-moved",
        media_version_id=ebook.id,
        title="Moved",
        sort_order=0,
        format="EPUB",
        resource_key="reclassify:moved",
        import_status="COMPLETED",
        classification_source="AUTO",
        classification_reason="FORMAT_DEFAULT",
        suggested_media_kind="COMIC",
    )
    remaining = LibraryVolume(
        id="reclassify-remaining",
        media_version_id=ebook.id,
        title="Remaining",
        sort_order=1000,
        format="EPUB",
        resource_key="reclassify:remaining",
        import_status="COMPLETED",
    )
    existing_target = LibraryVolume(
        id="reclassify-target",
        media_version_id=comic.id,
        title="Target",
        sort_order=0,
        format="CBZ",
        resource_key="reclassify:target",
        import_status="COMPLETED",
    )
    progress = LibraryReadingProgress(
        id="reclassify-progress",
        user_id=user.id,
        volume_id=moved.id,
        reader_type="epub",
        position="epubcfi(/6/2)",
        percent=42,
        extra="{}",
    )
    bookmark = ReaderBookmark(
        id="reclassify-bookmark",
        user_id=user.id,
        volume_id=moved.id,
        bookmark_id="bookmark-reclassify",
        location_json="{}",
        label="Saved",
        percent=42,
        bookmark_created_at="2026-08-03T00:00:00Z",
    )
    source_history = UserMediaHistory(
        id="reclassify-source-history",
        user_id=user.id,
        media_version_id=ebook.id,
        last_volume_id=moved.id,
        created_at=now - timedelta(days=2),
        updated_at=now,
    )
    target_history = UserMediaHistory(
        id="reclassify-target-history",
        user_id=user.id,
        media_version_id=comic.id,
        last_volume_id=existing_target.id,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=1),
    )
    db_session.add(work)
    db_session.flush()
    db_session.add_all([ebook, comic])
    db_session.flush()
    db_session.add_all([moved, remaining, existing_target])
    db_session.flush()
    db_session.add_all(
        [
            progress,
            bookmark,
            source_history,
            target_history,
        ]
    )
    db_session.commit()

    response = client.post(
        f"/api/works/{work.id}/volumes/{moved.id}/reclassify",
        json={"targetMediaKind": "COMIC", "applyTo": "VOLUME"},
    )
    assert response.status_code == 200
    operation_id = response.json()["data"]["operation"]["id"]
    db_session.expire_all()
    moved_after = db_session.get(LibraryVolume, moved.id)
    assert moved_after is not None
    assert moved_after.media_version_id == comic.id
    assert moved_after.classification_source == "USER"
    assert moved_after.classification_reason == "USER_OVERRIDE"
    assert moved_after.suggested_media_kind is None
    assert db_session.get(LibraryReadingProgress, progress.id) is not None
    assert db_session.get(ReaderBookmark, bookmark.id) is not None
    source_history_after = db_session.get(UserMediaHistory, source_history.id)
    target_history_after = db_session.get(UserMediaHistory, target_history.id)
    assert source_history_after is not None
    assert source_history_after.last_volume_id == remaining.id
    assert target_history_after is not None
    assert target_history_after.last_volume_id == moved.id

    undo = client.post(f"/api/library/operations/{operation_id}/undo")
    assert undo.status_code == 200
    db_session.expire_all()
    restored = db_session.get(LibraryVolume, moved.id)
    assert restored is not None
    assert restored.media_version_id == ebook.id
    assert restored.classification_source == "AUTO"
    assert restored.suggested_media_kind == "COMIC"
    assert (
        db_session.get(UserMediaHistory, source_history.id).last_volume_id == moved.id
    )
    assert (
        db_session.get(UserMediaHistory, target_history.id).last_volume_id
        == existing_target.id
    )


def test_volume_structure_openapi_has_explicit_volume_only_contract(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    path = "/api/works/{work_id}/volumes/{volume_id}"
    assert "delete" in schema["paths"][path]
    assert "requestBody" in schema["paths"][path]["patch"]
    move = schema["paths"][f"{path}/move"]["post"]
    split = schema["paths"][f"{path}/split"]["post"]
    reclassify = schema["paths"][f"{path}/reclassify"]["post"]
    assert "requestBody" in move
    assert "requestBody" in split
    assert "requestBody" in reclassify
    volume_contract = str(
        {
            path: schema["paths"][path],
            f"{path}/move": schema["paths"][f"{path}/move"],
            f"{path}/split": schema["paths"][f"{path}/split"],
            f"{path}/reclassify": schema["paths"][f"{path}/reclassify"],
        }
    )
    assert "editionId" not in volume_contract
    assert "SplitEdition" not in volume_contract


def _batch_volume_aggregate(
    db: Session,
    *,
    work_id: str,
    volume_ids: tuple[str, ...],
) -> tuple[LibraryWork, list[LibraryVolume]]:
    _ensure_test_library(db)
    work = LibraryWork(
        library_id="test-library",
        id=work_id,
        origin="MANUAL",
        title="Batch work",
        normalized_title=f"batch-{work_id}",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    media = LibraryMediaVersion(
        id=f"{work_id}-ebook",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volumes = [
        LibraryVolume(
            id=volume_id,
            media_version_id=media.id,
            title=f"Volume {index}",
            sort_order=index * 1000,
            format="EPUB",
            resource_key=f"batch:{volume_id}",
            import_status="COMPLETED",
        )
        for index, volume_id in enumerate(volume_ids, start=1)
    ]
    db.add(work)
    db.flush()
    db.add_all([media, *volumes])
    db.commit()
    return work, volumes


def test_batch_reclassify_updates_every_selected_volume_in_one_contract(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work, volumes = _batch_volume_aggregate(
        db_session,
        work_id="batch-reclassify-work",
        volume_ids=("batch-reclassify-one", "batch-reclassify-two"),
    )

    response = client.post(
        f"/api/works/{work.id}/volumes/batch",
        json={
            "action": "SET_MEDIA_KIND",
            "volumeIds": [volumes[1].id, volumes[0].id],
            "targetMediaKind": "COMIC",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["affectedVolumeIds"] == [volumes[0].id, volumes[1].id]
    assert len(payload["operationIds"]) == 2
    db_session.expire_all()
    media_kinds = db_session.scalars(
        select(LibraryMediaVersion.media_kind)
        .join(LibraryVolume)
        .where(LibraryVolume.id.in_([volume.id for volume in volumes]))
    ).all()
    assert media_kinds == ["COMIC", "COMIC"]


def test_batch_prevalidation_rejects_cross_work_selection_without_mutation(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    source, source_volumes = _batch_volume_aggregate(
        db_session,
        work_id="batch-source-work",
        volume_ids=("batch-source-volume",),
    )
    _foreign, foreign_volumes = _batch_volume_aggregate(
        db_session,
        work_id="batch-foreign-work",
        volume_ids=("batch-foreign-volume",),
    )

    response = client.post(
        f"/api/works/{source.id}/volumes/batch",
        json={
            "action": "DELETE",
            "volumeIds": [source_volumes[0].id, foreign_volumes[0].id],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VOLUME_NOT_FOUND"
    db_session.expire_all()
    assert db_session.get(LibraryVolume, source_volumes[0].id) is not None
    assert db_session.get(LibraryVolume, foreign_volumes[0].id) is not None


def test_batch_transfer_split_and_delete_preserve_their_public_results(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    transfer_source, transfer_volumes = _batch_volume_aggregate(
        db_session,
        work_id="batch-transfer-source",
        volume_ids=("batch-transfer-one", "batch-transfer-two"),
    )
    transfer_target, _ = _batch_volume_aggregate(
        db_session,
        work_id="batch-transfer-target",
        volume_ids=("batch-transfer-existing",),
    )

    transfer = client.post(
        f"/api/works/{transfer_source.id}/volumes/batch",
        json={
            "action": "TRANSFER",
            "volumeIds": [volume.id for volume in transfer_volumes],
            "targetWorkId": transfer_target.id,
        },
    )

    assert transfer.status_code == 200
    assert transfer.json()["data"]["deletedWork"] is True
    assert transfer.json()["data"]["targetWorkIds"] == [transfer_target.id]
    db_session.expire_all()
    transferred_work_ids = db_session.scalars(
        select(LibraryMediaVersion.work_id)
        .join(LibraryVolume)
        .where(LibraryVolume.id.in_([volume.id for volume in transfer_volumes]))
    ).all()
    assert transferred_work_ids == [transfer_target.id, transfer_target.id]
    assert db_session.get(LibraryWork, transfer_source.id) is None

    split_source, split_volumes = _batch_volume_aggregate(
        db_session,
        work_id="batch-split-source",
        volume_ids=("batch-split-one", "batch-split-two"),
    )
    split = client.post(
        f"/api/works/{split_source.id}/volumes/batch",
        json={
            "action": "SPLIT",
            "volumeIds": [volume.id for volume in split_volumes],
        },
    )

    assert split.status_code == 200
    split_payload = split.json()["data"]
    assert split_payload["deletedWork"] is True
    assert len(split_payload["targetWorkIds"]) == 2
    db_session.expire_all()
    split_work_ids = set(
        db_session.scalars(
            select(LibraryMediaVersion.work_id)
            .join(LibraryVolume)
            .where(LibraryVolume.id.in_([volume.id for volume in split_volumes]))
        ).all()
    )
    assert split_work_ids == set(split_payload["targetWorkIds"])
    assert db_session.get(LibraryWork, split_source.id) is None

    delete_source, delete_volumes = _batch_volume_aggregate(
        db_session,
        work_id="batch-delete-source",
        volume_ids=("batch-delete-one", "batch-delete-two"),
    )
    deletion = client.post(
        f"/api/works/{delete_source.id}/volumes/batch",
        json={
            "action": "DELETE",
            "volumeIds": [volume.id for volume in delete_volumes],
        },
    )

    assert deletion.status_code == 200
    assert deletion.json()["data"]["deletedWork"] is True
    db_session.expire_all()
    assert db_session.get(LibraryWork, delete_source.id) is None
    assert all(
        db_session.get(LibraryVolume, volume.id) is None for volume in delete_volumes
    )
    assert (
        db_session.scalar(
            select(func.count(LibraryOperation.id)).where(
                LibraryOperation.target_id.in_(
                    [
                        *[volume.id for volume in transfer_volumes],
                        *[volume.id for volume in split_volumes],
                        *[volume.id for volume in delete_volumes],
                    ]
                )
            )
        )
        == 6
    )


def test_batch_set_media_kind_dml_grows_only_at_sqlite_parameter_chunks(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    dml_counts: list[int] = []
    for size in (1, 25, 130):
        work, volumes = _batch_volume_aggregate(
            db_session,
            work_id=f"batch-budget-{size}",
            volume_ids=tuple(f"batch-budget-{size}-{index}" for index in range(size)),
        )
        statements: list[str] = []

        def record_statement(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                statements.append(statement)

        engine = db_session.get_bind()
        event.listen(engine, "before_cursor_execute", record_statement)
        try:
            response = client.post(
                f"/api/works/{work.id}/volumes/batch",
                json={
                    "action": "SET_MEDIA_KIND",
                    "volumeIds": [volume.id for volume in volumes],
                    "targetMediaKind": "COMIC",
                },
            )
        finally:
            event.remove(engine, "before_cursor_execute", record_statement)
        assert response.status_code == 200
        dml_counts.append(len(statements))

    assert dml_counts[1] <= dml_counts[0] + 1
    assert dml_counts[2] <= dml_counts[1] + 2


def test_batch_volume_download_returns_one_ordered_zip(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login_admin(client, db_session)
    work, volumes = _batch_volume_aggregate(
        db_session,
        work_id="batch-download-work",
        volume_ids=("batch-download-one", "batch-download-two"),
    )
    source_dir = test_settings.resolved_storage_root / "library"
    source_dir.mkdir(parents=True, exist_ok=True)
    for index, volume in enumerate(volumes, start=1):
        source = source_dir / f"source-{index}.epub"
        source.write_bytes(f"volume-{index}".encode())
        db_session.add(
            LibraryFile(
                id=f"batch-download-file-{index}",
                volume_id=volume.id,
                path=f"library/{source.name}",
                mtime_ms=index,
                kind="EPUB",
                mime_type="application/epub+zip",
                size_bytes=source.stat().st_size,
                sort_order=0,
            )
        )
    db_session.commit()

    response = client.post(
        f"/api/works/{work.id}/volumes/download",
        json={"volumeIds": [volumes[1].id, volumes[0].id]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "001-Volume 1.epub",
            "002-Volume 2.epub",
        ]
        assert archive.read("001-Volume 1.epub") == b"volume-1"
        assert archive.read("002-Volume 2.epub") == b"volume-2"


def test_batch_volume_download_rejects_a_missing_source_without_partial_archive(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work, volumes = _batch_volume_aggregate(
        db_session,
        work_id="batch-download-missing-work",
        volume_ids=("batch-download-missing-volume",),
    )

    response = client.post(
        f"/api/works/{work.id}/volumes/download",
        json={"volumeIds": [volumes[0].id]},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VOLUME_SOURCE_MISSING"


def test_continue_reading_uses_recent_unfinished_media_and_includes_zero_percent(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _ensure_test_library(db_session)
    now = datetime.now(UTC)
    work = LibraryWork(
        library_id="test-library",
        id="continue-work",
        origin="MANUAL",
        title="Continue",
        normalized_title="continue",
        author="Author",
        normalized_author="author",
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
    db_session.add(work)
    db_session.flush()
    db_session.add_all([ebook, comic])
    db_session.flush()
    db_session.add_all([ebook_volume, comic_first, comic_second])
    db_session.flush()
    db_session.add_all(
        [
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
    _ensure_test_library(db_session)
    work = LibraryWork(
        library_id="test-library",
        id="import-cleanup-work",
        origin="MANUAL",
        title="Import cleanup",
        normalized_title="importcleanup",
        author="Author",
        normalized_author="author",
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
    db_session.add(work)
    db_session.flush()
    db_session.add(media)
    db_session.flush()
    db_session.add_all([first, second])
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
    source_folder = Library(
            organization_mode="FLAT", 
        id="source-folder",
        name="Source",
        root_path="/source",
    )
    target_folder = Library(
            organization_mode="FLAT", 
        id="target-folder",
        name="Target",
        root_path="/target",
    )
    access = UserLibraryAccess(
        user_id=user.id,
        library_id=source_folder.id,
    )

    def aggregate(prefix: str, folder_id: str) -> tuple[LibraryWork, LibraryVolume]:
        work = LibraryWork(
            id=f"{prefix}-work",
            library_id=folder_id,
            origin="WATCH",
            title=prefix,
            normalized_title=prefix,
            author="Author",
            normalized_author="author",
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
            title=prefix,
            sort_order=0,
            format="EPUB",
            resource_key=f"{prefix}:volume",
            import_status="COMPLETED",
        )
        db_session.add(work)
        db_session.flush()
        db_session.add_all([media, volume])
        return work, volume

    db_session.add_all([user, source_folder, target_folder])
    db_session.flush()
    db_session.add(access)
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
                sort_order=0,
                format="EPUB",
                library_id=None,
                author=None,
                work_title="Work",
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
        library_ids=(),
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


def test_batch_volume_operation_rolls_back_after_a_mid_batch_failure() -> None:
    class FailingBatchPort:
        def can_access_work(self, **_kwargs: object) -> bool:
            return True

        def get_volume_context(
            self, *, volume_id: str, **_kwargs: object
        ) -> VolumeContext:
            return VolumeContext(
                id=volume_id,
                work_id="work",
                media_version_id="media",
                media_kind="EBOOK",
                title=volume_id,
                sort_order=0 if volume_id == "one" else 1000,
                format="EPUB",
                library_id=None,
                author="Author",
                work_title="Work",
                source_path=Path(f"{volume_id}.epub"),
            )

        def get_volume_contexts(
            self, *, volume_ids: tuple[str, ...], **kwargs: object
        ) -> tuple[VolumeContext, ...]:
            return tuple(
                self.get_volume_context(volume_id=volume_id, **kwargs)
                for volume_id in volume_ids
            )

        def delete_volume(
            self, *, volume_id: str, **_kwargs: object
        ) -> VolumeDeleteOutcome:
            if volume_id == "two":
                raise RuntimeError("second mutation failed")
            return VolumeDeleteOutcome(
                work_id="work",
                volume_id=volume_id,
                deleted_media_version=False,
                deleted_work=False,
                operation=OperationSummary(
                    id="operation-one",
                    action="DELETE_VOLUME",
                    status="COMPLETED",
                    summary="deleted",
                    expires_at=datetime.now(UTC),
                    undo_available=True,
                ),
            )

        def apply_batch(self, **_kwargs: object) -> BatchVolumeOutcome:
            self.delete_volume(volume_id="one")
            self.delete_volume(volume_id="two")
            raise AssertionError("unreachable")

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
        library_ids=(),
    )

    with pytest.raises(RuntimeError, match="second mutation failed"):
        batch_volume_resources(
            FailingBatchPort(),
            unit_of_work,
            actor=actor,
            work_id="work",
            command=BatchVolumeCommand(
                action="DELETE",
                volume_ids=("one", "two"),
            ),
            now=datetime.now(UTC),
        )

    assert unit_of_work.rolled_back is True
    assert unit_of_work.committed is False


def test_move_and_split_operations_restore_the_original_volume_parent(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    _ensure_test_library(db_session)

    def aggregate(prefix: str) -> tuple[LibraryWork, LibraryVolume]:
        work = LibraryWork(
            library_id="test-library",
            id=f"undo-{prefix}-work",
            origin="MANUAL",
            title=prefix,
            normalized_title=prefix,
            author="Author",
            normalized_author="author",
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
        db_session.add(work)
        db_session.flush()
        db_session.add_all([media, volume])
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
