"""A terminal write failure closes one execution; it never schedules a replay."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.models import Library
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.services import metadata_lookup_queue, organize_scheduler
from app.worker import main as worker_main


@pytest.fixture()
def scanning_pipeline(
    db_session: Session, tmp_path: Path, test_settings: Settings
) -> tuple[ReadableResourcePipeline, str, str]:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    library = db_session.get(Library, "test-library")
    assert library is not None
    library.root_path = str(first_root)
    db_session.add(Library(
        id="second-library", name="Second library", root_path=str(second_root),
        organization_mode="FLAT",
    ))
    db_session.commit()
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    first = pipeline.queue.enqueue(kind="SCAN_LIBRARY", library_id="test-library")
    second = pipeline.queue.enqueue(kind="SCAN_LIBRARY", library_id="second-library")
    first_row = db_session.get(LibraryImportTask, first.id)
    second_row = db_session.get(LibraryImportTask, second.id)
    assert first_row is not None and second_row is not None
    first_row.created_at = datetime(2026, 9, 13, tzinfo=UTC)
    second_row.created_at = first_row.created_at + timedelta(seconds=1)
    db_session.commit()
    return pipeline, first.id, second.id


@pytest.mark.parametrize("failure_stage", ("statement", "commit"))
def test_success_terminal_write_failure_is_closed_once_and_next_task_runs(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
    failure_stage: str,
) -> None:
    pipeline, first_id, second_id = scanning_pipeline
    worker = build_readable_resource_worker(pipeline)
    scanned: list[str] = []
    original_scan = pipeline.scan_library_source_tree.execute_library

    def recorded_scan(library_id: str, **kwargs: object):
        scanned.append(library_id)
        return original_scan(library_id, **kwargs)

    pipeline.scan_library_source_tree.execute_library = recorded_scan
    attempts = 0
    success_written = False

    def interrupt_success(_connection, _cursor, statement, parameters, context, _many):
        nonlocal attempts, success_written
        if (
            context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and first_id in parameters
            and "SUCCEEDED" in parameters
        ):
            attempts += 1
            if failure_stage == "statement":
                raise OperationalError(
                    statement, parameters, sqlite3.OperationalError("disk I/O error")
                )
            success_written = True

    def interrupt_commit(_session: Session) -> None:
        nonlocal success_written
        if failure_stage == "commit" and success_written:
            success_written = False
            raise OperationalError(
                "COMMIT", None, sqlite3.OperationalError("disk I/O error")
            )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", interrupt_success)
    event.listen(db_session, "before_commit", interrupt_commit)
    try:
        assert worker.process_once() == "failed"
    finally:
        event.remove(engine, "before_cursor_execute", interrupt_success)
        event.remove(db_session, "before_commit", interrupt_commit)
    with Session(engine) as observer:
        first = observer.get(LibraryImportTask, first_id)
        second = observer.get(LibraryImportTask, second_id)
        assert first is not None and first.state == "FAILED"
        assert first.error_summary == "TASK_COMPLETION_WRITE_FAILED"
        assert first.completion_outcome is None
        assert second is not None and second.state == "QUEUED"
    assert attempts == 1
    assert scanned == ["test-library"]
    assert worker.process_once() == "scan"
    assert scanned == ["test-library", "second-library"]
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, first_id).state == "FAILED"
        assert observer.get(LibraryImportTask, second_id).state == "SUCCEEDED"


def test_failure_terminal_write_does_not_schedule_another_execution(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
) -> None:
    pipeline, first_id, _ = scanning_pipeline
    worker = build_readable_resource_worker(pipeline)
    scanned: list[str] = []
    original_scan = pipeline.scan_library_source_tree.execute_library

    def failed_scan(library_id: str, **_kwargs: object) -> None:
        scanned.append(library_id)
        if library_id == "test-library":
            raise RuntimeError("injected scan failure")
        return original_scan(library_id, **_kwargs)

    pipeline.scan_library_source_tree.execute_library = failed_scan
    attempts = 0

    def interrupt_failure(_connection, _cursor, statement, parameters, context, _many):
        nonlocal attempts
        if (
            context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and first_id in parameters
            and "FAILED" in parameters
        ):
            attempts += 1
            if attempts == 1:
                raise OperationalError(
                    statement, parameters, sqlite3.OperationalError("disk I/O error")
                )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", interrupt_failure)
    try:
        assert worker.process_once() == "failed"
    finally:
        event.remove(engine, "before_cursor_execute", interrupt_failure)
    assert attempts == 2  # initial terminal write and the one allowed failure close
    assert scanned == ["test-library"]
    with Session(engine) as observer:
        first = observer.get(LibraryImportTask, first_id)
        assert first is not None and first.state == "FAILED"
        assert first.completion_outcome is None
    assert worker.process_once() == "scan"
    assert scanned == ["test-library", "second-library"]


def test_unwritable_terminal_is_isolated_without_restarting_worker(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
) -> None:
    pipeline, first_id, second_id = scanning_pipeline
    worker = build_readable_resource_worker(pipeline)
    scanned: list[str] = []
    original_scan = pipeline.scan_library_source_tree.execute_library

    def recorded_scan(library_id: str, **kwargs: object):
        scanned.append(library_id)
        return original_scan(library_id, **kwargs)

    pipeline.scan_library_source_tree.execute_library = recorded_scan

    def fail_terminal(_connection, _cursor, statement, parameters, context, _many):
        if (
            context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and first_id in parameters
            and ("SUCCEEDED" in parameters or "FAILED" in parameters)
        ):
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("disk I/O error")
            )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", fail_terminal)
    try:
        assert worker.process_once() == "isolated"
    finally:
        event.remove(engine, "before_cursor_execute", fail_terminal)

    assert scanned == ["test-library"]
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, first_id).state == "RUNNING"
        assert observer.get(LibraryImportTask, second_id).state == "QUEUED"
    assert worker.process_once() == "scan"
    assert scanned == ["test-library", "second-library"]
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, first_id).state == "RUNNING"
        assert observer.get(LibraryImportTask, second_id).state == "SUCCEEDED"


def test_outer_loop_continues_after_one_task_cannot_persist_terminal(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
    test_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _pipeline, first_id, second_id = scanning_pipeline
    third_root = tmp_path / "third"
    third_root.mkdir()
    db_session.add(Library(
        id="third-library", name="Third library", root_path=str(third_root),
        organization_mode="FLAT",
    ))
    db_session.commit()
    engine = db_session.get_bind()
    third_id: list[str] = []
    scanned: list[str] = []
    startup_calls: list[int] = []
    terminal_attempts = 0

    def fail_first_terminal(_connection, _cursor, statement, parameters, context, _many):
        nonlocal terminal_attempts
        if (
            context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and first_id in parameters
            and ("SUCCEEDED" in parameters or "FAILED" in parameters)
        ):
            terminal_attempts += 1
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("disk I/O error")
            )

    class StopAfterIndependentTasks:
        stopped = False
        waits = 0

        def is_set(self) -> bool:
            if third_id:
                with Session(engine) as observer:
                    if all(
                        observer.get(LibraryImportTask, task_id).state == "SUCCEEDED"
                        for task_id in (second_id, third_id[0])
                    ):
                        self.stopped = True
            return self.stopped

        def set(self) -> None:
            self.stopped = True

        def wait(self, _delay: float) -> bool:
            self.waits += 1
            if self.waits > 10:
                self.set()
            return self.stopped

    def build_pipeline(session: Session) -> ReadableResourcePipeline:
        pipeline = build_readable_resource_pipeline(session, test_settings)
        original_scan = pipeline.scan_library_source_tree.execute_library

        def recorded_scan(library_id: str, **kwargs: object):
            scanned.append(library_id)
            return original_scan(library_id, **kwargs)

        pipeline.scan_library_source_tree.execute_library = recorded_scan
        return pipeline

    def build_worker(pipeline: ReadableResourcePipeline):
        worker = build_readable_resource_worker(pipeline)
        original_startup = worker.startup

        def startup() -> int:
            startup_calls.append(1)
            return original_startup()

        worker.startup = startup
        return worker

    def pulse(**kwargs: object) -> None:
        if kwargs.get("error") != "completion-isolated" or third_id:
            return
        with Session(engine) as submitter:
            task = SqlAlchemyLibraryImportTaskQueue(submitter).enqueue(
                kind="SCAN_LIBRARY", library_id="third-library"
            )
            third_id.append(task.id)
            submitter.commit()

    event.listen(engine, "before_cursor_execute", fail_first_terminal)
    monkeypatch.setattr(worker_main, "BackgroundSessionLocal", lambda: Session(engine))
    monkeypatch.setattr(worker_main, "get_settings", lambda: test_settings)
    monkeypatch.setattr(worker_main, "worker_ready_file", lambda: tmp_path / "ready")
    monkeypatch.setattr(worker_main, "verify_current_schema", lambda _engine: None)
    monkeypatch.setattr(worker_main, "configure_logging", lambda: None)
    monkeypatch.setattr(worker_main, "configure_exception_storage", lambda _factory: None)
    monkeypatch.setattr(worker_main, "install_exception_hooks", lambda: None)
    monkeypatch.setattr(worker_main, "build_readable_resource_pipeline", build_pipeline)
    monkeypatch.setattr(worker_main, "build_readable_resource_worker", build_worker)
    monkeypatch.setattr(worker_main, "build_automation_uploads", lambda _db: Mock())
    monkeypatch.setattr(worker_main, "build_file_move_worker", lambda _db: Mock())
    monkeypatch.setattr(worker_main, "LibraryScanCoordinator", lambda **_kw: Mock())
    monkeypatch.setattr(worker_main, "QueueHeartbeatPump", lambda *_a, **_kw: SimpleNamespace(
        start=lambda: None, stop=lambda: None, pulse=pulse,
    ))
    monkeypatch.setattr(worker_main.threading, "Event", StopAfterIndependentTasks)
    monkeypatch.setattr(worker_main.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(metadata_lookup_queue, "MetadataLookupWorker", lambda *_a, **_kw: Mock())
    monkeypatch.setattr(organize_scheduler, "OrganizerScheduler", lambda *_a, **_kw: Mock())
    try:
        worker_main.main()
    finally:
        event.remove(engine, "before_cursor_execute", fail_first_terminal)

    assert terminal_attempts == 2
    assert startup_calls == [1]
    assert scanned == ["test-library", "second-library", "third-library"]
    assert len(third_id) == 1
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, first_id).state == "RUNNING"
        assert observer.get(LibraryImportTask, second_id).state == "SUCCEEDED"
        assert observer.get(LibraryImportTask, third_id[0]).state == "SUCCEEDED"
    for diagnostic_event, stage in (
        ("completion_write_failed", "completion"),
        ("failure_close_failed", "failure_close"),
    ):
        assert any(
            diagnostic_event in record.message
            and "disk I/O error" in record.message
            and getattr(record, "stage", None) == stage
            and getattr(record, "task_id", None) == first_id
            for record in caplog.records
        )
