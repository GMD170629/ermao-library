"""A terminal write failure closes one execution; it never schedules a replay."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)


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


def test_unwritable_terminal_and_failure_close_stay_running_until_startup(
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
        with pytest.raises(RuntimeError, match="IMPORT_TERMINAL_PERSISTENCE_FAILED"):
            worker.process_once()
    finally:
        event.remove(engine, "before_cursor_execute", fail_terminal)

    assert scanned == ["test-library"]
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, first_id).state == "RUNNING"
        assert observer.get(LibraryImportTask, second_id).state == "QUEUED"
    assert worker.startup() == 1
    with Session(engine) as observer:
        first = observer.get(LibraryImportTask, first_id)
        assert first.state == "FAILED" and first.error_summary == "WORKER_INTERRUPTED"
    assert worker.process_once() == "scan"
    assert scanned == ["test-library", "second-library"]
