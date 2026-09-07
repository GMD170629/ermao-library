from __future__ import annotations

import copy
import json
import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import Connection, create_engine, event, select
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.core.auth import hash_password
from app.db.base import Base
from app.models import (
    Library,
    ReaderProgressMutationV5,
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
from app.modules.reader.domain.resource_progress import ResourceReadingState
from app.modules.reader.infrastructure.clock import SystemReaderClock
from app.modules.reader.infrastructure.v5_library_queries import (
    SqlAlchemyReaderV5LibraryPresentationQueries,
)
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


def test_v5_late_first_submission_becomes_current_despite_older_capture_time(
    client,
    db_session: Session,
) -> None:
    _seed_reader_resource(client, db_session)

    mutation_m = _payload(
        _MUTATION_A,
        locator={"opaquePosition": {"label": "M"}},
        presentation=_presentation(display_percent=41, total_progression=0.41),
    )
    mutation_m["clientId"] = "reader-v5-api-client-m"
    mutation_m["capturedAtEpochMillis"] = 1_000
    accepted_m = client.put(_progress_url(), json=mutation_m)

    mutation_n = _payload(
        _MUTATION_B,
        locator={
            "href": "OEBPS/Text/newer.xhtml",
            "locations": {"position": 91},
            "engineExtension": {"marker": "N"},
        },
        presentation=_presentation(display_percent=86, total_progression=0.86),
    )
    mutation_n["clientId"] = "reader-v5-api-client-n"
    mutation_n["capturedAtEpochMillis"] = 3_000
    accepted_n = client.put(_progress_url(), json=mutation_n)

    late_locator = {
        "href": "OEBPS/Text/offline.xhtml",
        "locations": {"position": 7, "cssSelector": "#late-c"},
        "text": {"before": "older", "highlight": "", "after": "offline"},
        "unknownOfflineExtension": {
            "path": [{"segment": 1}, None, ""],
            "flags": [],
        },
    }
    late_presentation = _presentation(display_percent=17, total_progression=0.17)
    late_presentation["currentHref"] = "OEBPS/Text/offline.xhtml"
    late_mutation_id = "00000000-0000-4000-8000-000000000003"
    mutation_c = _payload(
        late_mutation_id,
        locator=late_locator,
        presentation=late_presentation,
    )
    mutation_c["clientId"] = "reader-v5-api-client-c"
    mutation_c["capturedAtEpochMillis"] = 2_000
    accepted_c = client.put(_progress_url(), json=mutation_c)

    assert accepted_m.status_code == 200, accepted_m.text
    assert accepted_m.json()["data"]["acceptedRevision"] == 1
    assert accepted_n.status_code == 200, accepted_n.text
    assert accepted_n.json()["data"]["acceptedRevision"] == 2
    assert (
        accepted_n.json()["data"]["currentSnapshot"]["position"]
        == mutation_n["position"]
    )
    assert mutation_c["capturedAtEpochMillis"] < mutation_n["capturedAtEpochMillis"]
    assert accepted_c.status_code == 200, accepted_c.text
    accepted_c_data = accepted_c.json()["data"]
    assert accepted_c_data["acceptedMutationId"] == late_mutation_id
    assert accepted_c_data["acceptedRevision"] == 3
    current_c = accepted_c_data["currentSnapshot"]
    assert set(current_c) == {
        "schemaVersion",
        "revision",
        "clientId",
        "mutationId",
        "capturedAtEpochMillis",
        "receivedAtEpochMillis",
        "position",
    }
    assert current_c["schemaVersion"] == 5
    assert current_c["revision"] == 3
    assert current_c["clientId"] == mutation_c["clientId"]
    assert current_c["mutationId"] == late_mutation_id
    assert current_c["capturedAtEpochMillis"] == 2_000
    assert isinstance(current_c["receivedAtEpochMillis"], int)
    assert current_c["position"] == mutation_c["position"]
    assert current_c["position"]["locator"] == late_locator
    assert current_c["position"]["presentation"] == late_presentation
    assert current_c["position"]["presentation"]["displayPercent"] == 17
    assert (
        accepted_n.json()["data"]["currentSnapshot"]["position"]["presentation"][
            "displayPercent"
        ]
        > current_c["position"]["presentation"]["displayPercent"]
    )

    fetched_c = client.get(_progress_url())
    assert fetched_c.status_code == 200, fetched_c.text
    assert fetched_c.json()["data"]["progressSnapshot"] == current_c

    replayed_m = client.put(_progress_url(), json=copy.deepcopy(mutation_m))
    assert replayed_m.status_code == 200, replayed_m.text
    assert replayed_m.json()["data"]["acceptedMutationId"] == _MUTATION_A
    assert replayed_m.json()["data"]["acceptedRevision"] == 1
    assert replayed_m.json()["data"]["currentSnapshot"] == current_c

    conflicting_m = copy.deepcopy(mutation_m)
    conflicting_m["position"]["locator"] = {"attemptedOverwrite": True}
    conflict = client.put(_progress_url(), json=conflicting_m)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "READER_PROGRESS_MUTATION_REUSE"

    final_get = client.get(_progress_url())
    assert final_get.status_code == 200, final_get.text
    assert final_get.json()["data"]["progressSnapshot"] == current_c

    db_session.expire_all()
    row = db_session.scalar(
        select(ReaderResourceProgressV5).where(
            ReaderResourceProgressV5.resource_id == _RESOURCE_ID
        )
    )
    assert row is not None
    assert row.revision == 3
    assert row.client_id == mutation_c["clientId"]
    assert row.mutation_id == late_mutation_id
    stored_locator = json.loads(row.locator_json)
    assert stored_locator == late_locator
    assert stored_locator["locations"] == {
        "position": 7,
        "cssSelector": "#late-c",
    }
    assert json.loads(row.presentation_json) == late_presentation
    assert row.display_percent == 17
    assert row.total_progression == 0.17
    assert row.current_href == "OEBPS/Text/offline.xhtml"


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


class _UnusedReadingStateQueries:
    def list_reading_states(
        self, *, user_id: str, resource_ids: Sequence[str]
    ) -> Mapping[str, ResourceReadingState]:
        raise AssertionError("saving progress must not load reading-state projections")


def test_v5_storage_failure_rolls_back_application_transaction() -> None:
    unit_of_work = _RecordingUnitOfWork()
    service = ResourceReaderV5Service(
        _FailingRepository(),  # type: ignore[arg-type]
        unit_of_work,  # type: ignore[arg-type]
        _FixedClock(),  # type: ignore[arg-type]
        _UnusedReadingStateQueries(),
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


@pytest.mark.parametrize("first_mutation", [_MUTATION_A, _MUTATION_B], ids=["A", "B"])
def test_v5_concurrent_writes_allocate_monotonic_revisions(
    tmp_path: Path, first_mutation: str
) -> None:
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

    commands = {
        mutation_id: SaveProgressV5Command(
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
            position=ReaderV5PositionDto(
                locator=OpaqueLocator.from_object({"mutation": mutation_id}),
                presentation=ReaderV5PresentationDto(
                    display_percent=display_percent,
                    total_progression=display_percent / 100,
                    current_href=None,
                    chapter=None,
                    page=None,
                    playback=None,
                ),
            ),
        )
        for mutation_id, display_percent in ((_MUTATION_A, 10.0), (_MUTATION_B, 20.0))
    }
    second_mutation = _MUTATION_B if first_mutation == _MUTATION_A else _MUTATION_A
    first_written = Event()
    second_begun = Event()
    first_commit_recorded = Event()
    transaction_events: list[tuple[str, str]] = []

    def write(mutation_id: str) -> int:
        session = SessionLocal()

        @event.listens_for(session, "after_begin")
        def after_begin(
            writer_session: Session,
            transaction: SessionTransaction,
            connection: Connection,
        ) -> None:
            assert writer_session is session
            assert not transaction.nested
            assert connection.in_transaction()
            transaction_events.append(("after_begin", mutation_id))
            if mutation_id == second_mutation:
                assert first_written.is_set()
                assert not first_commit_recorded.is_set()
                second_begun.set()

        @event.listens_for(session, "before_commit")
        def before_commit(writer_session: Session) -> None:
            if mutation_id == first_mutation:
                # The real repository has already executed its SQLite upsert.
                # Read without autoflush so the service still owns receipt flush.
                with writer_session.no_autoflush:
                    written = SqlAlchemyReaderV5Repository(
                        writer_session
                    ).get_v5_progress(
                        commands[mutation_id].user_id, commands[mutation_id].resource_id
                    )
                assert written is not None
                assert written.mutation_id == first_mutation
                assert written.revision == 1
                transaction_events.append(("before_commit", mutation_id))
                first_written.set()
                assert second_begun.wait(10), (
                    "second writer never began its transaction"
                )
            else:
                # SQLite's write lock orders commits. This acknowledgement only
                # prevents callback scheduling from reversing their observation.
                assert first_commit_recorded.wait(10), "first commit was not recorded"
                transaction_events.append(("before_commit", mutation_id))

        @event.listens_for(session, "after_commit")
        def after_commit(writer_session: Session) -> None:
            assert writer_session is session
            transaction_events.append(("after_commit", mutation_id))
            if mutation_id == first_mutation:
                first_commit_recorded.set()

        try:
            if mutation_id == second_mutation:
                assert first_written.wait(10), "first writer never reached pre-commit"
            service = ResourceReaderV5Service(
                SqlAlchemyReaderV5Repository(session),
                session,
                SystemReaderClock(),
                SqlAlchemyReaderV5LibraryPresentationQueries(session),
            )
            return service.save_progress(commands[mutation_id]).accepted_revision
        finally:
            session.close()
            event.remove(session, "after_begin", after_begin)
            event.remove(session, "before_commit", before_commit)
            event.remove(session, "after_commit", after_commit)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                mutation_id: executor.submit(write, mutation_id)
                for mutation_id in (first_mutation, second_mutation)
            }
            try:
                revisions = {
                    mutation_id: future.result(timeout=30)
                    for mutation_id, future in futures.items()
                }
            finally:
                first_written.set()
                second_begun.set()
                first_commit_recorded.set()

        assert transaction_events == [
            ("after_begin", first_mutation),
            ("before_commit", first_mutation),
            ("after_begin", second_mutation),
            ("after_commit", first_mutation),
            ("before_commit", second_mutation),
            ("after_commit", second_mutation),
        ]
        commit_order = [
            mutation_id
            for stage, mutation_id in transaction_events
            if stage == "after_commit"
        ]
        assert commit_order == [first_mutation, second_mutation]
        assert revisions == {commit_order[0]: 1, commit_order[1]: 2}
        winner = commands[commit_order[-1]]
        verify = SessionLocal()
        try:
            final_progress = SqlAlchemyReaderV5Repository(verify).get_v5_progress(
                winner.user_id, winner.resource_id
            )
            assert final_progress is not None
            assert final_progress.revision == 2
            assert final_progress.position == winner.position
            assert (
                final_progress.user_id,
                final_progress.resource_id,
                final_progress.client_id,
                final_progress.mutation_id,
            ) == (
                winner.user_id,
                winner.resource_id,
                winner.client_id,
                winner.mutation_id,
            )
            receipts = verify.scalars(
                select(ReaderProgressMutationV5).where(
                    ReaderProgressMutationV5.user_id == winner.user_id,
                    ReaderProgressMutationV5.resource_id == winner.resource_id,
                )
            ).all()
            assert len(receipts) == 2
            assert {
                receipt.mutation_id: receipt.accepted_revision for receipt in receipts
            } == revisions
            logging.getLogger(__name__).info(
                "POS07 service/SQLite events=%s receipts=%s final_mutation=%s "
                "final_percent=%s complete_position_and_identity=verified",
                transaction_events,
                revisions,
                final_progress.mutation_id,
                final_progress.position.presentation.display_percent,
            )
        finally:
            verify.close()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
