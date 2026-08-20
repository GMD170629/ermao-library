from __future__ import annotations

from pathlib import Path

from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import User
from app.models.library import Library, LibraryFile, LibraryVersion, LibraryVolume, LibraryWork


def _login(client, db_session) -> None:
    db_session.add(
        User(
            id="item-action-admin",
            email="item-actions@example.com",
            name="Item actions admin",
            password_hash=hash_password("item-actions-password"),
            role="admin",
        )
    )
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "item-actions@example.com", "password": "item-actions-password"},
    )
    assert response.status_code == 200


def _add_work(db_session, *, work_id: str, root_path: Path | None = None) -> tuple[LibraryWork, LibraryVersion]:
    library = db_session.get(Library, "test-library")
    assert library is not None
    if root_path is not None:
        library.root_path = str(root_path)
    work = LibraryWork(
        id=work_id,
        library_id=library.id,
        origin="SCAN",
        source_key=f"source:{work_id}",
        title="测试作品",
        normalized_title="测试作品",
        author="作者",
        normalized_author="作者",
        tags="[]",
    )
    version = LibraryVersion(
        id=f"{work_id}-version",
        work_id=work.id,
        source_key="version-source",
        source_name="版本一",
    )
    db_session.add_all([work, version])
    db_session.flush()
    return work, version


def _add_volume(db_session, *, version_id: str, volume_id: str, source_path: Path | None = None) -> LibraryVolume:
    volume = LibraryVolume(
        id=volume_id,
        version_id=version_id,
        origin="SCAN",
        title=volume_id,
        sort_order=0,
        format="PDF",
        resource_key=f"resource:{volume_id}",
        import_status="COMPLETED",
        size_bytes=10,
    )
    db_session.add(volume)
    db_session.flush()
    if source_path is not None:
        db_session.add(
            LibraryFile(
                id=f"{volume_id}-file",
                volume_id=volume.id,
                path=str(source_path),
                kind="PDF",
                mime_type="application/pdf",
                size_bytes=10,
                sort_order=0,
            )
        )
    return volume


def test_version_metadata_update_applies_to_every_volume(client, db_session) -> None:
    _login(client, db_session)
    work, version = _add_work(db_session, work_id="metadata-action-work")
    first = _add_volume(db_session, version_id=version.id, volume_id="metadata-volume-1")
    second = _add_volume(db_session, version_id=version.id, volume_id="metadata-volume-2")
    db_session.commit()

    response = client.patch(
        f"/api/works/{work.id}/versions/{version.id}",
        json={"publisher": "新出版社", "language": "zh-CN"},
    )

    assert response.status_code == 200
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.publisher, first.language) == ("新出版社", "zh-CN")
    assert (second.publisher, second.language) == ("新出版社", "zh-CN")


def test_version_cover_regeneration_creates_independent_cover(
    client, db_session, test_settings: Settings
) -> None:
    _login(client, db_session)
    work, version = _add_work(db_session, work_id="cover-action-work")
    volume = _add_volume(db_session, version_id=version.id, volume_id="cover-volume")
    source_cover = test_settings.resolved_storage_root / "covers" / "source.jpg"
    source_cover.parent.mkdir(parents=True, exist_ok=True)
    source_cover.write_bytes(b"cover-bytes")
    volume.cover_path = str(source_cover.relative_to(test_settings.resolved_storage_root))
    volume.cover_status = "READY"
    db_session.commit()

    response = client.post(
        f"/api/works/{work.id}/versions/{version.id}/cover/regenerate"
    )

    assert response.status_code == 200
    db_session.refresh(version)
    assert version.cover_status == "READY"
    assert version.cover_path is not None
    assert (test_settings.resolved_storage_root / version.cover_path).read_bytes() == b"cover-bytes"


def test_volume_source_delete_removes_file_and_last_work(
    client, db_session, tmp_path: Path
) -> None:
    _login(client, db_session)
    library_root = tmp_path / "library-source"
    source_path = library_root / "测试作品" / "第一卷.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"publication")
    work, version = _add_work(
        db_session, work_id="delete-action-work", root_path=library_root
    )
    volume = _add_volume(
        db_session,
        version_id=version.id,
        volume_id="delete-action-volume",
        source_path=source_path,
    )
    db_session.commit()

    response = client.request(
        "DELETE",
        f"/api/works/{work.id}/volumes/{volume.id}/source",
        headers={"Idempotency-Key": "delete-action-1"},
        json={"confirmation": volume.title},
    )

    assert response.status_code == 200
    assert response.json()["data"]["affectedFileCount"] == 1
    assert not source_path.exists()
    db_session.expire_all()
    assert db_session.get(LibraryVolume, volume.id) is None
    assert db_session.get(LibraryVersion, version.id) is None
    assert db_session.get(LibraryWork, work.id) is None

    repeated = client.request(
        "DELETE",
        f"/api/works/{work.id}/volumes/{volume.id}/source",
        headers={"Idempotency-Key": "delete-action-1"},
        json={"confirmation": volume.title},
    )
    assert repeated.status_code == 200
    assert repeated.json() == response.json()
