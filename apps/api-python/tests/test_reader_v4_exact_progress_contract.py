from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import Library, ReaderProgressMutation, ReaderResourceProgress
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.modules.reader.presentation.v4_schemas import ReaderProgressPut

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = _REPOSITORY_ROOT / "packages" / "reader-contracts" / "fixtures"


def _fixture(name: str) -> dict[str, object]:
    parsed = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _path_key(path: str) -> str:
    return f"v1:{hashlib.sha256(path.encode('utf-8')).hexdigest()}"


def _login_and_resource(
    client: TestClient, session: Session
) -> LibraryReadableResource:
    source_path = _REPOSITORY_ROOT / "test-data" / "library" / "epub" / "reader-v2.epub"
    library = session.get(Library, "test-library")
    assert library is not None
    library.root_path = str(source_path.parent)
    user = User(
        id="reader-v4-exact-user",
        email="reader-v4-exact@example.com",
        name="Reader Exact",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    book_node = LibrarySourceNode(
        id="exact-book-node",
        library_id="test-library",
        relative_path="exact-book/",
        path_key=_path_key("exact-book/"),
        name="exact-book",
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=1_000_000,
        observed_at=datetime.now(UTC),
    )
    source_node = LibrarySourceNode(
        id="exact-source-node",
        library_id="test-library",
        relative_path=source_path.name,
        path_key=_path_key(source_path.name),
        name=source_path.name,
        physical_kind="REGULAR_FILE",
        observed_size_bytes=source_path.stat().st_size,
        observed_mtime_ns=int(source_path.stat().st_mtime * 1_000_000_000),
        observed_at=datetime.now(UTC),
    )
    book = LibraryBook(
        id="exact-book",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    book_metadata = LibraryBookMetadata(
        book_id=book.id,
        title="Exact Reader",
        normalized_title="exact reader",
        author="测试作者",
        normalized_author="测试作者",
    )
    resource = LibraryReadableResource(
        id="exact-resource",
        library_id="test-library",
        book_id=book.id,
        source_node_id=source_node.id,
        adapter_id="epub",
        adapter_version="1",
        media_kind="EBOOK",
        format="EPUB",
        enablement_state="ENABLED",
        import_state="READY",
    )
    resource_metadata = LibraryReadableResourceMetadata(
        resource_id=resource.id,
        title="Exact Reader",
    )
    asset = LibraryResourceAsset(
        id="exact-asset",
        library_id="test-library",
        resource_id=resource.id,
        source_node_id=source_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
        sequence_index=0,
        sort_key="0",
    )
    asset_metadata = LibraryResourceAssetMetadata(
        asset_id=asset.id,
        mime_type="application/epub+zip",
    )
    session.add(user)
    session.add_all([book_node, source_node])
    session.flush()
    session.add(book)
    session.flush()
    session.add(book_metadata)
    session.flush()
    session.add(resource)
    session.flush()
    session.add(resource_metadata)
    session.flush()
    session.add(asset)
    session.flush()
    session.add(asset_metadata)
    session.commit()
    login = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert login.status_code == 200
    return resource


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


def test_shared_exact_fixture_round_trips_and_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    resource = _login_and_resource(client, db_session)
    bootstrap = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")
    assert bootstrap.status_code == 200
    assert "publicationFingerprint" not in bootstrap.json()["data"]

    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["engineLocator"]["payload"]["href"] = "OEBPS/chapter1.xhtml"
    first = client.put(f"/api/reader/v4/resources/{resource.id}/progress", json=payload)
    replay = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress", json=payload
    )

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["data"]["revision"] == 1
    assert first.json()["data"]["locator"] == payload["locator"]
    assert db_session.query(ReaderResourceProgress).count() == 1
    assert db_session.query(ReaderProgressMutation).count() == 1


def test_shared_progression_only_fixture_has_stable_exactness_error(
    client: TestClient, db_session: Session
) -> None:
    resource = _login_and_resource(client, db_session)
    payload = _fixture("progression-only-invalid.json")

    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress", json=payload
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_NOT_EXACT"
    assert db_session.query(ReaderResourceProgress).count() == 0


def test_exact_locator_resource_must_belong_to_the_normalized_publication(
    client: TestClient, db_session: Session
) -> None:
    resource = _login_and_resource(client, db_session)
    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["engineLocator"]["payload"]["href"] = (
        "not-in-reading-order.xhtml"
    )

    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress", json=payload
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_RESOURCE_INVALID"
    assert db_session.query(ReaderResourceProgress).count() == 0


def test_stale_revision_returns_current_exact_snapshot_without_overwrite(
    client: TestClient, db_session: Session
) -> None:
    resource = _login_and_resource(client, db_session)
    payload = _fixture("exact-reflowable-request.json")
    payload["baseRevision"] = 0
    payload["locator"]["engineLocator"]["payload"]["href"] = "OEBPS/chapter1.xhtml"
    accepted = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress", json=payload
    )
    stale = _fixture("exact-reflowable-request.json")
    stale["mutationId"] = "08f57563-4ceb-46bf-a79f-2ca21e5f5ef4"
    stale["baseRevision"] = 0
    stale["locator"]["engineLocator"]["payload"]["href"] = "OEBPS/chapter1.xhtml"
    stale["locator"]["engineLocator"]["payload"]["locations"]["totalProgression"] = 0.9

    conflict = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress", json=stale
    )

    assert accepted.status_code == 200, accepted.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"] == {
        "message": "另一设备已更新阅读位置",
        "code": "READER_PROGRESS_CONFLICT",
        "current": accepted.json()["data"],
    }
    stored = db_session.query(ReaderResourceProgress).one()
    assert stored.revision == 1
    assert stored.percent == accepted.json()["data"]["displayPercent"]
