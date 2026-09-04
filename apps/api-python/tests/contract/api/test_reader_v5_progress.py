from __future__ import annotations

import copy
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password
from app.db.base import Base
from app.models import (
    Library,
    ReaderResourceProgress,
    ReaderResourceProgressV5,
    ReaderResourceReadingStatusV5,
)
from app.models.auth import User
from app.modules.reader.application.dto import ReaderAccessScope
from app.modules.reader.application.resource_reader_v5 import (
    ResourceReaderV5Service,
    SaveProgressV5Command,
)
from app.modules.reader.application.v5_dto import (
    ReaderV5PositionDto,
    ReaderV5PresentationDto,
)
from app.modules.reader.application.v5_locator import OpaqueLocator
from app.modules.reader.infrastructure.clock import SystemReaderClock
from app.modules.reader.infrastructure.v5_repository import (
    SqlAlchemyReaderV5Repository,
)
from tests.contract.api.test_library_smart_filters import _book, _ready_resource

_RESOURCE_ID = "reader-v5-api-resource"
_USER_ID = "reader-v5-api-user"
_PASSWORD = "reader-v5-api-password"
_MUTATION_A = "00000000-0000-4000-8000-000000000001"
_MUTATION_B = "00000000-0000-4000-8000-000000000002"
_MISSING = object()


def _presentation(
    *,
    display_percent: float = 99,
    total_progression: float = 0.25,
) -> dict[str, object]:
    return {
        "displayPercent": display_percent,
        "totalProgression": total_progression,
        "currentHref": "OEBPS/Text/chapter.xhtml",
        "chapter": None,
        "page": None,
        "playback": None,
    }


def _payload(
    mutation_id: str = _MUTATION_A,
    *,
    locator: object = _MISSING,
    presentation: dict[str, object] | None = None,
) -> dict[str, object]:
    if locator is _MISSING:
        locator = {
            "href": "OEBPS/Text/chapter.xhtml",
            "locations": {"totalProgression": 0.25, "vendor": None},
            "text": {"highlight": ""},
            "unknownExtension": {"empty": [], "nullable": None},
        }
    return {
        "schemaVersion": 5,
        "clientId": "reader-v5-api-client",
        "mutationId": mutation_id,
        "capturedAtEpochMillis": 0,
        "position": {
            "locator": locator,
            "presentation": (
                presentation if presentation is not None else _presentation()
            ),
        },
    }


def _seed_reader_resource(client, db: Session):
    user = User(
        id=_USER_ID,
        email="reader-v5-api@example.com",
        name="Reader v5 API",
        password_hash=hash_password(_PASSWORD),
        role="admin",
    )
    db.add(user)
    db.commit()
    _book(db, book_id="reader-v5-api-book", title="Reader v5", author="Author")
    resource = _ready_resource(
        db,
        book_id="reader-v5-api-book",
        resource_id=_RESOURCE_ID,
    )
    db.commit()
    login = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    return user, resource


def _progress_url(resource_id: str = _RESOURCE_ID) -> str:
    return f"/api/reader/v5/resources/{resource_id}/progress"


def test_v5_progress_preserves_opaque_locator_and_client_projection(
    client,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed_reader_resource(client, db_session)
    payload = _payload()

    with caplog.at_level(
        logging.INFO, logger="app.modules.reader.application.resource_reader_v5"
    ):
        response = client.put(_progress_url(), json=payload)

    assert response.status_code == 200, response.text
    snapshot = response.json()["data"]["currentSnapshot"]
    assert response.json()["data"]["acceptedRevision"] == 1
    assert snapshot["position"] == payload["position"]
    assert snapshot["position"]["presentation"]["displayPercent"] == 99
    assert snapshot["position"]["presentation"]["totalProgression"] == 0.25
    assert snapshot["position"]["locator"]["locations"]["totalProgression"] == 0.25
    assert snapshot["position"]["locator"]["text"]["highlight"] == ""
    assert snapshot["position"]["locator"]["unknownExtension"]["nullable"] is None
    assert "reader_v5_progress_accepted" in caplog.text
    assert "unknownExtension" not in caplog.text

    row = db_session.scalar(
        select(ReaderResourceProgressV5).where(
            ReaderResourceProgressV5.resource_id == _RESOURCE_ID
        )
    )
    assert row is not None
    assert "unknownExtension" in row.locator_json
    assert "unknownExtension" not in row.presentation_json


def test_v5_empty_locator_object_is_valid_and_round_trips(
    client, db_session: Session
) -> None:
    _seed_reader_resource(client, db_session)
    response = client.put(
        _progress_url(),
        json=_payload(locator={}),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["currentSnapshot"]["position"]["locator"] == {}


@pytest.mark.parametrize("locator", [None, [], "not-an-object", 7])
def test_v5_locator_must_be_a_json_object(
    client,
    db_session: Session,
    locator: object,
) -> None:
    _seed_reader_resource(client, db_session)
    payload = _payload(locator=locator)

    response = client.put(_progress_url(), json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert db_session.scalar(select(ReaderResourceProgressV5.id)) is None


def test_v5_locator_budget_is_utf8_bytes_and_does_not_include_presentation(
    client,
    db_session: Session,
) -> None:
    _seed_reader_resource(client, db_session)
    oversized = {"x": "a" * 65_530}

    response = client.put(_progress_url(), json=_payload(locator=oversized))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert db_session.scalar(select(ReaderResourceProgressV5.id)) is None


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("position", "presentation", "displayPercent"), float("nan")),
        (("position", "presentation", "totalProgression"), float("inf")),
        (("position", "locator", "nested"), float("nan")),
    ),
)
def test_v5_rejects_non_finite_numbers_before_opaque_mapping(
    client,
    db_session: Session,
    path: tuple[str, ...],
    value: float,
) -> None:
    _seed_reader_resource(client, db_session)
    payload = _payload()
    target: object = payload
    for key in path[:-1]:
        assert isinstance(target, dict)
        target = target[key]
    assert isinstance(target, dict)
    target[path[-1]] = value
    raw = json.dumps(payload, allow_nan=True, separators=(",", ":"))

    response = client.put(
        _progress_url(),
        content=raw,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert db_session.scalar(select(ReaderResourceProgressV5.id)) is None


def test_v5_idempotency_and_reuse_return_original_receipt_and_current_snapshot(
    client,
    db_session: Session,
) -> None:
    _seed_reader_resource(client, db_session)
    first_payload = _payload()
    first = client.put(_progress_url(), json=first_payload)
    replay = client.put(_progress_url(), json=copy.deepcopy(first_payload))
    second_payload = _payload(
        _MUTATION_B,
        locator={"different": True},
        presentation=_presentation(display_percent=42, total_progression=0.42),
    )
    second = client.put(_progress_url(), json=second_payload)
    retry_first = client.put(_progress_url(), json=first_payload)
    reused = copy.deepcopy(first_payload)
    reused["position"]["presentation"] = _presentation(
        display_percent=13, total_progression=0.13
    )
    reuse_response = client.put(_progress_url(), json=reused)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert second.status_code == 200, second.text
    assert replay.json()["data"]["acceptedRevision"] == 1
    assert replay.json()["data"]["currentSnapshot"]["revision"] == 1
    assert second.json()["data"]["acceptedRevision"] == 2
    assert retry_first.status_code == 200, retry_first.text
    assert retry_first.json()["data"]["acceptedRevision"] == 1
    assert (
        retry_first.json()["data"]["currentSnapshot"]
        == second.json()["data"]["currentSnapshot"]
    )
    assert reuse_response.status_code == 409
    assert reuse_response.json()["error"]["code"] == "READER_PROGRESS_MUTATION_REUSE"
    assert db_session.scalar(select(ReaderResourceProgressV5.revision)) == 2


def test_v5_bootstrap_and_progress_use_the_same_snapshot(
    client, db_session: Session
) -> None:
    _seed_reader_resource(client, db_session)
    progress = client.put(_progress_url(), json=_payload())
    progress_snapshot = progress.json()["data"]["currentSnapshot"]

    bootstrap = client.get(f"/api/reader/v5/resources/{_RESOURCE_ID}/bootstrap")
    fetched = client.get(_progress_url())

    assert bootstrap.status_code == 200, bootstrap.text
    assert fetched.status_code == 200, fetched.text
    assert bootstrap.json()["data"]["progressSnapshot"] == progress_snapshot
    assert fetched.json()["data"]["progressSnapshot"] == progress_snapshot
    assert bootstrap.json()["data"]["resourceUrl"] == (
        f"/api/reader/v5/resources/{_RESOURCE_ID}/publication"
    )


def test_v5_reading_status_is_independent_and_does_not_create_locator_snapshot(
    client,
    db_session: Session,
) -> None:
    _seed_reader_resource(client, db_session)

    written = client.put(
        f"/api/reader/v5/resources/{_RESOURCE_ID}/reading-status",
        json={"status": "FINISHED"},
    )
    read = client.get(f"/api/reader/v5/resources/{_RESOURCE_ID}/reading-status")

    assert written.status_code == 200, written.text
    assert read.status_code == 200, read.text
    assert read.json()["data"] == {
        "resourceId": _RESOURCE_ID,
        "status": "FINISHED",
        "percent": 0,
    }
    assert db_session.scalar(select(ReaderResourceProgressV5.id)) is None
    assert db_session.scalar(select(ReaderResourceReadingStatusV5.id)) is not None


def test_v5_ignores_legacy_v4_progress_rows(client, db_session: Session) -> None:
    user, resource = _seed_reader_resource(client, db_session)
    now = datetime.now(UTC)
    db_session.add(
        ReaderResourceProgress(
            id="legacy-v4-progress-row",
            user_id=user.id,
            resource_id=resource.id,
            reader_type="pdf",
            position="legacy-page-88",
            percent=88,
            extra="{}",
            progressed_at=now,
            source_protocol="LEGACY_V4",
            revision=7,
        )
    )
    db_session.commit()

    before = client.get(_progress_url())
    after = client.put(_progress_url(), json=_payload())

    assert before.status_code == 200
    assert before.json()["data"]["progressSnapshot"] is None
    assert after.status_code == 200
    assert (
        db_session.scalar(select(ReaderResourceProgress.id)) == "legacy-v4-progress-row"
    )
    assert db_session.scalar(select(ReaderResourceProgressV5.id)) is not None


class _FailingRepository:
    def is_mutation_conflict(self, error: Exception) -> bool:
        del error
        return False

    def get_visible_context(self, resource_id: str, access_scope: ReaderAccessScope):
        del resource_id, access_scope
        return object()

    def get_v5_mutation(self, user_id: str, resource_id: str, mutation_id: str):
        del user_id, resource_id, mutation_id

    def save_v5_progress(self, **kwargs):
        del kwargs
        raise RuntimeError("injected storage failure")


class _RecordingUnitOfWork:
    committed = 0
    rolled_back = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


def test_v5_storage_failure_rolls_back_application_transaction() -> None:
    unit_of_work = _RecordingUnitOfWork()
    service = ResourceReaderV5Service(
        _FailingRepository(),  # type: ignore[arg-type]
        unit_of_work,  # type: ignore[arg-type]
        _FixedClock(),  # type: ignore[arg-type]
    )
    position = ReaderV5PositionDto(
        locator=OpaqueLocator.from_object({}),
        presentation=ReaderV5PresentationDto(
            display_percent=0,
            total_progression=0,
            current_href=None,
            chapter=None,
            page=None,
            playback=None,
        ),
    )

    with pytest.raises(RuntimeError, match="injected storage failure"):
        service.save_progress(
            SaveProgressV5Command(
                user_id="user",
                resource_id="resource",
                access_scope=ReaderAccessScope(
                    is_admin=True,
                    can_view_manual_imports=True,
                    library_ids=(),
                ),
                client_id="client",
                mutation_id=_MUTATION_A,
                captured_at_epoch_millis=0,
                position=position,
            )
        )

    assert unit_of_work.committed == 0
    assert unit_of_work.rolled_back == 1


def test_v5_concurrent_writes_allocate_monotonic_revisions(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'reader-v5-concurrency.sqlite3'}",
        connect_args={"timeout": 10, "check_same_thread": False},
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    seed = SessionLocal()
    try:
        seed.add(
            Library(
                id="test-library",
                name="Test Library",
                root_path="/test-library",
                organization_mode="FLAT",
            )
        )
        seed.add(
            User(
                id="concurrent-reader-user",
                email="concurrent-reader@example.com",
                name="Concurrent Reader",
                password_hash="unused",
                role="admin",
            )
        )
        seed.commit()
        _book(seed, book_id="concurrent-reader-book", title="Concurrent", author="A")
        _ready_resource(
            seed,
            book_id="concurrent-reader-book",
            resource_id="concurrent-reader-resource",
        )
        seed.commit()
    finally:
        seed.close()

    def write(mutation_id: str, display_percent: float) -> int:
        session = SessionLocal()
        try:
            service = ResourceReaderV5Service(
                SqlAlchemyReaderV5Repository(session),
                session,
                SystemReaderClock(),
            )
            position = ReaderV5PositionDto(
                locator=OpaqueLocator.from_object({"mutation": mutation_id}),
                presentation=ReaderV5PresentationDto(
                    display_percent=display_percent,
                    total_progression=display_percent / 100,
                    current_href=None,
                    chapter=None,
                    page=None,
                    playback=None,
                ),
            )
            result = service.save_progress(
                SaveProgressV5Command(
                    user_id="concurrent-reader-user",
                    resource_id="concurrent-reader-resource",
                    access_scope=ReaderAccessScope(
                        is_admin=True,
                        can_view_manual_imports=True,
                        library_ids=(),
                    ),
                    client_id="concurrent-client",
                    mutation_id=mutation_id,
                    captured_at_epoch_millis=0,
                    position=position,
                )
            )
            return result.accepted_revision
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            revisions = list(
                executor.map(
                    write,
                    (_MUTATION_A, _MUTATION_B),
                    (10.0, 20.0),
                )
            )

        assert sorted(revisions) == [1, 2]
        verify = SessionLocal()
        try:
            row = verify.scalar(
                select(ReaderResourceProgressV5).where(
                    ReaderResourceProgressV5.resource_id == "concurrent-reader-resource"
                )
            )
            assert row is not None
            assert row.revision == 2
        finally:
            verify.close()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
