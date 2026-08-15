from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
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
from app.modules.reader.presentation.v4_schemas import ReaderProgressPut

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = _REPOSITORY_ROOT / "packages" / "reader-contracts" / "fixtures"


def _fixture(name: str) -> dict[str, object]:
    parsed = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_all_morphology_fixtures_match_the_python_boundary() -> None:
    adapter = TypeAdapter(ReaderProgressPut)
    assert {
        adapter.validate_python(_fixture(name)).locator.kind
        for name in (
            "exact-reflowable-request.json",
            "exact-pdf-request.json",
            "exact-comic-request.json",
            "exact-audio-request.json",
        )
    } == {"reflowable", "pdf", "comic", "audio"}


def test_former_all_readium_v4_envelope_is_rejected() -> None:
    payload = _fixture("exact-reflowable-request.json")
    location = payload["locator"]
    assert isinstance(location, dict)
    engine = location.pop("engineLocator")
    assert isinstance(engine, dict)
    location.update(engine)

    with pytest.raises(ValidationError):
        TypeAdapter(ReaderProgressPut).validate_python(payload)


def _login_and_volume(client: TestClient, session: Session) -> LibraryVolume:
    source_path = (
        _REPOSITORY_ROOT / "test-data" / "library" / "epub" / "reader-v2.epub"
    )
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
        format="EPUB",
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
                mtime_ms=int(source_path.stat().st_mtime * 1000),
                kind="EPUB",
                mime_type="application/epub+zip",
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
    assert "publicationFingerprint" not in bootstrap.json()["data"]

    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["engineLocator"]["payload"]["href"] = "OEBPS/chapter1.xhtml"
    first = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)
    replay = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)

    assert first.status_code == 200, first.json()
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
    payload = _fixture("progression-only-invalid.json")

    response = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_NOT_EXACT"
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_exact_locator_resource_must_belong_to_the_normalized_publication(
    client: TestClient, db_session: Session
) -> None:
    volume = _login_and_volume(client, db_session)
    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["engineLocator"]["payload"]["href"] = "OEBPS/chapter1.xhtml"
    payload["locator"]["engineLocator"]["payload"]["href"] = (
        "not-in-reading-order.xhtml"
    )

    response = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_RESOURCE_INVALID"
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_stale_revision_returns_current_exact_snapshot_without_overwrite(
    client: TestClient, db_session: Session
) -> None:
    volume = _login_and_volume(client, db_session)
    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["engineLocator"]["payload"]["href"] = "OEBPS/chapter1.xhtml"
    accepted = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=payload)
    stale = _fixture("exact-reflowable-request.json")
    stale["mutationId"] = "08f57563-4ceb-46bf-a79f-2ca21e5f5ef4"
    stale["baseRevision"] = 0
    stale["locator"]["engineLocator"]["payload"]["href"] = "OEBPS/chapter1.xhtml"
    stale["locator"]["engineLocator"]["payload"]["locations"]["totalProgression"] = 0.9

    conflict = client.put(f"/api/reader/v4/volumes/{volume.id}/progress", json=stale)

    assert accepted.status_code == 200, accepted.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"] == {
        "message": "另一设备已更新阅读位置",
        "code": "READER_PROGRESS_CONFLICT",
        "current": accepted.json()["data"],
    }
    stored = db_session.query(LibraryReadingProgress).one()
    assert stored.revision == 1
    assert stored.percent == accepted.json()["data"]["displayPercent"]
