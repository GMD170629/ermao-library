"""Persist task outcomes after transient failures without rerunning the work."""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.models import Library, LibraryBook, LibraryBookMetadata, LibrarySourceNode
from app.modules.imports.application.readable_resource.book_work import BookWork
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath


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
    db_session.add(
        Library(
            id="second-library",
            name="Second library",
            root_path=str(second_root),
            organization_mode="FLAT",
        )
    )
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


@pytest.mark.parametrize("scan_fails", (False, True), ids=("success", "failure"))
@pytest.mark.parametrize("failure_stage", ("statement", "commit"))
def test_terminal_write_retry_preserves_outcome_and_blocks_next_task(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
    monkeypatch: pytest.MonkeyPatch,
    scan_fails: bool,
    failure_stage: str,
) -> None:
    pipeline, first_id, second_id = scanning_pipeline
    scan = pipeline.scan_library_source_tree.execute_library
    scanned_libraries: list[str] = []

    def execute_library(library_id: str, **kwargs: object):
        scanned_libraries.append(library_id)
        if scan_fails and library_id == "test-library":
            raise RuntimeError("scan failed")
        return scan(library_id, **kwargs)

    monkeypatch.setattr(
        pipeline.scan_library_source_tree, "execute_library", execute_library
    )
    worker = build_readable_resource_worker(pipeline)
    terminal_state = "FAILED" if scan_fails else "SUCCEEDED"
    failures_remaining = 2
    terminal_statement_written = False
    terminal_attempts = 0

    def interrupt_terminal_statement(
        _connection, _cursor, statement, parameters, context, _executemany
    ) -> None:
        nonlocal failures_remaining, terminal_statement_written, terminal_attempts
        if (
            not context.isupdate
            or context.compiled.statement.table.name != LibraryImportTask.__tablename__
            or first_id not in parameters
            or terminal_state not in parameters
        ):
            return
        terminal_attempts += 1
        if failure_stage == "statement" and failures_remaining:
            failures_remaining -= 1
            original = sqlite3.OperationalError("interrupted")
            original.time_budget_exceeded = True
            raise OperationalError(
                statement, parameters, original
            )
        terminal_statement_written = True

    def interrupt_terminal_commit(_session: Session) -> None:
        nonlocal failures_remaining, terminal_statement_written
        if (
            failure_stage == "commit"
            and terminal_statement_written
            and failures_remaining
        ):
            failures_remaining -= 1
            terminal_statement_written = False
            original = sqlite3.OperationalError("interrupted")
            original.time_budget_exceeded = True
            raise OperationalError(
                "COMMIT", None, original
            )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", interrupt_terminal_statement)
    event.listen(db_session, "before_commit", interrupt_terminal_commit)
    try:
        for _ in range(2):
            observed = worker.process_once()
            with Session(engine) as debug_session:
                debug_row = debug_session.get(LibraryImportTask, first_id)
                debug_fact = (debug_row.state, debug_row.completion_outcome, debug_row.completion_retry_count)
            assert observed == "deferred", (observed, terminal_attempts, failures_remaining, scanned_libraries, debug_fact)
            with Session(engine) as observer:
                first = observer.get(LibraryImportTask, first_id)
                second = observer.get(LibraryImportTask, second_id)
                assert first is not None and first.state == "QUEUED"
                assert first.finished_at is None
                assert second is not None and second.state == "QUEUED"
                assert first.completion_outcome is not None
                first.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
                observer.commit()
            assert pipeline.queue.next_queued(started_at=datetime.now(UTC)).id == first_id
            assert scanned_libraries == ["test-library"]

        assert failures_remaining == 0
        assert worker.process_once() == ("error" if scan_fails else "scan")
        assert terminal_attempts == 3
        with Session(engine) as observer:
            first = observer.get(LibraryImportTask, first_id)
            second = observer.get(LibraryImportTask, second_id)
            assert first is not None and first.state == terminal_state
            assert first.finished_at is not None
            assert first.error_summary == ("WORKER_ERROR" if scan_fails else None)
            assert second is not None and second.state == "QUEUED"
        assert scanned_libraries == ["test-library"]

        assert worker.process_once() == "scan"
        assert scanned_libraries == ["test-library", "second-library"]
    finally:
        event.remove(engine, "before_cursor_execute", interrupt_terminal_statement)
        event.remove(db_session, "before_commit", interrupt_terminal_commit)


def test_deleted_task_is_not_recreated_by_pending_terminal_retry(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, first_id, second_id = scanning_pipeline
    scan = pipeline.scan_library_source_tree.execute_library
    scanned_libraries: list[str] = []

    def execute_library(library_id: str, **kwargs: object):
        scanned_libraries.append(library_id)
        return scan(library_id, **kwargs)

    monkeypatch.setattr(
        pipeline.scan_library_source_tree, "execute_library", execute_library
    )
    worker = build_readable_resource_worker(pipeline)

    def interrupt_terminal_statement(
        _connection, _cursor, statement, parameters, context, _executemany
    ) -> None:
        if (
            context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and first_id in parameters
            and "SUCCEEDED" in parameters
        ):
            original = sqlite3.OperationalError("interrupted")
            original.time_budget_exceeded = True
            raise OperationalError(
                statement, parameters, original
            )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", interrupt_terminal_statement)
    try:
        assert worker.process_once() == "deferred"
    finally:
        event.remove(engine, "before_cursor_execute", interrupt_terminal_statement)

    with Session(engine) as cancellation:
        cancellation.execute(
            delete(LibraryImportTask).where(LibraryImportTask.id == first_id)
        )
        cancellation.commit()

    assert scanned_libraries == ["test-library"]
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, first_id) is None
        second = observer.get(LibraryImportTask, second_id)
        assert second is not None and second.state == "QUEUED"
        assert list(observer.scalars(select(LibraryImportTask.id))) == [second_id]

    assert worker.process_once() == "scan"
    assert scanned_libraries == ["test-library", "second-library"]


def test_book_completion_failure_preserves_scans_and_retries_after_worker_restart(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, first_id, second_id = scanning_pipeline
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "scan"

    filename = "Pending Book.epub"
    db_session.add(
        LibrarySourceNode(
            id="pending-source",
            library_id="test-library",
            relative_path=filename,
            path_key=SourceNodeRelativePath(filename).path_key,
            name=filename,
            physical_kind="REGULAR_FILE",
            observed_size_bytes=1,
            observed_mtime_ns=1,
            observed_at=datetime(2026, 9, 13, tzinfo=UTC),
        )
    )
    db_session.flush()
    db_session.add(
        LibraryBook(
            id="pending-book",
            library_id="test-library",
            source_node_id="pending-source",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id="pending-book",
            title="Pending Book",
            normalized_title="pending book",
            metadata_pending=True,
            import_revision=3,
        )
    )
    db_session.commit()
    book_task = pipeline.queue.request_book_work(
        book_id="pending-book",
        work=BookWork(identify=True),
        requested_at=datetime.now(UTC),
    )
    db_session.commit()

    completion_attempts = 0
    interrupt_completion = True
    identified: list[str] = []
    identify = pipeline.identify_book.execute

    def record_identify(source_id: str, **kwargs: object):
        identified.append(source_id)
        return identify(source_id, **kwargs)

    monkeypatch.setattr(pipeline.identify_book, "execute", record_identify)

    def interrupt_book_completion(
        _connection, _cursor, statement, parameters, context, _executemany
    ) -> None:
        nonlocal completion_attempts
        if (
            context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and "SUCCEEDED" in parameters
            and book_task.id in parameters
        ):
            completion_attempts += 1
            if interrupt_completion:
                original = sqlite3.OperationalError("interrupted")
                original.time_budget_exceeded = True
                raise OperationalError(
                    statement, parameters, original
                )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", interrupt_book_completion)
    try:
        # A failed terminal write keeps the completed metadata and the earlier
        # scan, while leaving the next scan queued for later work.
        assert worker.process_once() == "deferred"
        assert completion_attempts == 1
        with Session(engine) as observer:
            assert observer.get(LibraryImportTask, first_id).state == "SUCCEEDED"
            assert observer.get(LibraryImportTask, second_id).state == "QUEUED"
            pending = observer.get(LibraryImportTask, book_task.id)
            assert pending.state == "QUEUED"
            assert pending.completion_outcome == "book"
            metadata = observer.get(LibraryBookMetadata, "pending-book")
            assert metadata is not None and not metadata.metadata_pending
            assert metadata.metadata_state == "COMPLETED"
        assert identified == ["pending-source"]
        with Session(engine) as observer:
            pending = observer.get(LibraryImportTask, book_task.id)
            pending.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            observer.commit()
        assert worker.process_once() == "deferred"
        assert completion_attempts == 2
        assert identified == ["pending-source"]

        db_session.add(
            LibraryImportTask(
                id="interrupted-scan",
                # Failed scans block resource/identification work only in their library.
                library_id="second-library",
                kind="SCAN_LIBRARY",
                state="RUNNING",
            )
        )
        db_session.commit()

        # A fresh worker recovers the Book and the unrelated interrupted scan.
        with Session(engine) as restarted_session:
            restarted_pipeline = build_readable_resource_pipeline(
                restarted_session, test_settings
            )
            restarted_identify = restarted_pipeline.identify_book.execute

            def record_restarted_identify(source_id: str, **kwargs: object):
                identified.append(source_id)
                return restarted_identify(source_id, **kwargs)

            monkeypatch.setattr(
                restarted_pipeline.identify_book, "execute", record_restarted_identify
            )
            restarted = build_readable_resource_worker(restarted_pipeline)
            assert restarted.startup() == 1
            with Session(engine) as observer:
                interrupted = observer.get(LibraryImportTask, "interrupted-scan")
                assert interrupted is not None and interrupted.state == "FAILED"
                assert interrupted.finished_at is not None
                assert interrupted.error_summary == "WORKER_INTERRUPTED"
                metadata = observer.get(LibraryBookMetadata, "pending-book")
                assert metadata is not None and not metadata.metadata_pending

            interrupt_completion = False
            with Session(engine) as observer:
                pending = observer.get(LibraryImportTask, book_task.id)
                pending.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
                observer.commit()
            assert restarted.process_once() == "book"
            assert completion_attempts == 3
            assert identified == ["pending-source"]
            assert restarted.process_once() == "scan"
            assert restarted.process_once() == "idle"
            assert completion_attempts == 3

        with Session(engine) as observer:
            metadata = observer.get(LibraryBookMetadata, "pending-book")
            assert metadata is not None and not metadata.metadata_pending
            assert metadata.metadata_state == "COMPLETED"
            assert metadata.processed_revision == 4
            identification = observer.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK"
                )
            )
            assert identification is not None and identification.state == "SUCCEEDED"
            assert {
                row.id: row.state
                for row in observer.scalars(
                    select(LibraryImportTask).where(
                        LibraryImportTask.kind == "SCAN_LIBRARY"
                    )
                )
            } == {
                first_id: "SUCCEEDED",
                second_id: "SUCCEEDED",
                "interrupted-scan": "FAILED",
            }
    finally:
        event.remove(engine, "before_cursor_execute", interrupt_book_completion)


@pytest.mark.parametrize("failure_kind", ("budget", "integrity"))
def test_persistent_book_terminal_timeout_is_bounded_and_allows_next_book(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    pipeline, _, _ = scanning_pipeline
    requested_at = datetime.now(UTC) - timedelta(seconds=2)
    for index in range(2):
        filename = f"Book {index}.epub"
        source_id = f"completion-source-{index}"
        book_id = f"completion-book-{index}"
        db_session.add(
            LibrarySourceNode(
                id=source_id,
                library_id="test-library",
                relative_path=filename,
                path_key=SourceNodeRelativePath(filename).path_key,
                name=filename,
                physical_kind="REGULAR_FILE",
                observed_size_bytes=1,
                observed_mtime_ns=1,
                observed_at=requested_at,
            )
        )
        db_session.flush()
        db_session.add(
            LibraryBook(id=book_id, library_id="test-library", source_node_id=source_id)
        )
        db_session.flush()
        db_session.add(
            LibraryBookMetadata(
                book_id=book_id,
                title=filename,
                normalized_title=filename.lower(),
                metadata_pending=True,
                import_revision=1,
            )
        )
    db_session.commit()
    first = pipeline.queue.request_book_work(
        book_id="completion-book-0", work=BookWork(identify=True), requested_at=requested_at
    )
    second = pipeline.queue.request_book_work(
        book_id="completion-book-1", work=BookWork(identify=True),
        requested_at=requested_at + timedelta(seconds=1),
    )
    db_session.commit()
    identify = pipeline.identify_book.execute
    identified: list[str] = []

    def record_identify(source_id: str, **kwargs: object):
        identified.append(source_id)
        return identify(source_id, **kwargs)

    monkeypatch.setattr(pipeline.identify_book, "execute", record_identify)
    attempts = 0

    def timeout_first_completion(
        _connection, _cursor, statement, parameters, context, _executemany
    ) -> None:
        nonlocal attempts
        if (
            context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and first.id in parameters
            and "SUCCEEDED" in parameters
        ):
            attempts += 1
            if failure_kind == "integrity":
                raise IntegrityError(statement, parameters, sqlite3.IntegrityError("constraint failed"))
            original = sqlite3.OperationalError("interrupted")
            original.time_budget_exceeded = True
            raise OperationalError(statement, parameters, original)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", timeout_first_completion)
    try:
        worker = build_readable_resource_worker(pipeline)
        assert worker.process_once() == ("deferred" if failure_kind == "budget" else "isolated")
        with Session(engine) as observer:
            row = observer.get(LibraryImportTask, first.id)
            assert row is not None and row.completion_outcome == "book"
            if failure_kind == "budget":
                assert row.next_attempt_at > requested_at
            else:
                assert row.state == "FAILED"
        assert worker.process_once() == "book"
        assert identified == ["completion-source-0", "completion-source-1"]
        with Session(engine) as observer:
            assert observer.get(LibraryImportTask, second.id).state == "SUCCEEDED"
        assert attempts == 1
        if failure_kind == "integrity":
            assert identified == ["completion-source-0", "completion-source-1"]
            return
        for expected_count, disposition in ((2, "deferred"), (3, "deferred"), (4, "isolated")):
            with Session(engine) as observer:
                pending = observer.get(LibraryImportTask, first.id)
                pending.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
                observer.commit()
            assert worker.process_once() == disposition
            with Session(engine) as observer:
                pending = observer.get(LibraryImportTask, first.id)
                assert pending.completion_retry_count == expected_count
                assert pending.completion_outcome == "book"
                assert pending.state == ("FAILED" if disposition == "isolated" else "QUEUED")
            assert identified == ["completion-source-0", "completion-source-1"]
        assert attempts == 4
        assert worker.process_once() != "deferred"
        assert attempts == 4
    finally:
        event.remove(engine, "before_cursor_execute", timeout_first_completion)


@pytest.fixture()
def pending_book_worker(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
):
    pipeline, _, second_scan_id = scanning_pipeline
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "scan"
    filename = "Another Book.epub"
    db_session.add(
        LibrarySourceNode(
            id="another-source", library_id="test-library",
            relative_path=filename,
            path_key=SourceNodeRelativePath(filename).path_key,
            name=filename, physical_kind="REGULAR_FILE",
            observed_size_bytes=1, observed_mtime_ns=1,
            observed_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    db_session.add(
        LibraryBook(
            id="another-book", library_id="test-library",
            source_node_id="another-source",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id="another-book", title="Another Book",
            normalized_title="another book", metadata_pending=True,
            import_revision=1,
        )
    )
    db_session.commit()
    task = pipeline.queue.request_book_work(
        book_id="another-book", work=BookWork(identify=True),
        requested_at=datetime.now(UTC),
    )
    db_session.commit()
    return pipeline, worker, task.id, second_scan_id


@pytest.mark.parametrize("change", ("delete", "new_request"))
def test_terminal_recovery_respects_book_deletion_and_new_request(
    db_session: Session,
    pending_book_worker,
    change: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, worker, task_id, second_scan_id = pending_book_worker
    engine = db_session.get_bind()
    failed = False

    def fail_once(_connection, _cursor, statement, parameters, context, _executemany):
        nonlocal failed
        if (
            not failed and context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and task_id in parameters and "SUCCEEDED" in parameters
        ):
            failed = True
            original = sqlite3.OperationalError("interrupted")
            original.time_budget_exceeded = True
            raise OperationalError(statement, parameters, original)

    event.listen(engine, "before_cursor_execute", fail_once)
    try:
        assert worker.process_once() == "deferred"
    finally:
        event.remove(engine, "before_cursor_execute", fail_once)
    assert failed
    if change == "delete":
        with Session(engine) as observer:
            observer.execute(delete(LibraryImportTask).where(LibraryImportTask.id == task_id))
            observer.commit()
        assert worker.process_once() == "scan"
        with Session(engine) as observer:
            assert observer.get(LibraryImportTask, task_id) is None
            assert observer.get(LibraryImportTask, second_scan_id).state == "SUCCEEDED"
        return

    before = pipeline.queue.get_book_task(task_id)
    assert before is not None
    merged = pipeline.queue.request_book_work(
        book_id="another-book", work=BookWork(identify=True),
        requested_at=datetime.now(UTC),
    )
    db_session.commit()
    assert merged.request_version == before.request_version + 1
    assert merged.execution_version == before.execution_version
    assert merged.completion_outcome == "book"
    assert not merged.work.pending.is_empty
    with Session(engine) as observer:
        task = observer.get(LibraryImportTask, task_id)
        task.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        observer.commit()
    finish = pipeline.queue.finish_book_run
    conflicted = False

    def conflict_once(*args: object, **kwargs: object):
        nonlocal conflicted
        if not conflicted:
            conflicted = True
            return None
        return finish(*args, **kwargs)

    monkeypatch.setattr(pipeline.queue, "finish_book_run", conflict_once)
    assert worker.process_once() == "deferred"
    with Session(engine) as observer:
        task = observer.get(LibraryImportTask, task_id)
        assert task.state == "QUEUED"
        assert task.completion_outcome == "book"
        task.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        observer.commit()
    assert worker.process_once() == "book"
    with Session(engine) as observer:
        task = observer.get(LibraryImportTask, task_id)
        assert task.state == "QUEUED"
        assert task.completion_outcome is None
        assert task.execution_version is None
    assert worker.process_once() == "book"
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, task_id).state == "SUCCEEDED"


def test_unwritable_completion_recovery_keeps_durable_intent_for_restart(
    db_session: Session,
    pending_book_worker,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, worker, task_id, _ = pending_book_worker
    engine = db_session.get_bind()
    identified: list[str] = []
    original_identify = pipeline.identify_book.execute

    def count_identify(source_id: str, **kwargs: object):
        identified.append(source_id)
        return original_identify(source_id, **kwargs)

    monkeypatch.setattr(pipeline.identify_book, "execute", count_identify)
    events: list[str] = []

    class CompletionDiagnosticHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if "readable_resource.worker.completion_write_failed" in record.getMessage():
                events.append("diagnostic")

    handler = CompletionDiagnosticHandler()
    diagnostic_logger = logging.getLogger("ermao.readable_resource_pipeline")
    diagnostic_logger.addHandler(handler)

    def note_rollback(_session: Session) -> None:
        events.append("rollback")

    event.listen(db_session, "after_rollback", note_rollback)

    def block_completion_and_recovery(
        _connection, _cursor, statement, parameters, context, _executemany
    ) -> None:
        if (
            context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and task_id in parameters
            and ("SUCCEEDED" in parameters or "completionRetryCount" in statement)
        ):
            original = sqlite3.OperationalError("database is locked")
            raise OperationalError(statement, parameters, original)

    event.listen(engine, "before_cursor_execute", block_completion_and_recovery)
    try:
        with pytest.raises(OperationalError):
            worker.process_once()
    finally:
        event.remove(engine, "before_cursor_execute", block_completion_and_recovery)
        event.remove(db_session, "after_rollback", note_rollback)
        diagnostic_logger.removeHandler(handler)
    assert events.index("diagnostic") < events.index("rollback")
    assert identified == ["another-source"]
    with Session(engine) as observer:
        task = observer.get(LibraryImportTask, task_id)
        assert task.state == "RUNNING"
        assert task.completion_outcome == "book"
        assert task.completion_retry_count == 0
        metadata = observer.get(LibraryBookMetadata, "another-book")
        assert metadata is not None and metadata.metadata_state == "COMPLETED"

    with Session(engine) as restarted_session:
        restarted_pipeline = build_readable_resource_pipeline(
            restarted_session, test_settings
        )
        restarted_identify = restarted_pipeline.identify_book.execute

        def count_restarted_identify(source_id: str, **kwargs: object):
            identified.append(source_id)
            return restarted_identify(source_id, **kwargs)

        monkeypatch.setattr(
            restarted_pipeline.identify_book, "execute", count_restarted_identify
        )
        restarted = build_readable_resource_worker(restarted_pipeline)
        assert restarted.startup() == 1
        assert restarted.process_once() == "book"
    assert identified == ["another-source"]
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, task_id).state == "SUCCEEDED"


def test_book_business_integrity_error_is_not_queued_for_retry(
    db_session: Session,
    pending_book_worker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, worker, task_id, second_scan_id = pending_book_worker

    def fail_identify(_source_id: str, **_kwargs: object):
        raise IntegrityError("identify", (), sqlite3.IntegrityError("constraint failed"))

    monkeypatch.setattr(pipeline.identify_book, "execute", fail_identify)
    assert worker.process_once() == "error"
    with Session(db_session.get_bind()) as observer:
        task = observer.get(LibraryImportTask, task_id)
        assert task.state == "FAILED"
        assert task.retry_count == 1
        assert task.completion_outcome is None
    assert worker.process_once() == "scan"
    with Session(db_session.get_bind()) as observer:
        assert observer.get(LibraryImportTask, second_scan_id).state == "SUCCEEDED"


def test_discovery_callback_only_finishes_deferred_book_result(
    db_session: Session,
    pending_book_worker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, worker, task_id, _ = pending_book_worker
    engine = db_session.get_bind()
    identified: list[str] = []
    original_identify = pipeline.identify_book.execute

    def count_identify(source_id: str, **kwargs: object):
        identified.append(source_id)
        return original_identify(source_id, **kwargs)

    monkeypatch.setattr(pipeline.identify_book, "execute", count_identify)
    failed = False

    def fail_once(_connection, _cursor, statement, parameters, context, _many):
        nonlocal failed
        if (
            not failed and context.isupdate
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and task_id in parameters and "SUCCEEDED" in parameters
        ):
            failed = True
            original = sqlite3.OperationalError("interrupted")
            original.time_budget_exceeded = True
            raise OperationalError(statement, parameters, original)

    event.listen(engine, "before_cursor_execute", fail_once)
    try:
        assert worker.process_once() == "deferred"
    finally:
        event.remove(engine, "before_cursor_execute", fail_once)
    assert identified == ["another-source"]
    with Session(engine) as observer:
        task = observer.get(LibraryImportTask, task_id)
        task.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        observer.commit()
    worker._process_discovered_book()
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, task_id).state == "SUCCEEDED"
    assert identified == ["another-source"]


def test_terminal_only_retry_can_run_while_scan_gate_blocks_resource_work(
    db_session: Session,
    pending_book_worker,
) -> None:
    pipeline, _, task_id, _ = pending_book_worker
    now = datetime.now(UTC)
    claimed = pipeline.queue.claim_next_book(started_at=now)
    assert claimed is not None and claimed.id == task_id
    assert claimed.execution_version is not None
    assert pipeline.queue.record_book_completion_intent(
        task_id, execution_version=claimed.execution_version,
        outcome="book_yield", error_summary=None,
    )
    task = db_session.get(LibraryImportTask, task_id)
    assert task is not None
    task.scan_gate_blocked = True
    db_session.commit()
    assert pipeline.queue.defer_book_completion(
        task_id, execution_version=claimed.execution_version,
        attempted_at=now, retryable=True,
    ) == "deferred"
    db_session.commit()
    db_session.expire_all()
    task = db_session.get(LibraryImportTask, task_id)
    assert task is not None and task.scan_gate_blocked is False
    task.next_attempt_at = now - timedelta(seconds=1)
    db_session.commit()
    resumed = pipeline.queue.claim_next_book(started_at=now)
    assert resumed is not None and resumed.id == task_id
    assert resumed.completion_outcome == "book_yield"


def test_forced_process_exit_after_terminal_failure_resumes_only_completion(
    db_session: Session,
    pending_book_worker,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, task_id, _ = pending_book_worker
    database_path = db_session.get_bind().url.database
    assert database_path is not None
    child = r'''
import os
import sqlite3
import sys
from pathlib import Path
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
sys.path.insert(0, sys.argv[3])
from app.db.sqlite import create_sqlite_engine
from app.bootstrap.readable_resource_pipeline import build_readable_resource_pipeline, build_readable_resource_worker
from app.modules.imports.infrastructure.readable_resource_import_schema import LibraryImportTask
engine = create_sqlite_engine(Path(sys.argv[1]))
def fail_terminal(_connection, _cursor, statement, parameters, context, _many):
    if (context.isupdate and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and sys.argv[2] in parameters and "SUCCEEDED" in parameters):
        original = sqlite3.OperationalError("interrupted")
        original.time_budget_exceeded = True
        raise OperationalError(statement, parameters, original)
event.listen(engine, "before_cursor_execute", fail_terminal)
with Session(engine) as session:
    pipeline = build_readable_resource_pipeline(session)
    assert build_readable_resource_worker(pipeline).process_once() == "deferred"
os._exit(23)
'''
    finished = subprocess.run(
        [
            sys.executable, "-c", child, database_path, task_id,
            str(Path(__file__).resolve().parents[4]),
        ],
        check=False, capture_output=True, text=True, timeout=20,
    )
    assert finished.returncode == 23, finished.stderr
    with Session(db_session.get_bind()) as observer:
        task = observer.get(LibraryImportTask, task_id)
        assert task is not None and task.state == "QUEUED"
        assert task.completion_outcome == "book"
        metadata = observer.get(LibraryBookMetadata, "another-book")
        assert metadata is not None and metadata.metadata_state == "COMPLETED"
        task.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        observer.commit()
    with Session(db_session.get_bind()) as restarted_session:
        pipeline = build_readable_resource_pipeline(restarted_session, test_settings)

        def replay_forbidden(_source_id: str, **_kwargs: object):
            pytest.fail("Book business replayed to complete a terminal write")

        monkeypatch.setattr(pipeline.identify_book, "execute", replay_forbidden)
        worker = build_readable_resource_worker(pipeline)
        assert worker.startup() == 0
        assert worker.process_once() == "book"
    with Session(db_session.get_bind()) as observer:
        assert observer.get(LibraryImportTask, task_id).state == "SUCCEEDED"
