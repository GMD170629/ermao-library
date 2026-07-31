from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

import app.services.metadata_lookup_queue as metadata_queue
import app.services.organize_scheduler as organize_scheduler
from app.core.config import Settings
from app.infrastructure.sqlite_retry import execute_with_sqlite_busy_retry


def _operational_error(message: str) -> OperationalError:
    return OperationalError("UPDATE queue", {}, RuntimeError(message))


class RecordingSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.closed = False

    def __enter__(self) -> RecordingSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def rollback(self) -> None:
        self.rollback_calls += 1


class RecordingSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[RecordingSession] = []

    def __call__(self) -> RecordingSession:
        session = RecordingSession()
        self.sessions.append(session)
        return session


class NonBlockingStop:
    def __init__(self, *, cancel: bool = False) -> None:
        self.cancel = cancel
        self.delays: list[float] = []

    def wait(self, delay_seconds: float) -> bool:
        self.delays.append(delay_seconds)
        return self.cancel


def test_sqlite_busy_retry_rolls_back_and_uses_a_fresh_session() -> None:
    session_factory = RecordingSessionFactory()
    stop = NonBlockingStop()
    calls = 0

    def operation(_db: RecordingSession) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _operational_error("database is locked")
        return "completed"

    result = execute_with_sqlite_busy_retry(
        session_factory,
        operation,
        retry_delays_seconds=(0.25, 1.0),
        stop_wait=stop.wait,
    )

    assert result.completed is True
    assert result.value == "completed"
    assert stop.delays == [0.25]
    assert len(session_factory.sessions) == 2
    assert session_factory.sessions[0].rollback_calls == 1
    assert all(session.closed for session in session_factory.sessions)


def test_sqlite_retry_does_not_retry_an_unrelated_operational_error() -> None:
    session_factory = RecordingSessionFactory()
    stop = NonBlockingStop()

    with pytest.raises(OperationalError, match="disk I/O error"):
        execute_with_sqlite_busy_retry(
            session_factory,
            lambda _db: (_ for _ in ()).throw(
                _operational_error("disk I/O error")
            ),
            retry_delays_seconds=(0.25, 1.0),
            stop_wait=stop.wait,
        )

    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].rollback_calls == 1
    assert stop.delays == []


def test_sqlite_retry_can_be_interrupted_before_opening_another_session() -> None:
    session_factory = RecordingSessionFactory()
    stop = NonBlockingStop(cancel=True)

    result = execute_with_sqlite_busy_retry(
        session_factory,
        lambda _db: (_ for _ in ()).throw(
            _operational_error("database is locked")
        ),
        retry_delays_seconds=(0.25, 1.0),
        stop_wait=stop.wait,
    )

    assert result.completed is False
    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].rollback_calls == 1


def test_metadata_worker_retries_transient_database_locks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_factory = RecordingSessionFactory()
    calls = 0

    def operation(*_args: object) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _operational_error("database is locked")
        return False

    monkeypatch.setattr(
        metadata_queue, "process_next_metadata_lookup_task", operation
    )
    worker = metadata_queue.MetadataLookupWorker(
        session_factory,
        Settings(storage_root=str(tmp_path)),
    )
    monkeypatch.setattr(worker, "_stop", NonBlockingStop())

    result = worker._process_iteration()

    assert result is False
    assert calls == 2
    assert len(session_factory.sessions) == 2
    assert session_factory.sessions[0].rollback_calls == 1


def test_organizer_scheduler_retries_transient_database_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = RecordingSessionFactory()
    calls = 0

    def operation(*_args: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _operational_error("database is locked")
        return 0

    monkeypatch.setattr(
        organize_scheduler, "process_organize_schedule_tick", operation
    )
    scheduler = organize_scheduler.OrganizerScheduler(session_factory)
    monkeypatch.setattr(scheduler, "_stop", NonBlockingStop())

    assert scheduler._process_iteration() is True
    assert calls == 2
    assert len(session_factory.sessions) == 2
    assert session_factory.sessions[0].rollback_calls == 1
