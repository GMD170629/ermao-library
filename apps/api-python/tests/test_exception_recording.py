from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app.main as app_main
import app.modules.system.presentation.http as system_http
from app.core.auth import hash_password
from app.core.exception_diagnostics import (
    configure_exception_storage,
    persist_exception_diagnostic,
    prepare_exception_diagnostic,
    record_exception,
    reset_exception_storage,
)
from app.models.auth import User
from app.models.settings import SystemEvent
from app.modules.imports.application.readable_resource.ports import (
    LibraryImportTaskRecord,
)
from app.modules.imports.infrastructure.readable_resource.worker import (
    ReadableResourceWorkerProcessor,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

LOGGER = logging.getLogger("tests.exception_recording")


def _session_for(db_session: Session) -> Session:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return factory()


def _load_event(db_session: Session, event_id: str):
    return next((event for event in _all_events(db_session) if event.id == event_id), None)


def _all_events(db_session: Session, source: str | None = None):
    from types import SimpleNamespace
    from app.modules.system.infrastructure.log_files import read_log_events
    return [SimpleNamespace(**{**event, "metadata_json": event["metadata"]})
            for event in read_log_events() if source is None or event["source"] == source]


def test_unhandled_api_exception_records_correlation_and_hides_stack(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("unexpected api failure")

    monkeypatch.setattr(system_http, "app_config_payload", _boom)

    with caplog.at_level(logging.ERROR):
        response = client.get("/api/app-config")

    assert response.status_code == 500
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "RuntimeError"
    assert "Traceback" not in response.text
    assert body["error"]["message"] == "RuntimeError: unexpected api failure"
    assert "X-Error-Id" not in response.headers
    assert "eventId" not in body["error"]["details"]
    diagnostic_id = next(event.id for event in _all_events(db_session) if event.message == "unexpected api failure")

    records = [
        record for record in caplog.records if "unexpected api failure" in record.getMessage()
    ]
    assert records, "unhandled exception must be logged with a traceback"
    assert "_boom" in caplog.text
    # The raw exception must not be attached as exc_info; only the sanitized
    # traceback text is emitted.
    assert all(record.exc_info is None for record in records)

    event = _load_event(db_session, diagnostic_id)
    assert event is not None
    diagnostics = event.metadata_json["diagnostics"]
    assert diagnostics["exceptionType"].endswith("RuntimeError")
    assert "_boom" in diagnostics["traceback"]
    assert event.source == "system"
    assert event.action == "api.request_failed"


def test_record_exception_survives_business_rollback_and_storage_failure(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def factory() -> Session:
        return _session_for(db_session)

    configure_exception_storage(factory)
    try:
        try:
            raise ValueError("business-path-failure")
        except ValueError as error:
            diagnostic_id = record_exception(
                LOGGER,
                "unit.business_failure",
                error,

            )

        # A later business rollback must not remove the diagnostic event.
        db_session.rollback()
        event = _load_event(db_session, diagnostic_id)
        assert event is not None
        assert "libraryId" not in event.metadata_json
        assert "business-path-failure" in event.metadata_json["diagnostics"]["traceback"]
    finally:
        reset_exception_storage()

    def _broken_factory():
        raise RuntimeError("storage unavailable")

    configure_exception_storage(_broken_factory)
    try:
        with caplog.at_level(logging.WARNING):
            try:
                raise RuntimeError("original-failure")
            except RuntimeError as error:
                fallback_id = record_exception(
                    LOGGER, "unit.storage_failure", error
                )
        assert fallback_id.startswith("diag_")
        assert _load_event(db_session, fallback_id) is not None
        assert "storage unavailable" not in capsys.readouterr().err
    finally:
        reset_exception_storage()


def test_admin_reads_full_diagnostics_and_unknown_event_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    from app.modules.system.infrastructure.log_files import append_log_event
    append_log_event({
        "id": "diag_admin", "level": "error", "source": "system", "actorType": "system",
        "actorId": None, "action": "api.request_failed", "message": "boom",
        "createdAt": datetime.now(UTC).isoformat(),
        "metadata": {"diagnostics": {"exceptionType": "builtins.RuntimeError",
            "traceback": "Traceback (most recent call last):\nRuntimeError: boom", "location": "app/x.py:1"}},
    })
    db_session.add(
        User(
            email="diagnostics-admin@example.com",
            name="diagnostics-admin",
            password_hash=hash_password("Diagnostics123!"),
            role="admin",
        )
    )
    db_session.commit()
    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"email": "diagnostics-admin@example.com", "password": "Diagnostics123!"},
    )
    assert login.status_code == 200

    detail = client.get("/api/management/events/diag_admin")
    assert detail.status_code == 200
    diagnostics = detail.json()["data"]["metadata"]["diagnostics"]
    assert diagnostics["exceptionType"] == "builtins.RuntimeError"
    assert "RuntimeError: boom" in diagnostics["traceback"]

    listing = client.get("/api/management/events").json()["data"]["events"]
    summary = next(event for event in listing if event["id"] == "diag_admin")
    assert summary["metadata"]["diagnostics"] == diagnostics
    exported = client.get("/api/management/events").json()["data"]["events"]
    complete = next(event for event in exported if event["id"] == "diag_admin")
    assert complete["metadata"]["diagnostics"] == diagnostics

    settings = client.get("/api/system/log-settings")
    assert settings.status_code == 200
    assert settings.json()["data"]["storage"]["retentionDays"] == 3
    assert settings.json()["data"]["storage"]["minimumLevel"] == "error"
    updated = client.put("/api/system/log-settings", json={"retentionDays": 7, "minimumLevel": "debug"})
    assert updated.status_code == 200
    assert updated.json()["data"]["storage"]["retentionDays"] == 7
    assert updated.json()["data"]["storage"]["minimumLevel"] == "debug"
    assert "maxBytes" not in updated.text
    invalid = client.put("/api/system/log-settings", json={"retentionDays": 0})
    assert invalid.status_code == 400
    assert client.get("/api/system/log-settings").json()["data"]["storage"]["retentionDays"] == 7
    assert client.put("/api/system/log-settings", json={"maxBytes": 1048576}).status_code == 422

    missing = client.get("/api/management/events/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "EVENT_NOT_FOUND"


def test_validation_and_authorization_failures_are_not_recorded_as_crashes(
    client: TestClient,
    db_session: Session,
) -> None:
    invalid = client.post("/api/auth/login", json={})
    assert invalid.status_code == 422

    db_session.add(
        User(
            email="plain-member@example.com",
            name="plain-member",
            password_hash=hash_password("PlainMember123!"),
            role="member",
        )
    )
    db_session.commit()
    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"email": "plain-member@example.com", "password": "PlainMember123!"},
    )
    assert login.status_code == 200
    forbidden = client.get("/api/management/events")
    assert forbidden.status_code == 403
    assert client.get("/api/management/events").status_code == 403

    assert [
        event
        for event in _all_events(db_session, source="system")
        if event.action == "api.request_failed"
    ] == []


class _FakeUow:
    def release_before_io(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def recover_after_failure(self) -> None:
        return None

    @contextmanager
    def transaction(self):
        yield


class _FakeProcessImport:
    def reset_inspection_cache(self) -> None:
        return None


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class _ScanRaises:
    def execute_library(self, *_args, **_kwargs):
        raise OSError("scan boom marker")

    def execute_source(self, *_args, **_kwargs):
        raise AssertionError("unused")


class _ScanOk:
    def execute_library(self, *_args, **_kwargs):
        return None

    def execute_source(self, *_args, **_kwargs):
        raise AssertionError("unused")


class _FakeQueue:
    def __init__(self, task: LibraryImportTaskRecord, *, complete: bool = True) -> None:
        self.task = task
        self.failed_summary: str | None = None
        self._complete = complete

    def prepare_book_identifications(self):
        return ()

    def enqueue_book_identifications(self, _prepared):
        return 0

    def next_queued(self, *, started_at: datetime):
        return self.task

    def begin_discovery(self, task_id: str) -> None:
        assert task_id == self.task.id

    def end_discovery(self) -> None:
        pass

    def mark_running(self, task_id: str, *, started_at: datetime) -> None:
        self.task = replace(self.task, state="RUNNING")

    def get_task(self, task_id: str):
        if not self._complete:
            return None
        return self.task if self.task.state == "RUNNING" else None

    def mark_succeeded(self, task_id: str, *, finished_at: datetime) -> None:
        self.task = replace(self.task, state="SUCCEEDED")

    def mark_failed(
        self, task_id: str, *, error_summary: str, finished_at: datetime
    ) -> None:
        self.failed_summary = error_summary
        self.task = replace(self.task, state="FAILED")

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int:
        return 0


def _task() -> LibraryImportTaskRecord:
    return LibraryImportTaskRecord(
        id="task-1",
        kind="SCAN_LIBRARY",
        library_id="library-1",
        state="QUEUED",
        resource_id=None,
        source_node_id="node-9",
        role=None,
        error_summary=None,
    )


def _processor(queue: _FakeQueue, scan) -> ReadableResourceWorkerProcessor:
    return ReadableResourceWorkerProcessor(
        queue=queue,
        scan=scan,
        process_import=_FakeProcessImport(),
        uow=_FakeUow(),
        clock=_FixedClock(),
    )


def test_worker_containment_records_task_context_and_original_traceback(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_exception_storage(lambda: _session_for(db_session))
    try:
        queue = _FakeQueue(_task())
        with caplog.at_level(logging.ERROR):
            outcome = _processor(queue, _ScanRaises()).process_once()
    finally:
        reset_exception_storage()

    assert outcome == "failed"
    assert queue.failed_summary == "OSError: scan boom marker"
    assert "scan boom marker" in caplog.text
    assert "OSError" in caplog.text

    events = _all_events(db_session, source="import")
    assert len(events) == 1
    event = events[0]
    assert not hasattr(event, "target_type")
    assert not hasattr(event, "target_id")
    assert "libraryId" not in event.metadata_json
    assert "taskKind" not in event.metadata_json
    assert "sourceNodeId" not in event.metadata_json
    assert "scan boom marker" in event.metadata_json["diagnostics"]["traceback"]


def test_outer_boundary_records_maintenance_failure_and_still_propagates(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(_db):
        raise OperationalError("maintenance probe", {}, Exception("db down"))

    monkeypatch.setattr(app_main, "database_maintenance_is_active", _boom)

    with caplog.at_level(logging.ERROR), pytest.raises(OperationalError):
        client.post("/api/app-config")

    assert "db down" in caplog.text
    events = [
        event
        for event in _all_events(db_session, source="system")
        if event.action == "operation.failed_before_cleanup"
    ]
    assert len(events) == 1
    assert events[0].id not in caplog.text
    assert "stage" not in events[0].metadata_json
    assert "method" not in events[0].metadata_json
    assert "db down" in events[0].metadata_json["diagnostics"]["traceback"]


def test_outer_boundary_records_permission_query_failure_and_still_propagates(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("auth lookup failed")

    monkeypatch.setattr(app_main, "get_current_user", _boom)

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        client.get("/api/management/events")

    assert "auth lookup failed" in caplog.text
    events = [
        event
        for event in _all_events(db_session, source="system")
        if event.action == "operation.failed_before_cleanup"
    ]
    assert len(events) == 1
    assert events[0].id not in caplog.text
    assert "stage" not in events[0].metadata_json


def test_secrets_never_reach_running_log_or_persisted_event(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def factory() -> Session:
        return _session_for(db_session)

    configure_exception_storage(factory)
    try:
        try:
            raise RuntimeError(
                'password="db-secret" token=db-token '
                '{"authorization": "Bearer db-bearer"}'
            )
        except RuntimeError as error:
            with caplog.at_level(logging.ERROR):
                diagnostic_id = record_exception(
                    LOGGER,
                    "secret.failure",
                    error,

                )
    finally:
        reset_exception_storage()

    event = _load_event(db_session, diagnostic_id)
    assert event is not None
    persisted_blob = f"{event.message}{json.dumps(event.metadata_json, ensure_ascii=False)}"
    for secret in ("db-secret", "db-token", "db-bearer"):
        assert secret in persisted_blob
        assert secret in caplog.text
    assert "secret.failure" not in caplog.text
    assert "diag_" not in caplog.text


def test_cross_layer_propagation_reuses_one_main_event(db_session: Session) -> None:
    def factory() -> Session:
        return _session_for(db_session)

    try:
        raise ValueError("cross-layer failure")
    except ValueError as error:
        inner = prepare_exception_diagnostic(
            LOGGER, "layer.inner", error
        )
        outer = prepare_exception_diagnostic(
            LOGGER, "layer.outer", error
        )
        assert inner is outer
        assert inner.diagnostic_id == outer.diagnostic_id
        assert persist_exception_diagnostic(LOGGER, inner, factory) is True
        assert persist_exception_diagnostic(LOGGER, outer, factory) is True

    events = _all_events(db_session, source="system")
    assert len(events) == 1
    assert events[0].id == inner.diagnostic_id


def test_distinct_attempts_with_identical_text_are_recorded_separately(
    db_session: Session,
) -> None:
    def factory() -> Session:
        return _session_for(db_session)

    configure_exception_storage(factory)
    try:
        diagnostic_ids = []
        for _attempt in range(2):
            try:
                raise ValueError("identical failure text")
            except ValueError as error:
                diagnostic_ids.append(
                    record_exception(LOGGER, "attempt.failed", error, source="import")
                )
    finally:
        reset_exception_storage()

    assert len(set(diagnostic_ids)) == 2
    events = _all_events(db_session, source="import")
    assert len(events) == 2
    assert {event.id for event in events} == set(diagnostic_ids)


class _ClosingSession:
    def execute(self, *_args, **_kwargs):
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        raise RuntimeError("close failed")


class _FailingWriteSession:
    def execute(self, *_args, **_kwargs):
        raise RuntimeError("write failed")

    def commit(self) -> None:
        raise RuntimeError("commit failed")

    def rollback(self) -> None:
        raise RuntimeError("rollback failed")

    def close(self) -> None:
        raise RuntimeError("close failed too")


def test_logging_no_longer_opens_database_sessions(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        raise ValueError("original business failure")
    except ValueError as error:
        close_only = prepare_exception_diagnostic(
            LOGGER, "session.close_failed", error
        )
    with caplog.at_level(logging.WARNING):
        assert (
            persist_exception_diagnostic(LOGGER, close_only, lambda: _ClosingSession())
            is True
        )

    try:
        raise ValueError("second business failure")
    except ValueError as error:
        write_failed = prepare_exception_diagnostic(
            LOGGER, "session.write_failed", error
        )
    with caplog.at_level(logging.WARNING):
        assert (
            persist_exception_diagnostic(
                LOGGER, write_failed, lambda: _FailingWriteSession()
            )
            is True
        )

    assert "original business failure" in caplog.text
    assert "second business failure" in caplog.text
    output = capsys.readouterr().err
    for message in ("write failed", "rollback failed", "close failed too"):
        assert message not in output


def test_recording_succeeds_without_waiting_for_business_write_lock(
    tmp_path,
) -> None:
    database_path = tmp_path / "diagnostics-lock.sqlite3"
    locked_engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"timeout": 0.25, "check_same_thread": False},
    )
    recorder_engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"timeout": 0.25, "check_same_thread": False},
    )
    SystemEvent.__table__.create(recorder_engine)
    factory = sessionmaker(
        bind=recorder_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    try:
        try:
            raise RuntimeError("locked diagnostic failure")
        except RuntimeError as error:
            snapshot = prepare_exception_diagnostic(LOGGER, "lock.failure", error)

        with locked_engine.connect() as business:
            transaction = business.begin()
            business.execute(
                insert(SystemEvent).values(
                    id="held-business-row",
                    level="info",
                    source="test",
                    actor_type="system",
                    action="held",
                    message="uncommitted business write",
                )
            )
            started = monotonic()
            persisted_while_locked = persist_exception_diagnostic(
                LOGGER, snapshot, factory
            )
            elapsed = monotonic() - started
            transaction.rollback()

        # File logging remains available while the business database is write-locked.
        assert persisted_while_locked is True
        assert elapsed < 1.5, "recording waited too long on the business write lock"

        assert persist_exception_diagnostic(LOGGER, snapshot, factory) is True
        session = factory()
        try:
            assert session.get(SystemEvent, snapshot.diagnostic_id) is None
            assert _load_event(session, snapshot.diagnostic_id) is not None
        finally:
            session.close()
    finally:
        locked_engine.dispose()
        recorder_engine.dispose()


def test_cancelled_completion_is_not_recorded_as_crash(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_exception_storage(lambda: _session_for(db_session))
    try:
        queue = _FakeQueue(_task(), complete=False)
        with caplog.at_level(logging.ERROR):
            outcome = _processor(queue, _ScanOk()).process_once()
    finally:
        reset_exception_storage()

    assert outcome == "cancelled"
    assert queue.failed_summary is None
    assert "task_failed" not in caplog.text
    assert _all_events(db_session) == []
