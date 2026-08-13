from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    ReaderProgressMutation,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = _REPOSITORY_ROOT / "packages" / "reader-contracts" / "fixtures"


def _fixture(name: str) -> dict[str, object]:
    parsed = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _login_and_volume(client: TestClient, session: Session) -> LibraryVolume:
    source_path = (
        _REPOSITORY_ROOT / "test-data" / "library" / "mobi" / "08-zh-hans.azw3"
    )
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    user = User(
        email="reader-v4-exact@example.com",
        name="Reader Exact",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    work = LibraryWork(
        id="exact-work",
        origin="MANUAL",
        title="Exact Reader",
        normalized_title="exact reader",
        tags="[]",
    )
    media = LibraryMediaVersion(id="exact-media", work_id=work.id, media_kind="EBOOK")
    volume = LibraryVolume(
        id="exact-volume",
        media_version_id=media.id,
        title="Exact Volume",
        sort_order=0,
        format="MOBI",
        resource_key="exact:volume",
        import_status="COMPLETED",
    )
    session.add_all(
        [
            user,
            work,
            media,
            volume,
            LibraryFile(
                id="exact-file",
                volume_id=volume.id,
                path=str(source_path),
                fingerprint="exact-file",
                full_hash=source_hash,
                hash_status="COMPLETED",
                mtime_ms=1,
                kind="MOBI",
                mime_type="application/x-mobipocket-ebook",
                size_bytes=source_path.stat().st_size,
                sort_order=0,
            ),
        ]
    )
    session.commit()
    login = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert login.status_code == 200
    return volume


def test_shared_exact_fixture_round_trips_and_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    volume = _login_and_volume(client, db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["data"]["publicationFingerprint"] == {
        "originalFileHash": (
            "sha256:f2b9fdd883430568c161995e80e52fc337ceb417222884c3c782af8202f4c581"
        ),
        "parser": "libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add",
        "normalization": "ermao-mobi-core-v1",
    }

    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["publication"] = bootstrap.json()["data"][
        "publicationFingerprint"
    ]
    first = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)
    replay = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["data"]["revision"] == 1
    assert first.json()["data"]["locator"] == payload["locator"]
    assert db_session.query(LibraryReadingProgress).count() == 1
    assert db_session.query(ReaderProgressMutation).count() == 1


def test_shared_progression_only_fixture_has_stable_exactness_error(
    client: TestClient, db_session: Session
) -> None:
    volume = _login_and_volume(client, db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    payload = _fixture("progression-only-invalid.json")
    payload["locator"]["publication"] = bootstrap["publicationFingerprint"]

    response = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_NOT_EXACT"
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_exact_locator_resource_must_belong_to_the_normalized_publication(
    client: TestClient, db_session: Session
) -> None:
    volume = _login_and_volume(client, db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["publication"] = bootstrap["publicationFingerprint"]
    payload["locator"]["payload"]["href"] = "not-in-reading-order.xhtml"

    response = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_RESOURCE_INVALID"
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_stale_revision_returns_current_exact_snapshot_without_overwrite(
    client: TestClient, db_session: Session
) -> None:
    volume = _login_and_volume(client, db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["publication"] = bootstrap["publicationFingerprint"]
    accepted = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)
    stale = _fixture("exact-reflowable-request.json")
    stale["mutationId"] = "08f57563-4ceb-46bf-a79f-2ca21e5f5ef4"
    stale["baseRevision"] = 0
    stale["locator"]["publication"] = bootstrap["publicationFingerprint"]
    stale["locator"]["payload"]["locations"]["totalProgression"] = 0.9

    conflict = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=stale)

    assert accepted.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"] == {
        "message": "另一设备已更新阅读位置",
        "code": "READER_PROGRESS_CONFLICT",
        "current": accepted.json()["data"],
    }
    stored = db_session.query(LibraryReadingProgress).one()
    assert stored.revision == 1
    assert stored.percent == accepted.json()["data"]["displayPercent"]
