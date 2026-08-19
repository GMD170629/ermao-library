import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import ReaderBookmark, User
from app.models.import_pipeline import ImportTask
from app.models.library import (
    Library,
    LibraryFile,
    LibraryMediaVersion,
    LibraryOperation,
    LibraryReadingProgress,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
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
from app.modules.library.infrastructure.implicit_version import (
    IMPLICIT_VERSION_SOURCE_KEY,
    get_or_create_implicit_version,
)
from app.modules.library.presentation.work_ops import (
    _delete_import_linked_library_scope,
)


def _parent(
    *, id: str, work_id: str, kind: str
) -> tuple[LibraryVersion, LibraryMediaVersion]:
    return (
        LibraryVersion(id=id, work_id=work_id, source_key=IMPLICIT_VERSION_SOURCE_KEY),
        LibraryMediaVersion(id=f"{id}:kind", work_id=work_id, media_kind=kind),
    )


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
    version, media_version = _parent(
        id="delete-volume-media", work_id=work.id, kind="EBOOK"
    )
    volume = LibraryVolume(
        id="delete-volume-resource",
        version_id=version.id,
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
    db.add_all([version, media_version, volume])
    db.flush()
    db.add_all([file, progress, bookmark, task])
    db.commit()


def test_implicit_version_identity_is_unique_per_work(db_session: Session) -> None:
    _ensure_test_library(db_session)
    work = LibraryWork(
        library_id="test-library",
        id="implicit-unique-work",
        origin="MANUAL",
        title="Implicit Unique",
        normalized_title="implicit unique",
        tags="[]",
    )
    db_session.add(work)
    db_session.flush()
    db_session.add(
        LibraryVersion(
            id="implicit-unique-first",
            work_id=work.id,
            source_key=IMPLICIT_VERSION_SOURCE_KEY,
        )
    )
    db_session.flush()
    db_session.add(
        LibraryVersion(
            id="implicit-unique-second",
            work_id=work.id,
            source_key=IMPLICIT_VERSION_SOURCE_KEY,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_get_or_create_implicit_version_is_idempotent(db_session: Session) -> None:
    _ensure_test_library(db_session)
    work = LibraryWork(
        library_id="test-library",
        id="implicit-helper-work",
        origin="MANUAL",
        title="Implicit Helper",
        normalized_title="implicit helper",
        tags="[]",
    )
    db_session.add(work)
    db_session.flush()

    first = get_or_create_implicit_version(db_session, work.id)
    second = get_or_create_implicit_version(db_session, work.id)

    assert first.id == second.id
    count = db_session.scalar(
        select(func.count())
        .select_from(LibraryVersion)
        .where(
            LibraryVersion.work_id == work.id,
            LibraryVersion.source_key == IMPLICIT_VERSION_SOURCE_KEY,
        )
    )
    assert count == 1


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
    assert payload["deletedVersion"] is True
    assert payload["deletedWork"] is True
    assert payload["operation"]["action"] == "DELETE_VOLUME"
    db_session.expire_all()
    assert db_session.get(LibraryWork, "delete-volume-work") is None
    assert db_session.get(LibraryVersion, "delete-volume-media") is None
    assert db_session.get(LibraryMediaVersion, "delete-volume-media:kind") is None
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
    assert db_session.get(LibraryVersion, "delete-volume-media") is not None
    assert db_session.get(LibraryMediaVersion, "delete-volume-media:kind") is not None
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
    version = LibraryVersion(
        id="reclassify-version",
        work_id=work.id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    ebook = LibraryMediaVersion(
        id="reclassify-ebook", work_id=work.id, media_kind="EBOOK"
    )
    comic = LibraryMediaVersion(
        id="reclassify-comic", work_id=work.id, media_kind="COMIC"
    )
    moved = LibraryVolume(
        id="reclassify-moved",
        version_id=version.id,
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
        version_id=version.id,
        title="Remaining",
        sort_order=1000,
        format="EPUB",
        resource_key="reclassify:remaining",
        import_status="COMPLETED",
    )
    existing_target = LibraryVolume(
        id="reclassify-target",
        version_id=version.id,
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
    db_session.add(work)
    db_session.flush()
    db_session.add_all([version, ebook, comic])
    db_session.flush()
    db_session.add_all([moved, remaining, existing_target])
    db_session.flush()
    db_session.add_all([progress, bookmark])
    db_session.commit()

    response = client.post(
        f"/api/works/{work.id}/volumes/{moved.id}/reclassify",
        json={"targetMediaKind": "COMIC", "applyTo": "VOLUME"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["movedVolumeIds"] == [moved.id]
    assert "targetVersionId" not in payload
    assert "sourceVersionId" not in payload
    assert "targetMediaVersionId" not in payload
    operation_id = payload["operation"]["id"]
    db_session.expire_all()
    moved_after = db_session.get(LibraryVolume, moved.id)
    assert moved_after is not None
    assert moved_after.version_id == version.id
    assert moved_after.classification_source == "USER"
    assert moved_after.classification_reason == "USER_OVERRIDE"
    assert moved_after.suggested_media_kind == "COMIC"
    assert db_session.get(LibraryReadingProgress, progress.id) is not None
    assert db_session.get(ReaderBookmark, bookmark.id) is not None

    undo = client.post(f"/api/library/operations/{operation_id}/undo")
    assert undo.status_code == 200
    db_session.expire_all()
    restored = db_session.get(LibraryVolume, moved.id)
    assert restored is not None
    assert restored.version_id == version.id
    assert restored.classification_source == "AUTO"
    assert restored.suggested_media_kind == "COMIC"
    assert db_session.get(LibraryReadingProgress, progress.id) is not None
    assert db_session.get(ReaderBookmark, bookmark.id) is not None


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
    assert f"{path}/move-to" not in schema["paths"]
    assert "editionId" not in volume_contract
    assert "SplitEdition" not in volume_contract
    payloads = schema["components"]["schemas"]
    structure_payload = str(payloads["WorkStructureMutationPayload"])
    reclassify_payload = str(payloads["ReclassifyVolumePayload"])
    reclassify_request = str(payloads["ReclassifyVolumeRequest"])
    assert "sourceVersionId" in structure_payload
    assert "targetVersionId" in structure_payload
    assert "deletedVersion" in structure_payload
    assert "targetMediaVersionId" not in structure_payload
    assert "sourceMediaVersionId" not in structure_payload
    assert "deletedMediaVersion" not in structure_payload
    assert "movedVolumeIds" in reclassify_payload
    assert "targetVersionId" not in reclassify_payload
    assert "SAME_MEDIA_KIND" in reclassify_request
    assert "MEDIA_VERSION" not in reclassify_request
    assert "MoveVolumeRequest" not in payloads
    batch_request = str(payloads["BatchVolumeRequest"])
    assert "TRANSFER" not in batch_request
    assert "targetWorkId" not in batch_request
    openapi_paths = str(schema["paths"])
    assert "move-to" not in openapi_paths
    assert "transfer volume" not in openapi_paths.lower()


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
    version, media = _parent(
        id=f"{work_id}-ebook",
        work_id=work.id,
        kind="EBOOK",
    )
    volumes = [
        LibraryVolume(
            id=volume_id,
            version_id=version.id,
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
    db.add_all([version, media, *volumes])
    db.commit()
    return work, volumes


def _attach_progress_and_bookmark(
    db: Session,
    *,
    user_id: str,
    volume_id: str,
    suffix: str,
) -> tuple[LibraryReadingProgress, ReaderBookmark]:
    progress = LibraryReadingProgress(
        id=f"{suffix}-progress",
        user_id=user_id,
        volume_id=volume_id,
        reader_type="epub",
        position="epubcfi(/6/2)",
        percent=33,
        extra="{}",
    )
    bookmark = ReaderBookmark(
        id=f"{suffix}-bookmark",
        user_id=user_id,
        volume_id=volume_id,
        bookmark_id=f"bookmark-{suffix}",
        location_json="{}",
        label="Saved",
        percent=33,
        bookmark_created_at="2026-08-03T00:00:00Z",
    )
    db.add_all([progress, bookmark])
    db.commit()
    return progress, bookmark


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
        select(LibraryVersion.source_key)
        .join(LibraryVolume, LibraryVolume.version_id == LibraryVersion.id)
        .where(LibraryVolume.id.in_([volume.id for volume in volumes]))
        .order_by(LibraryVolume.id.asc())
    ).all()
    assert media_kinds == [IMPLICIT_VERSION_SOURCE_KEY, IMPLICIT_VERSION_SOURCE_KEY]
    for volume in volumes:
        persisted = db_session.get(LibraryVolume, volume.id)
        assert persisted is not None
        assert persisted.version_id == volume.version_id
        assert persisted.suggested_media_kind == "COMIC"
        assert persisted.classification_source == "USER"


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


def test_batch_transfer_is_rejected_and_split_and_delete_preserve_their_public_results(
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
    source_version_ids = [volume.version_id for volume in transfer_volumes]

    transfer = client.post(
        f"/api/works/{transfer_source.id}/volumes/batch",
        json={
            "action": "TRANSFER",
            "volumeIds": [volume.id for volume in transfer_volumes],
            "targetWorkId": transfer_target.id,
        },
    )

    assert transfer.status_code == 400
    assert transfer.json()["error"]["code"] == "INVALID_BATCH_OPERATION"
    db_session.expire_all()
    persisted_versions = db_session.scalars(
        select(LibraryVolume.version_id).where(
            LibraryVolume.id.in_([volume.id for volume in transfer_volumes])
        )
    ).all()
    assert list(persisted_versions) == source_version_ids
    assert db_session.get(LibraryWork, transfer_source.id) is not None

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
            select(LibraryVersion.work_id)
            .join(LibraryVolume, LibraryVolume.version_id == LibraryVersion.id)
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
                        *[volume.id for volume in split_volumes],
                        *[volume.id for volume in delete_volumes],
                    ]
                )
            )
        )
        == 4
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
            collected: list[str] = statements,
        ) -> None:
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                collected.append(statement)

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


def test_continue_reading_uses_latest_unfinished_progress(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _ensure_test_library(db_session)
    now = datetime.now(UTC)

    def seed_work(
        *,
        work_id: str,
        title: str,
        media_kind: str,
        volume_format: str,
        reader_type: str,
        percent: float,
        updated_at: datetime,
    ) -> LibraryVolume:
        work = LibraryWork(
            library_id="test-library",
            id=work_id,
            origin="MANUAL",
            title=title,
            normalized_title=work_id,
            author="Author",
            normalized_author="author",
            tags="[]",
        )
        version = LibraryVersion(
            id=f"{work_id}-version",
            work_id=work.id,
            source_key=IMPLICIT_VERSION_SOURCE_KEY,
        )
        media = LibraryMediaVersion(
            id=f"{work_id}-media",
            work_id=work.id,
            media_kind=media_kind,
        )
        volume = LibraryVolume(
            id=f"{work_id}-volume",
            version_id=version.id,
            title=title,
            sort_order=0,
            format=volume_format,
            resource_key=f"continue:{work_id}",
            import_status="COMPLETED",
        )
        progress = LibraryReadingProgress(
            id=f"{work_id}-progress",
            user_id=user.id,
            volume_id=volume.id,
            reader_type=reader_type,
            position="1",
            percent=percent,
            extra="{}",
            created_at=updated_at,
            updated_at=updated_at,
        )
        db_session.add(work)
        db_session.flush()
        db_session.add_all([version, media])
        db_session.flush()
        db_session.add(volume)
        db_session.flush()
        db_session.add(progress)
        return volume

    finished = seed_work(
        work_id="continue-finished",
        title="Finished",
        media_kind="EBOOK",
        volume_format="EPUB",
        reader_type="epub",
        percent=100,
        updated_at=now,
    )
    zero = seed_work(
        work_id="continue-zero",
        title="Zero",
        media_kind="COMIC",
        volume_format="CBZ",
        reader_type="comic",
        percent=0,
        updated_at=now - timedelta(hours=1),
    )
    recent = seed_work(
        work_id="continue-recent",
        title="Recent",
        media_kind="EBOOK",
        volume_format="EPUB",
        reader_type="epub",
        percent=40,
        updated_at=now - timedelta(hours=2),
    )
    seed_work(
        work_id="continue-older",
        title="Older",
        media_kind="EBOOK",
        volume_format="EPUB",
        reader_type="epub",
        percent=10,
        updated_at=now - timedelta(hours=3),
    )
    db_session.commit()

    response = client.get("/api/dashboard/continue-reading")

    assert response.status_code == 200
    item = response.json()["data"]["item"]
    assert item["workId"] == "continue-zero"
    assert item["resumeVolumeId"] == zero.id
    assert item["progress"] == 0
    assert item["mediaKind"] == "COMIC"
    assert item["resumeVolumeId"] != finished.id
    assert item["resumeVolumeId"] != recent.id


def test_split_keeps_volume_progress_and_bookmarks(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    split_source, split_volumes = _batch_volume_aggregate(
        db_session,
        work_id="keep-split-source",
        volume_ids=("keep-split-one", "keep-split-two"),
    )
    split_progress, split_bookmark = _attach_progress_and_bookmark(
        db_session,
        user_id=user.id,
        volume_id=split_volumes[0].id,
        suffix="keep-split",
    )
    split = client.post(
        f"/api/works/{split_source.id}/volumes/batch",
        json={
            "action": "SPLIT",
            "volumeIds": [volume.id for volume in split_volumes],
        },
    )
    assert split.status_code == 200
    db_session.expire_all()
    assert db_session.get(LibraryReadingProgress, split_progress.id) is not None
    assert db_session.get(ReaderBookmark, split_bookmark.id) is not None
    assert db_session.get(LibraryReadingProgress, split_progress.id).volume_id == (
        split_volumes[0].id
    )
    assert db_session.get(ReaderBookmark, split_bookmark.id).volume_id == (
        split_volumes[0].id
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
    version, media = _parent(
        id="import-cleanup-media",
        work_id=work.id,
        kind="EBOOK",
    )
    first = LibraryVolume(
        id="import-cleanup-first",
        version_id=version.id,
        title="First",
        sort_order=0,
        format="EPUB",
        resource_key="import-cleanup:first",
        import_status="COMPLETED",
    )
    second = LibraryVolume(
        id="import-cleanup-second",
        version_id=version.id,
        title="Second",
        sort_order=1000,
        format="PDF",
        resource_key="import-cleanup:second",
        import_status="COMPLETED",
    )
    db_session.add(work)
    db_session.flush()
    db_session.add_all([version, media])
    db_session.flush()
    db_session.add_all([first, second])
    db_session.commit()
    version_id = version.id
    media_id = media.id

    first_result = _delete_import_linked_library_scope(
        db_session,
        {"workId": work.id, "volumeId": first.id},
        test_settings,
    )
    db_session.commit()
    assert first_result["deleted"] is True
    assert first_result["deletedWorkRecord"] is False
    assert db_session.get(LibraryWork, work.id) is not None
    assert db_session.get(LibraryVersion, version_id) is not None
    assert db_session.get(LibraryMediaVersion, media_id) is not None
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
    assert db_session.get(LibraryVersion, version_id) is None
    assert db_session.get(LibraryMediaVersion, media_id) is None


def test_move_to_route_does_not_exist(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    source, volumes = _batch_volume_aggregate(
        db_session,
        work_id="move-to-absent-source",
        volume_ids=("move-to-absent-volume",),
    )
    version_id = volumes[0].version_id
    response = client.post(
        f"/api/works/{source.id}/volumes/{volumes[0].id}/move-to",
        json={"targetWorkId": "any-target"},
    )
    assert response.status_code == 404
    db_session.expire_all()
    persisted = db_session.get(LibraryVolume, volumes[0].id)
    assert persisted is not None
    assert persisted.version_id == version_id


def test_delete_volume_rolls_back_when_persistence_fails() -> None:
    class FailingPort:
        def can_access_work(self, **_kwargs: object) -> bool:
            return True

        def get_volume_context(self, **_kwargs: object) -> VolumeContext:
            return VolumeContext(
                id="volume",
                work_id="work",
                version_id="media",
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
                version_id="media",
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
                deleted_version=False,
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


def test_split_operations_restore_the_original_volume_parent(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    _ensure_test_library(db_session)

    work = LibraryWork(
        library_id="test-library",
        id="undo-source-work",
        origin="MANUAL",
        title="source",
        normalized_title="source",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    version, media = _parent(
        id="undo-source-media",
        work_id=work.id,
        kind="EBOOK",
    )
    volume = LibraryVolume(
        id="undo-source-volume",
        version_id=version.id,
        title="source",
        sort_order=0,
        format="EPUB",
        resource_key="undo:source",
        import_status="COMPLETED",
    )
    db_session.add(work)
    db_session.flush()
    db_session.add_all([version, media, volume])
    db_session.commit()

    split = client.post(
        f"/api/works/{work.id}/volumes/{volume.id}/split",
        json={"title": "Split work"},
    )
    assert split.status_code == 200
    split_data = split.json()["data"]
    split_work_id = split_data["targetWorkId"]
    assert split_data["sourceVersionId"] == "undo-source-media"
    assert split_data["targetVersionId"]
    assert split_data["targetVersionId"] != "undo-source-media"
    assert split_data["transferMode"] == "CREATED_VERSION"
    split_inverse = json.loads(
        db_session.get(LibraryOperation, split_data["operation"]["id"]).inverse_json
    )
    assert "sourceVersion" in split_inverse
    assert split_inverse["targetVersionId"] == split_data["targetVersionId"]
    assert split_inverse["targetVersionCreated"] is True
    assert "sourceMediaVersion" not in split_inverse
    db_session.expire_all()
    assert db_session.get(LibraryWork, work.id) is None
    assert db_session.get(LibraryWork, split_work_id) is not None
    undo_split = client.post(
        f"/api/library/operations/{split_data['operation']['id']}/undo"
    )
    assert undo_split.status_code == 200
    db_session.expire_all()
    assert db_session.get(LibraryWork, work.id) is not None
    assert db_session.get(LibraryWork, split_work_id) is None
    assert db_session.get(LibraryVolume, volume.id).version_id == "undo-source-media"


def test_library_volume_belongs_to_library_version(db_session: Session) -> None:
    _ensure_test_library(db_session)
    work = LibraryWork(
        library_id="test-library",
        id="volume-version-work",
        origin="MANUAL",
        title="Version link",
        normalized_title="versionlink",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    version, media = _parent(
        id="volume-version-parent",
        work_id=work.id,
        kind="EBOOK",
    )
    volume = LibraryVolume(
        id="volume-version-volume",
        version_id=version.id,
        title="Linked volume",
        sort_order=0,
        format="EPUB",
        resource_key="volume-version:linked",
        import_status="COMPLETED",
    )
    db_session.add(work)
    db_session.flush()
    db_session.add_all([version, media, volume])
    db_session.commit()
    db_session.expire_all()

    persisted = db_session.get(LibraryVolume, volume.id)
    assert persisted is not None
    assert persisted.version_id == version.id
    assert persisted.version.id == version.id
    assert persisted.version.work_id == work.id
    assert "mediaVersionId" not in LibraryVolume.__table__.c
    assert "versionId" in LibraryVolume.__table__.c
    assert not hasattr(persisted, "media_version_id")


def test_mixed_ebook_and_comic_share_one_implicit_version(
    db_session: Session,
) -> None:
    _ensure_test_library(db_session)
    work = LibraryWork(
        library_id="test-library",
        id="mixed-kind-work",
        origin="MANUAL",
        title="Mixed",
        normalized_title="mixed",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    version = LibraryVersion(
        id="mixed-kind-version",
        work_id=work.id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    ebook = LibraryMediaVersion(
        id="mixed-kind-ebook", work_id=work.id, media_kind="EBOOK"
    )
    comic = LibraryMediaVersion(
        id="mixed-kind-comic", work_id=work.id, media_kind="COMIC"
    )
    db_session.add(work)
    db_session.flush()
    db_session.add_all(
        [
            version,
            ebook,
            comic,
            LibraryVolume(
                id="mixed-kind-epub",
                version_id=version.id,
                title="Ebook",
                sort_order=0,
                format="EPUB",
                resource_key="mixed:ebook",
                import_status="COMPLETED",
            ),
            LibraryVolume(
                id="mixed-kind-cbz",
                version_id=version.id,
                title="Comic",
                sort_order=1000,
                format="CBZ",
                resource_key="mixed:comic",
                import_status="COMPLETED",
            ),
        ]
    )
    db_session.commit()
    versions = list(
        db_session.scalars(
            select(LibraryVersion).where(LibraryVersion.work_id == work.id)
        ).all()
    )
    assert len(versions) == 1
    assert versions[0].source_key == IMPLICIT_VERSION_SOURCE_KEY


def test_set_media_kind_does_not_move_volume_version(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work, volumes = _batch_volume_aggregate(
        db_session,
        work_id="set-kind-version-work",
        volume_ids=("set-kind-volume",),
    )
    volume_id = volumes[0].id
    version_id = volumes[0].version_id
    response = client.post(
        f"/api/works/{work.id}/volumes/{volume_id}/reclassify",
        json={"targetMediaKind": "COMIC", "applyTo": "VOLUME"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["movedVolumeIds"] == [volume_id]
    assert "targetVersionId" not in payload
    db_session.expire_all()
    persisted = db_session.get(LibraryVolume, volume_id)
    assert persisted is not None
    assert persisted.version_id == version_id
    assert persisted.suggested_media_kind == "COMIC"


def test_batch_transfer_leaves_volume_on_source_version(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    source, source_volumes = _batch_volume_aggregate(
        db_session,
        work_id="transfer-implicit-source",
        volume_ids=("transfer-implicit-volume", "transfer-implicit-keep"),
    )
    target, _ = _batch_volume_aggregate(
        db_session,
        work_id="transfer-implicit-target",
        volume_ids=("transfer-implicit-existing",),
    )
    moved_id = source_volumes[0].id
    source_version_id = source_volumes[0].version_id
    response = client.post(
        f"/api/works/{source.id}/volumes/batch",
        json={
            "action": "TRANSFER",
            "volumeIds": [moved_id],
            "targetWorkId": target.id,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_BATCH_OPERATION"
    db_session.expire_all()
    moved = db_session.get(LibraryVolume, moved_id)
    assert moved is not None
    assert moved.version_id == source_version_id
    target_versions = list(
        db_session.scalars(
            select(LibraryVersion).where(LibraryVersion.work_id == target.id)
        ).all()
    )
    assert len(target_versions) == 1
    assert moved.version_id != target_versions[0].id


def test_split_creates_exactly_one_implicit_version_on_new_work(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    source, volumes = _batch_volume_aggregate(
        db_session,
        work_id="split-implicit-source",
        volume_ids=("split-implicit-one", "split-implicit-keep"),
    )
    source_version_id = volumes[0].version_id
    response = client.post(
        f"/api/works/{source.id}/volumes/{volumes[0].id}/split",
        json={"title": "Split implicit work"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    new_work_id = payload["targetWorkId"]
    assert payload["sourceVersionId"] == source_version_id
    assert payload["targetVersionId"]
    assert payload["targetWorkId"] == new_work_id
    assert payload["transferMode"] == "CREATED_VERSION"
    db_session.expire_all()
    new_versions = list(
        db_session.scalars(
            select(LibraryVersion).where(LibraryVersion.work_id == new_work_id)
        ).all()
    )
    assert len(new_versions) == 1
    assert new_versions[0].source_key == IMPLICIT_VERSION_SOURCE_KEY
    moved = db_session.get(LibraryVolume, volumes[0].id)
    assert moved is not None
    assert moved.version_id == new_versions[0].id


def test_production_code_does_not_use_version_source_key_as_media_kind() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    forbidden = (
        'source_key == "EBOOK"',
        'source_key == "COMIC"',
        'source_key == "AUDIOBOOK"',
        "source_key == 'EBOOK'",
        "source_key == 'COMIC'",
        "source_key == 'AUDIOBOOK'",
        'source_key="EBOOK"',
        'source_key="COMIC"',
        'source_key="AUDIOBOOK"',
        "source_key='EBOOK'",
        "source_key='COMIC'",
        "source_key='AUDIOBOOK'",
        "source_key: kind",
        "source_key: target_kind",
        "source_key: target_media_kind",
        "target_kind or ",
    )
    layout = root / "modules" / "library" / "domain" / "layout.py"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path == layout:
            continue
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(root.parent)))
        if "source_key.in_(" in text and "CATALOG_MEDIA_KINDS" in text:
            offenders.append(str(path.relative_to(root.parent)))
        if 'LibraryVersion.source_key.label("media_kind")' in text:
            offenders.append(str(path.relative_to(root.parent)))
    assert offenders == []


def test_reclassify_same_media_kind_updates_matching_volumes_without_moving_version(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    _ensure_test_library(db_session)
    work = LibraryWork(
        library_id="test-library",
        id="same-kind-work",
        origin="MANUAL",
        title="Same kind",
        normalized_title="samekind",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    version, ebook, comic = (
        LibraryVersion(
            id="same-kind-version",
            work_id=work.id,
            source_key=IMPLICIT_VERSION_SOURCE_KEY,
        ),
        LibraryMediaVersion(id="same-kind-ebook", work_id=work.id, media_kind="EBOOK"),
        LibraryMediaVersion(id="same-kind-comic", work_id=work.id, media_kind="COMIC"),
    )
    epub_one = LibraryVolume(
        id="same-kind-epub-one",
        version_id=version.id,
        title="Ebook one",
        sort_order=0,
        format="EPUB",
        resource_key="same-kind:one",
        import_status="COMPLETED",
    )
    epub_two = LibraryVolume(
        id="same-kind-epub-two",
        version_id=version.id,
        title="Ebook two",
        sort_order=1000,
        format="EPUB",
        resource_key="same-kind:two",
        import_status="COMPLETED",
    )
    cbz = LibraryVolume(
        id="same-kind-cbz",
        version_id=version.id,
        title="Comic",
        sort_order=2000,
        format="CBZ",
        resource_key="same-kind:comic",
        import_status="COMPLETED",
    )
    db_session.add(work)
    db_session.flush()
    db_session.add_all([version, ebook, comic, epub_one, epub_two, cbz])
    db_session.commit()

    response = client.post(
        f"/api/works/{work.id}/volumes/{epub_one.id}/reclassify",
        json={"targetMediaKind": "COMIC", "applyTo": "SAME_MEDIA_KIND"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert sorted(payload["movedVolumeIds"]) == [epub_one.id, epub_two.id]
    assert "targetVersionId" not in payload
    db_session.expire_all()
    first = db_session.get(LibraryVolume, epub_one.id)
    second = db_session.get(LibraryVolume, epub_two.id)
    other = db_session.get(LibraryVolume, cbz.id)
    assert first is not None and second is not None and other is not None
    assert first.version_id == version.id
    assert second.version_id == version.id
    assert other.version_id == version.id
    assert first.suggested_media_kind == "COMIC"
    assert second.suggested_media_kind == "COMIC"
    assert other.suggested_media_kind is None


def test_delete_last_volume_of_version_reports_deleted_version_without_deleting_work(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    _ensure_test_library(db_session)
    work = LibraryWork(
        library_id="test-library",
        id="two-version-work",
        origin="MANUAL",
        title="Two versions",
        normalized_title="twoversions",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    keep_version = LibraryVersion(
        id="two-version-keep",
        work_id=work.id,
        source_key="kindle",
        source_name="Kindle",
    )
    gone_version, gone_media = _parent(
        id="two-version-gone", work_id=work.id, kind="EBOOK"
    )
    keep_volume = LibraryVolume(
        id="two-version-keep-volume",
        version_id=keep_version.id,
        title="Keep",
        sort_order=0,
        format="EPUB",
        resource_key="two-version:keep",
        import_status="COMPLETED",
    )
    gone_volume = LibraryVolume(
        id="two-version-gone-volume",
        version_id=gone_version.id,
        title="Gone",
        sort_order=0,
        format="EPUB",
        resource_key="two-version:gone",
        import_status="COMPLETED",
    )
    db_session.add(work)
    db_session.flush()
    db_session.add_all(
        [keep_version, gone_version, gone_media, keep_volume, gone_volume]
    )
    db_session.commit()

    response = client.delete(f"/api/works/{work.id}/volumes/{gone_volume.id}")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["deletedVersion"] is True
    assert payload["deletedWork"] is False
    db_session.expire_all()
    assert db_session.get(LibraryWork, work.id) is not None
    assert db_session.get(LibraryVersion, keep_version.id) is not None
    assert db_session.get(LibraryVersion, gone_version.id) is None
    assert db_session.get(LibraryVolume, keep_volume.id) is not None
    assert db_session.get(LibraryVolume, gone_volume.id) is None


def test_delete_volume_keeps_version_when_siblings_remain(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work, volumes = _batch_volume_aggregate(
        db_session,
        work_id="sibling-version-work",
        volume_ids=("sibling-keep", "sibling-delete"),
    )
    version_id = volumes[0].version_id
    response = client.delete(f"/api/works/{work.id}/volumes/{volumes[1].id}")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["deletedVersion"] is False
    assert payload["deletedWork"] is False
    db_session.expire_all()
    assert db_session.get(LibraryVersion, version_id) is not None
    assert db_session.get(LibraryVolume, volumes[0].id) is not None
    assert db_session.get(LibraryVolume, volumes[1].id) is None


def test_move_to_is_absent_from_openapi_and_returns_not_found(
    client: TestClient,
    db_session: Session,
) -> None:
    schema = client.get("/openapi.json").json()
    assert all("move-to" not in path for path in schema["paths"])
    _login_admin(client, db_session)
    source, source_volumes = _batch_volume_aggregate(
        db_session,
        work_id="move-report-source",
        volume_ids=("move-report-volume", "move-report-keep"),
    )
    response = client.post(
        f"/api/works/{source.id}/volumes/{source_volumes[0].id}/move-to",
        json={"targetWorkId": "move-report-target"},
    )
    assert response.status_code == 404
    db_session.expire_all()
    persisted = db_session.get(LibraryVolume, source_volumes[0].id)
    assert persisted is not None
    assert persisted.version_id == source_volumes[0].version_id


def test_structural_operation_modules_do_not_use_media_version_contract_names() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "modules" / "library"
    forbidden = (
        "sourceMediaVersion",
        "targetMediaVersion",
        "source_media_version_id",
        "target_media_version_id",
        "CREATED_MEDIA_VERSION",
        'applyTo = "MEDIA_VERSION"',
        "deletedMediaVersion",
    )
    paths = (
        root / "application" / "dto.py",
        root / "application" / "volume_commands.py",
        root / "infrastructure" / "structural_operations.py",
        root / "infrastructure" / "volume_commands.py",
        root / "infrastructure" / "batch_volume_commands.py",
        root / "presentation" / "schemas.py",
    )
    offenders: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            offenders.append(str(path))
    assert offenders == []
