from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import Library, LibraryVersion, LibraryVolume, LibraryWork


def _login_admin(client, db: Session) -> None:
    db.add(
        User(
            id="volume-metadata-admin",
            email="volume-metadata@example.com",
            name="Volume metadata admin",
            password_hash=hash_password("starshipnas"),
            role="admin",
        )
    )
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "volume-metadata@example.com",
            "password": "starshipnas",
        },
    )
    assert response.status_code == 200


def _directory_topology(
    db: Session,
) -> tuple[LibraryWork, LibraryVersion, list[LibraryVolume]]:
    library = Library(
        id="volume-metadata-library",
        name="Volume metadata library",
        root_path="/library/volume-metadata",
        organization_mode="VOLUMES",
    )
    work = LibraryWork(
        id="volume-metadata-work",
        library_id=library.id,
        origin="SCAN",
        source_key="work:example",
        title="Example",
        normalized_title="example",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    version = LibraryVersion(
        id="volume-metadata-version",
        work_id=work.id,
        source_key="version:example/default",
        source_name="Default",
    )
    volumes = [
        LibraryVolume(
            id="volume-metadata-first",
            version_id=version.id,
            origin="SCAN",
            title="01 First",
            sort_order=0,
            format="EPUB",
            resource_key="volume:example/01.epub",
            import_status="COMPLETED",
        ),
        LibraryVolume(
            id="volume-metadata-second",
            version_id=version.id,
            origin="SCAN",
            title="02 Second",
            sort_order=1,
            format="EPUB",
            resource_key="volume:example/02.epub",
            import_status="COMPLETED",
        ),
    ]
    db.add_all([library, work])
    db.flush()
    db.add(version)
    db.flush()
    db.add_all(volumes)
    db.commit()
    return work, version, volumes


def test_volume_metadata_update_preserves_directory_owned_fields(
    client,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work, version, volumes = _directory_topology(db_session)

    response = client.patch(
        f"/api/works/{work.id}/volumes/{volumes[0].id}",
        json={"description": "Curated description", "publisher": "Publisher"},
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    updated = db_session.get(LibraryVolume, volumes[0].id)
    assert updated is not None
    assert updated.description == "Curated description"
    assert updated.publisher == "Publisher"
    assert updated.title == "01 First"
    assert updated.sort_order == 0
    assert updated.version_id == version.id


def test_batch_media_kind_override_preserves_work_version_volume_topology(
    client,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work, version, volumes = _directory_topology(db_session)
    before = (
        db_session.scalar(select(func.count(LibraryWork.id))),
        db_session.scalar(select(func.count(LibraryVersion.id))),
        db_session.scalar(select(func.count(LibraryVolume.id))),
    )

    response = client.post(
        f"/api/works/{work.id}/volumes/batch",
        json={
            "action": "SET_MEDIA_KIND",
            "volumeIds": [volumes[1].id, volumes[0].id],
            "targetMediaKind": "COMIC",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["affectedVolumeIds"] == [volumes[0].id, volumes[1].id]
    assert len(payload["operationIds"]) == 2
    assert "targetWorkIds" not in payload
    assert "deletedWork" not in payload
    db_session.expire_all()
    after = (
        db_session.scalar(select(func.count(LibraryWork.id))),
        db_session.scalar(select(func.count(LibraryVersion.id))),
        db_session.scalar(select(func.count(LibraryVolume.id))),
    )
    assert after == before
    for volume in volumes:
        persisted = db_session.get(LibraryVolume, volume.id)
        assert persisted is not None
        assert persisted.version_id == version.id
        assert persisted.suggested_media_kind == "COMIC"
        assert persisted.classification_source == "USER"


def test_media_kind_undo_does_not_restore_stale_directory_topology(
    client,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work, _version, volumes = _directory_topology(db_session)

    response = client.post(
        f"/api/works/{work.id}/volumes/{volumes[0].id}/reclassify",
        json={"targetMediaKind": "COMIC", "applyTo": "VOLUME"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["affectedVolumeIds"] == [volumes[0].id]
    operation_id = payload["operation"]["id"]
    scanner_version = LibraryVersion(
        id="scanner-authoritative-version",
        work_id=work.id,
        source_key="version:example/scanner-authoritative",
        source_name="Scanner authoritative",
    )
    db_session.add(scanner_version)
    db_session.flush()
    persisted = db_session.get(LibraryVolume, volumes[0].id)
    assert persisted is not None
    persisted.version_id = scanner_version.id
    persisted.resource_key = "volume:example/scanner-authoritative/01.epub"
    persisted.sort_order = 17
    db_session.commit()

    undo_response = client.post(f"/api/library/operations/{operation_id}/undo")

    assert undo_response.status_code == 200, undo_response.text
    db_session.expire_all()
    restored = db_session.get(LibraryVolume, volumes[0].id)
    assert restored is not None
    assert restored.classification_source == "AUTO"
    assert restored.classification_reason == "FORMAT_DEFAULT"
    assert restored.suggested_media_kind is None
    assert restored.version_id == scanner_version.id
    assert restored.resource_key == "volume:example/scanner-authoritative/01.epub"
    assert restored.sort_order == 17


def test_batch_structural_action_is_rejected_by_request_contract(
    client,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    work, _version, volumes = _directory_topology(db_session)

    response = client.post(
        f"/api/works/{work.id}/volumes/batch",
        json={"action": "DELETE", "volumeIds": [volumes[0].id]},
    )

    assert response.status_code == 422
