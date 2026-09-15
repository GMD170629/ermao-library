"""Persist task outcomes after transient failures without rerunning the work."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.models import Library, LibraryBook, LibraryBookMetadata, LibrarySourceNode
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
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("interrupted")
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
            raise OperationalError(
                "COMMIT", None, sqlite3.OperationalError("interrupted")
            )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", interrupt_terminal_statement)
    event.listen(db_session, "before_commit", interrupt_terminal_commit)
    try:
        for _ in range(2):
            assert worker.process_once() == "deferred"
            with Session(engine) as observer:
                first = observer.get(LibraryImportTask, first_id)
                second = observer.get(LibraryImportTask, second_id)
                assert first is not None and first.state == "RUNNING"
                assert first.finished_at is None
                assert second is not None and second.state == "QUEUED"
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
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("interrupted")
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

    assert worker.process_once() == "cancelled"
    assert scanned_libraries == ["test-library"]
    with Session(engine) as observer:
        assert observer.get(LibraryImportTask, first_id) is None
        second = observer.get(LibraryImportTask, second_id)
        assert second is not None and second.state == "QUEUED"
        assert list(observer.scalars(select(LibraryImportTask.id))) == [second_id]

    assert worker.process_once() == "scan"
    assert scanned_libraries == ["test-library", "second-library"]


def test_identification_failure_preserves_scans_and_retries_after_worker_restart(
    db_session: Session,
    scanning_pipeline: tuple[ReadableResourcePipeline, str, str],
    test_settings: Settings,
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

    insertion_attempts = 0
    interrupt_identification = True

    def interrupt_identification_insert(
        _connection, _cursor, statement, parameters, context, _executemany
    ) -> None:
        nonlocal insertion_attempts
        if (
            context.isinsert
            and context.compiled.statement.table.name == LibraryImportTask.__tablename__
            and "IDENTIFY_BOOK" in parameters
        ):
            insertion_attempts += 1
            if interrupt_identification:
                raise OperationalError(
                    statement, parameters, sqlite3.OperationalError("interrupted")
                )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", interrupt_identification_insert)
    try:
        # Failed compensation must neither undo a finished scan nor prevent the
        # next already-queued scan from making progress.
        assert worker.process_once() == "scan"
        assert insertion_attempts == 1
        assert worker.process_once() == "deferred"
        assert insertion_attempts == 2
        with Session(engine) as observer:
            assert set(observer.scalars(select(LibraryImportTask.state))) == {
                "SUCCEEDED"
            }
            metadata = observer.get(LibraryBookMetadata, "pending-book")
            assert metadata is not None and metadata.metadata_pending
            assert metadata.metadata_state == "WAITING_IMPORT"

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

        # Reconstruct the complete worker graph from persisted state, as a
        # restarted process does; startup recovery never attempts identification.
        with Session(engine) as restarted_session:
            restarted_pipeline = build_readable_resource_pipeline(
                restarted_session, test_settings
            )
            restarted = build_readable_resource_worker(restarted_pipeline)
            assert restarted.startup() == 1
            assert insertion_attempts == 2
            assert restarted.process_once() == "deferred"
            assert insertion_attempts == 3
            with Session(engine) as observer:
                interrupted = observer.get(LibraryImportTask, "interrupted-scan")
                assert interrupted is not None and interrupted.state == "FAILED"
                assert interrupted.finished_at is not None
                assert interrupted.error_summary == "WORKER_INTERRUPTED"
                metadata = observer.get(LibraryBookMetadata, "pending-book")
                assert metadata is not None and metadata.metadata_pending

            interrupt_identification = False
            assert restarted.process_once() == "identified"
            assert insertion_attempts == 4
            assert restarted.process_once() == "idle"
            assert insertion_attempts == 4

        with Session(engine) as observer:
            metadata = observer.get(LibraryBookMetadata, "pending-book")
            assert metadata is not None and not metadata.metadata_pending
            assert metadata.metadata_state == "COMPLETED"
            assert metadata.processed_revision == 3
            identification = observer.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IDENTIFY_BOOK"
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
        event.remove(engine, "before_cursor_execute", interrupt_identification_insert)
