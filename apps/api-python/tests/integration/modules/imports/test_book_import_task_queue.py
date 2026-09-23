"""Book work stays in one durable task across requests and worker runs."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibrarySourceNode,
)
from app.modules.imports.application.readable_resource.book_work import BookWork
from app.modules.imports.domain.scan_policy import ScanScope
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath

_NOW = datetime(2026, 9, 23, tzinfo=UTC)


def _node(node_id: str, path: str) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="library",
        relative_path=path,
        path_key=SourceNodeRelativePath(path).path_key,
        name=path.rpartition("/")[2],
        physical_kind="REGULAR_FILE",
        observed_size_bytes=1,
        observed_mtime_ns=1,
        observed_at=_NOW,
    )


@pytest.fixture
def db(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "book-queue.sqlite3")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                )
            )
            session.add_all(
                (
                    _node("source-one", "one.epub"),
                    _node("source-two", "two.epub"),
                )
            )
            session.flush()
            session.add_all(
                (
                    LibraryBook(
                        id="book-one", library_id="library", source_node_id="source-one"
                    ),
                    LibraryBook(
                        id="book-two", library_id="library", source_node_id="source-two"
                    ),
                )
            )
            session.flush()
            session.add_all(
                (
                    LibraryReadableResource(
                        id="resource-one",
                        library_id="library",
                        book_id="book-one",
                        source_node_id="source-one",
                        adapter_id="epub",
                        adapter_version="1",
                        format="EPUB",
                    ),
                    LibraryReadableResource(
                        id="resource-two",
                        library_id="library",
                        book_id="book-two",
                        source_node_id="source-two",
                        adapter_id="epub",
                        adapter_version="1",
                        format="EPUB",
                    ),
                )
            )
            session.commit()
            yield session
    finally:
        engine.dispose()


def test_book_requests_keep_independent_tasks_and_running_scope(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    first = queue.request_book_work(
        book_id="book-one", work=BookWork(resource_ids=("resource-one",)), requested_at=_NOW
    )
    duplicate = queue.request_book_work(
        book_id="book-one", work=BookWork(resource_ids=("resource-one",)), requested_at=_NOW
    )
    assert duplicate.id != first.id
    assert duplicate.request_version == 1
    db.commit()
    db.expire_all()

    claimed = queue.claim_next_book(started_at=_NOW)
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.execution_version == 1
    assert claimed.work.active.resource_ids == ("resource-one",)
    assert claimed.work.pending.is_empty
    db.commit()

    follow_up = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW
    )
    assert follow_up.id not in {first.id, duplicate.id}
    assert follow_up.state == "QUEUED"
    assert follow_up.request_version == 1
    assert claimed.work.active.resource_ids == ("resource-one",)
    assert follow_up.work.pending.identify
    db.commit()
    db.expire_all()

    finished = queue.finish_book_run(
        first.id, execution_version=1, finished_at=_NOW + timedelta(seconds=1)
    )
    assert finished is not None
    assert finished.state == "SUCCEEDED"
    assert finished.work.active.resource_ids == ("resource-one",)
    assert finished.work.pending.is_empty
    assert queue.finish_book_run(
        first.id, execution_version=1, finished_at=_NOW + timedelta(seconds=2)
    ) is None
    db.commit()

    next_run = queue.claim_next_book(started_at=_NOW + timedelta(seconds=2))
    assert next_run is not None and next_run.id in {duplicate.id, follow_up.id}
    assert next_run.execution_version == 1
    assert next_run.work.active == (
        BookWork(resource_ids=("resource-one",))
        if next_run.id == duplicate.id else BookWork(identify=True)
    )
    assert next_run.work.pending.is_empty
    done = queue.finish_book_run(
        next_run.id, execution_version=1, finished_at=_NOW + timedelta(seconds=3)
    )
    assert done is not None and done.state == "SUCCEEDED"
    db.commit()
    assert db.scalar(
        select(func.count()).select_from(LibraryImportTask).where(
            LibraryImportTask.kind == "IMPORT_BOOK"
        )
    ) == 3


def test_new_request_does_not_change_running_scan_phase(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    requested = queue.request_book_work(
        book_id="book-one",
        work=BookWork(
            scan_scopes=(ScanScope("one.epub", False),),
            resource_ids=("resource-one",),
        ),
        requested_at=_NOW,
    )
    claimed = queue.claim_next_book(started_at=_NOW)
    assert claimed is not None and claimed.execution_version == 1
    assert queue.advance_book_phase(
        requested.id, execution_version=1, phase="RESOURCES"
    )
    updated = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW
    )
    assert updated.id != requested.id and updated.phase == "IDENTIFY"
    db.commit()
    running = queue.get_book_task(requested.id)
    assert running is not None and running.phase == "RESOURCES"
    assert running.state == "RUNNING"
    assert queue.claim_book_task(updated.id, started_at=_NOW).phase == "IDENTIFY"


def test_book_claim_survives_process_termination(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    requested = queue.request_book_work(
        book_id="book-one",
        work=BookWork(resource_ids=("resource-one",)),
        requested_at=_NOW,
    )
    db.commit()
    database_path = db.get_bind().url.database
    assert database_path is not None
    child = r'''
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from sqlalchemy.orm import Session
from app.db.sqlite import create_sqlite_engine
from app.modules.imports.infrastructure.readable_resource.task_queue import SqlAlchemyLibraryImportTaskQueue
engine = create_sqlite_engine(Path(sys.argv[1]))
with Session(engine) as session:
    claimed = SqlAlchemyLibraryImportTaskQueue(session).claim_next_book(
        started_at=datetime(2026, 9, 23, tzinfo=timezone.utc)
    )
    assert claimed is not None and claimed.id == sys.argv[2]
    session.commit()
os._exit(23)
'''
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            database_path,
            requested.id,
            str(Path(__file__).resolve().parents[4]),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert finished.returncode == 23, finished.stderr
    db.expire_all()
    running = db.get(LibraryImportTask, requested.id)
    assert running is not None and running.state == "RUNNING"
    assert queue.fail_interrupted_tasks_on_startup(
        finished_at=_NOW + timedelta(seconds=1)
    ) == 1
    db.commit()
    assert queue.claim_next_book(started_at=_NOW + timedelta(seconds=1)) is None
    interrupted = db.get(LibraryImportTask, requested.id)
    assert interrupted is not None and interrupted.state == "FAILED"
    assert interrupted.error_summary == "WORKER_INTERRUPTED"


def test_book_request_marks_only_its_metadata_revision_pending(db: Session) -> None:
    db.add_all(
        (
            LibraryBookMetadata(
                book_id="book-one",
                title="One",
                normalized_title="one",
                import_revision=4,
                metadata_pending=False,
                metadata_state="COMPLETED",
            ),
            LibraryBookMetadata(
                book_id="book-two",
                title="Two",
                normalized_title="two",
                import_revision=7,
                metadata_pending=False,
                metadata_state="COMPLETED",
            ),
        )
    )
    db.commit()
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    requested = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW
    )
    db.expire_all()
    one = db.get(LibraryBookMetadata, "book-one")
    two = db.get(LibraryBookMetadata, "book-two")
    assert one is not None and two is not None
    assert (one.import_revision, one.metadata_pending, one.metadata_state) == (
        4, False, "COMPLETED",
    )
    assert (two.import_revision, two.metadata_pending, two.metadata_state) == (
        7,
        False,
        "COMPLETED",
    )
    claimed = queue.claim_next_book(started_at=_NOW)
    assert claimed is not None and claimed.execution_version is not None
    db.expire_all()
    assert db.get(LibraryBookMetadata, "book-one").metadata_pending is True
    with pytest.raises(ValueError, match="BOOK_IDENTIFICATION_PENDING"):
        queue.finish_book_run(
            requested.id,
            execution_version=claimed.execution_version,
            finished_at=_NOW,
        )
    failed = queue.fail_book_run(
        requested.id,
        execution_version=claimed.execution_version,
        error_summary="IDENTIFICATION_FAILED",
        failed_at=_NOW,
    )
    assert failed is not None and failed.state == "FAILED"
    db.expire_all()
    assert db.get(LibraryBookMetadata, "book-one").metadata_pending is False
    assert db.get(LibraryBookMetadata, "book-one").metadata_state == "FAILED"
    continued = queue.continue_book_task(requested.id, continued_at=_NOW)
    assert continued is not None and continued[1]
    db.expire_all()
    assert db.get(LibraryBookMetadata, "book-one").metadata_pending is False
    assert db.get(LibraryBookMetadata, "book-one").metadata_state == "FAILED"


def test_failed_book_run_does_not_consume_request_arriving_during_execution(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    requested = queue.request_book_work(
        book_id="book-one",
        work=BookWork(resource_ids=("resource-one",)),
        requested_at=_NOW,
    )
    claimed = queue.claim_next_book(started_at=_NOW)
    assert claimed is not None and claimed.execution_version is not None
    later = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW
    )
    assert queue.book_run_is_current(requested.id, execution_version=1)
    assert queue.book_run_is_current(
        requested.id, execution_version=1, require_latest_request=True
    )
    failed = queue.fail_book_run(
        requested.id,
        execution_version=claimed.execution_version,
        error_summary="RESOURCE_FAILED",
        failed_at=_NOW,
    )
    assert failed is not None and failed.state == "FAILED"
    assert failed.work.active.resource_ids == ("resource-one",)
    assert failed.work.pending.is_empty
    db.commit()
    db.expire_all()
    next_run = queue.claim_next_book(started_at=_NOW)
    assert next_run is not None and next_run.id == later.id
    assert next_run.execution_version == 1
    assert next_run.work.active.identify


def test_book_request_rejects_other_book_and_outside_scope(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    with pytest.raises(ValueError, match="RESOURCE_OUTSIDE_BOOK"):
        queue.request_book_work(
            book_id="book-one",
            work=BookWork(resource_ids=("resource-two",)),
            requested_at=_NOW,
        )
    with pytest.raises(ValueError, match="SCAN_SCOPE_OUTSIDE_BOOK"):
        queue.request_book_work(
            book_id="book-one",
            work=BookWork(scan_scopes=(ScanScope("two.epub"),)),
            requested_at=_NOW,
        )
    assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 0


def test_book_resource_cursor_is_ordered_and_rejects_stale_run(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    requested = queue.request_book_work(
        book_id="book-one",
        work=BookWork(resource_ids=("resource-one",)),
        requested_at=_NOW,
    )
    claimed = queue.claim_next_book(started_at=_NOW)
    assert claimed is not None and claimed.execution_version == 1
    assert queue.book_run_is_current(requested.id, execution_version=1)
    assert not queue.book_run_is_current(requested.id, execution_version=2)
    with pytest.raises(ValueError, match="BOOK_RESOURCE_CURSOR_OUT_OF_ORDER"):
        queue.advance_book_resource_cursor(
            requested.id, execution_version=1, resource_id="resource-two"
        )
    assert queue.advance_book_resource_cursor(
        requested.id, execution_version=1, resource_id="resource-one"
    )
    db.commit()
    db.expire_all()
    recovered = db.get(LibraryImportTask, requested.id)
    assert recovered is not None and recovered.resource_cursor == "resource-one"
    assert not queue.advance_book_resource_cursor(
        requested.id, execution_version=2, resource_id="resource-one"
    )
    finished = queue.finish_book_run(
        requested.id, execution_version=1, finished_at=_NOW
    )
    assert finished is not None and finished.resource_cursor == "resource-one"
    assert not queue.book_run_is_current(requested.id, execution_version=1)


def test_book_failure_is_terminal_and_continue_creates_new_execution(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    requested = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW
    )
    db.commit()

    claimed = queue.claim_next_book(started_at=_NOW)
    assert claimed is not None and claimed.id == requested.id
    failed = queue.fail_book_run(
        requested.id,
        execution_version=claimed.execution_version,
        error_summary="IDENTIFICATION_FAILED",
        failed_at=_NOW,
    )
    assert failed is not None and failed.state == "FAILED"
    db.commit()
    assert queue.claim_next_book(started_at=_NOW + timedelta(days=1)) is None
    continued = queue.continue_book_task(requested.id, continued_at=_NOW)
    assert continued is not None
    new_task, created = continued
    assert created and new_task.id != requested.id
    assert new_task.state == "QUEUED"
    assert db.get(LibraryImportTask, requested.id).state == "FAILED"


def test_failed_book_is_terminal_and_new_request_has_fresh_work(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    first = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW,
    )
    running = queue.claim_next_book(started_at=_NOW)
    assert running is not None and running.id == first.id
    failed = queue.fail_book_run(
        first.id, execution_version=running.execution_version,
        error_summary="IDENTIFICATION_FAILED", failed_at=_NOW,
    )
    assert failed is not None and failed.state == "FAILED"
    db.commit()
    assert queue.claim_next_book(started_at=_NOW + timedelta(days=1)) is None
    again = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW,
    )
    assert again.id != first.id
    claimed = queue.claim_next_book(started_at=_NOW)
    assert claimed is not None and claimed.id == again.id
    assert claimed.work.active.identify
    assert claimed.resource_cursor is None
    assert db.get(LibraryImportTask, first.id).state == "FAILED"


def test_startup_fails_only_started_book_and_keeps_fresh_queued(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    started = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW,
    )
    running = queue.claim_next_book(started_at=_NOW)
    assert running is not None and running.id == started.id
    fresh = queue.request_book_work(
        book_id="book-one", work=BookWork(identify=True), requested_at=_NOW,
    )
    db.commit()
    assert queue.fail_interrupted_tasks_on_startup(finished_at=_NOW) == 1
    db.commit()
    db.expire_all()
    assert db.get(LibraryImportTask, started.id).state == "FAILED"
    assert db.get(LibraryImportTask, started.id).error_summary == "WORKER_INTERRUPTED"
    assert db.get(LibraryImportTask, fresh.id).state == "QUEUED"
    next_run = queue.claim_next_book(started_at=_NOW)
    assert next_run is not None and next_run.id == fresh.id


def test_interrupted_book_stays_failed_after_restart(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    requested = queue.request_book_work(
        book_id="book-one", work=BookWork(resource_ids=("resource-one",)), requested_at=_NOW
    )
    first_claim = queue.claim_next_book(started_at=_NOW)
    assert first_claim is not None and first_claim.execution_version == 1
    db.commit()
    db.expire_all()

    restart_time = _NOW + timedelta(seconds=10)
    assert queue.fail_interrupted_tasks_on_startup(finished_at=restart_time) == 1
    db.commit()
    db.expire_all()

    assert queue.claim_next_book(started_at=restart_time) is None
    interrupted = db.get(LibraryImportTask, requested.id)
    assert interrupted is not None
    assert interrupted.state == "FAILED"
    assert interrupted.error_summary == "WORKER_INTERRUPTED"
