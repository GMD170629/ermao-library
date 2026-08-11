from __future__ import annotations

import logging
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Self

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.services.metadata_lookup_queue as metadata_queue
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.organize import OrganizeRun
from app.models.settings import SystemSetting
from app.services import organize_scheduler


def _operational_error(message: str) -> OperationalError:
    return OperationalError("UPDATE queue", {}, RuntimeError(message))


class RecordingSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.closed = False

    def __enter__(self) -> Self:
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


class RecordingHeartbeat:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def pulse(self, **_values: object) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True


def test_metadata_worker_retries_transient_database_locks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_factory = RecordingSessionFactory()
    calls = 0

    def operation(*_args: object, **_kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _operational_error("database is locked")
        return False

    monkeypatch.setattr(metadata_queue, "process_next_metadata_lookup_task", operation)
    worker = metadata_queue.MetadataLookupWorker(
        session_factory,
        Settings(storage_root=str(tmp_path)),
    )
    monkeypatch.setattr(worker, "_stop", NonBlockingStop())

    result = worker._process_iteration()

    assert result is False
    assert calls == 2
    assert len(session_factory.sessions) == 2
    assert session_factory.sessions[0].closed is True


def test_metadata_worker_throttles_expected_database_busy_logs(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    worker = metadata_queue.MetadataLookupWorker(
        RecordingSessionFactory(),
        Settings(storage_root=str(tmp_path)),
    )
    busy = _operational_error("database is locked")

    with caplog.at_level(logging.WARNING):
        worker._record_iteration_error(busy)
        worker._record_iteration_error(busy)

    deferred = [
        record
        for record in caplog.records
        if "outcome=deferred reason=database_busy" in record.getMessage()
    ]
    assert len(deferred) == 1
    assert deferred[0].exc_info is None


def test_metadata_worker_rotates_lookup_preparation_and_target_priority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: list[tuple[bool, bool]] = []

    def operation(*_args: object, **kwargs: object) -> bool:
        observed.append(
            (
                bool(kwargs["prefer_writeback"]),
                bool(kwargs["prefer_preparation"]),
            )
        )
        return False

    monkeypatch.setattr(metadata_queue, "process_next_metadata_lookup_task", operation)
    worker = metadata_queue.MetadataLookupWorker(
        RecordingSessionFactory(),
        Settings(storage_root=str(tmp_path)),
    )

    for _ in range(4):
        assert worker._process_iteration() is False

    assert observed == [
        (False, True),
        (True, False),
        (False, True),
        (True, False),
    ]


def test_metadata_worker_shutdown_interrupts_long_idle_poll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    iteration_started = Event()

    def operation(*_args: object, **_kwargs: object) -> bool:
        iteration_started.set()
        return False

    monkeypatch.setattr(metadata_queue, "process_next_metadata_lookup_task", operation)
    worker = metadata_queue.MetadataLookupWorker(
        RecordingSessionFactory(),
        Settings(storage_root=str(tmp_path)),
        poll_seconds=60,
    )
    heartbeat = RecordingHeartbeat()
    monkeypatch.setattr(worker, "_heartbeat", heartbeat)
    worker._thread.start()
    assert iteration_started.wait(timeout=2)

    started = monotonic()
    worker.shutdown()

    assert monotonic() - started < 0.5
    assert heartbeat.started is True
    assert heartbeat.stopped is True


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

    monkeypatch.setattr(organize_scheduler, "process_organize_schedule_tick", operation)
    scheduler = organize_scheduler.OrganizerScheduler(session_factory)
    monkeypatch.setattr(scheduler, "_stop", NonBlockingStop())

    assert scheduler._process_iteration() is True
    assert calls == 2
    assert len(session_factory.sessions) == 2
    assert session_factory.sessions[0].closed is True


def test_organizer_scheduler_throttles_expected_database_busy_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    scheduler = organize_scheduler.OrganizerScheduler(RecordingSessionFactory())
    busy = _operational_error("database is locked")

    with caplog.at_level(logging.WARNING):
        scheduler._record_iteration_error(busy)
        scheduler._record_iteration_error(busy)

    deferred = [
        record
        for record in caplog.records
        if "outcome=deferred reason=database_busy" in record.getMessage()
        and "organizer_schedule_iteration" in record.getMessage()
    ]
    assert len(deferred) == 1
    assert deferred[0].exc_info is None


def test_organizer_scheduler_preserves_pending_state_under_real_writer_lock(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    blocker_engine = create_sqlite_engine(settings.database_path, timeout_seconds=0.05)
    worker_engine = create_sqlite_engine(settings.database_path, timeout_seconds=0.05)
    bootstrap_database(blocker_engine, settings)
    worker_factory = sessionmaker(
        bind=worker_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    scheduler = organize_scheduler.OrganizerScheduler(worker_factory)
    monkeypatch.setattr(organize_scheduler, "DATABASE_BUSY_RETRY_DELAYS_SECONDS", ())

    try:
        with Session(worker_engine) as seed:
            seed.add(
                OrganizeRun(
                    id="pending-organize-run",
                    trigger="MANUAL",
                    scope_json="{}",
                    status="RUNNING",
                    queued_count=0,
                )
            )
            seed.commit()

        with Session(blocker_engine) as blocker:
            blocker.add(SystemSetting(key="writer-lock", value="held"))
            blocker.flush()
            with pytest.raises(OperationalError) as captured:
                scheduler._process_iteration()
            with caplog.at_level(logging.WARNING):
                scheduler._record_iteration_error(captured.value)

            with Session(worker_engine) as observer:
                pending = observer.scalar(
                    select(OrganizeRun).where(OrganizeRun.id == "pending-organize-run")
                )
                assert pending is not None
                assert pending.status == "RUNNING"

            blocker.rollback()

        assert scheduler._process_iteration() is True
        with Session(worker_engine) as observer:
            completed = observer.get(OrganizeRun, "pending-organize-run")
            assert completed is not None
            assert completed.status == "COMPLETED"
        deferred = [
            record
            for record in caplog.records
            if "organizer_schedule_iteration " in record.getMessage()
        ]
        assert len(deferred) == 1
        assert deferred[0].exc_info is None
    finally:
        blocker_engine.dispose()
        worker_engine.dispose()
