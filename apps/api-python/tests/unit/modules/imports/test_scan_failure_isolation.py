"""Scan failures must only block tasks that truly depend on their input."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibraryBook, LibraryBookMetadata, LibrarySourceNode
from app.modules.imports.domain.scan_policy import MissingEntryPolicy, ScanScope
from app.modules.imports.infrastructure.readable_resource.book_completion import (
    BookImportCompletion,
)
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryReadableResource,
)
from app.modules.library.public import SourceNodeRelativePath


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "scan-failure.sqlite3")
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
            session.commit()
            yield session
    finally:
        engine.dispose()


def _node(db: Session, node_id: str, relative_path: str, kind: str) -> None:
    is_directory = kind == "DIRECTORY"
    db.add(
        LibrarySourceNode(
            id=node_id,
            library_id="library",
            relative_path=relative_path,
            path_key=SourceNodeRelativePath(relative_path).path_key,
            name=relative_path.rpartition("/")[2],
            physical_kind=kind,
            observed_size_bytes=None if is_directory else 1,
            observed_mtime_ns=0 if is_directory else 1,
            observed_at=datetime(2026, 9, 13, tzinfo=UTC),
        )
    )
    db.flush()


def _resource(
    db: Session,
    *,
    resource_id: str,
    node_id: str,
    book_id: str,
    file_format: str,
    adapter_id: str,
) -> None:
    db.add(
        LibraryReadableResource(
            id=resource_id,
            library_id="library",
            book_id=book_id,
            source_node_id=node_id,
            adapter_id=adapter_id,
            adapter_version="1",
            format=file_format,
        )
    )
    db.flush()


def _resource_for_library(
    db: Session,
    *,
    library_id: str,
    resource_id: str,
    node_id: str,
    book_id: str,
    file_format: str,
    adapter_id: str,
) -> None:
    db.add(
        LibraryReadableResource(
            id=resource_id,
            library_id=library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter_id=adapter_id,
            adapter_version="1",
            format=file_format,
        )
    )
    db.flush()


def _book(db: Session, book_id: str, node_id: str) -> None:
    db.add(LibraryBook(id=book_id, library_id="library", source_node_id=node_id))
    db.flush()


def _failed_scan(
    db: Session,
    queue: SqlAlchemyLibraryImportTaskQueue,
    scopes: tuple[ScanScope, ...] | None,
) -> str:
    task, _ = queue.request_library_scan(
        "library",
        missing_entry_policy=MissingEntryPolicy.PRESERVE,
        scan_scopes=scopes,
    )
    queue.mark_running(task.id, started_at=datetime(2026, 9, 13, tzinfo=UTC))
    queue.mark_failed(
        task.id,
        error_summary="SOURCE_SCAN_INCOMPLETE",
        finished_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    db.flush()
    return task.id


def _created(db: Session, task_id: str, offset: int) -> None:
    row = db.get(LibraryImportTask, task_id)
    assert row is not None
    row.created_at = datetime(2026, 9, 13, tzinfo=UTC) + timedelta(seconds=offset)


def test_failed_full_scan_does_not_block_single_file_resource(db: Session) -> None:
    _node(db, "file-node", "book.epub", "REGULAR_FILE")
    _book(db, "file-book", "file-node")
    _resource(
        db,
        resource_id="file-resource",
        node_id="file-node",
        book_id="file-book",
        file_format="EPUB",
        adapter_id="epub",
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    _failed_scan(db, queue, None)
    task = queue.enqueue(
        kind="IMPORT_RESOURCE",
        library_id="library",
        resource_id="file-resource",
        source_node_id="file-node",
    )
    _created(db, task.id, 10)
    db.flush()

    selected = queue.next_queued()

    assert selected is not None and selected.id == task.id


def test_failed_scoped_scan_does_not_block_independent_directory_resource(
    db: Session,
) -> None:
    for node_id, path in (("good-node", "good"), ("bad-node", "bad")):
        _node(db, node_id, path, "DIRECTORY")
        _book(db, f"{node_id}-book", node_id)
        _resource(
            db,
            resource_id=f"{node_id}-resource",
            node_id=node_id,
            book_id=f"{node_id}-book",
            file_format="IMAGE_DIR",
            adapter_id="image_dir",
        )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    _failed_scan(db, queue, (ScanScope("bad", True),))
    good = queue.enqueue(
        kind="IMPORT_RESOURCE",
        library_id="library",
        resource_id="good-node-resource",
        source_node_id="good-node",
    )
    blocked = queue.enqueue(
        kind="IMPORT_RESOURCE",
        library_id="library",
        resource_id="bad-node-resource",
        source_node_id="bad-node",
    )
    _created(db, blocked.id, 10)
    _created(db, good.id, 20)
    db.flush()

    selected = queue.next_queued()

    assert selected is not None and selected.id == good.id


def test_retry_success_releases_dependent_directory_resource(db: Session) -> None:
    _node(db, "bad-node", "bad", "DIRECTORY")
    _book(db, "bad-book", "bad-node")
    _resource(
        db,
        resource_id="bad-resource",
        node_id="bad-node",
        book_id="bad-book",
        file_format="IMAGE_DIR",
        adapter_id="image_dir",
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    failed_id = _failed_scan(db, queue, (ScanScope("bad", True),))
    task = queue.enqueue(
        kind="IMPORT_RESOURCE",
        library_id="library",
        resource_id="bad-resource",
        source_node_id="bad-node",
    )
    db.flush()
    assert queue.next_queued() is None

    queue.mark_succeeded(failed_id, finished_at=datetime(2026, 9, 13, tzinfo=UTC))
    db.flush()

    selected = queue.next_queued()
    assert selected is not None and selected.id == task.id


def test_failed_scan_does_not_block_another_library_task(db: Session) -> None:
    db.add(
        Library(
            id="other-library",
            name="Other",
            root_path="/tmp/other",
            organization_mode="FLAT",
        )
    )
    db.flush()
    db.add(
        LibrarySourceNode(
            id="other-file-node",
            library_id="other-library",
            relative_path="other.epub",
            path_key=SourceNodeRelativePath("other.epub").path_key,
            name="other.epub",
            physical_kind="REGULAR_FILE",
            observed_size_bytes=1,
            observed_mtime_ns=1,
            observed_at=datetime(2026, 9, 13, tzinfo=UTC),
        )
    )
    db.flush()
    db.add(
        LibraryBook(
            id="other-book", library_id="other-library", source_node_id="other-file-node"
        )
    )
    db.flush()
    _resource_for_library(
        db,
        library_id="other-library",
        resource_id="other-resource",
        node_id="other-file-node",
        book_id="other-book",
        file_format="EPUB",
        adapter_id="epub",
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    _failed_scan(db, queue, (ScanScope("bad", True),))
    task = queue.enqueue(
        kind="IMPORT_RESOURCE",
        library_id="other-library",
        resource_id="other-resource",
        source_node_id="other-file-node",
    )
    db.flush()

    selected = queue.next_queued()

    assert selected is not None and selected.id == task.id


def test_deleting_a_failed_scan_is_not_treated_as_success(db: Session) -> None:
    _node(db, "bad-node", "bad", "DIRECTORY")
    _book(db, "bad-book", "bad-node")
    _resource(
        db,
        resource_id="bad-resource",
        node_id="bad-node",
        book_id="bad-book",
        file_format="IMAGE_DIR",
        adapter_id="image_dir",
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    failed_id = _failed_scan(db, queue, (ScanScope("bad", True),))
    task = queue.enqueue(
        kind="IMPORT_RESOURCE",
        library_id="library",
        resource_id="bad-resource",
        source_node_id="bad-node",
    )
    db.flush()
    assert queue.next_queued() is None

    db.delete(db.get(LibraryImportTask, failed_id))
    db.flush()

    selected = queue.next_queued()
    assert selected is not None and selected.id == task.id
    assert db.get(LibraryImportTask, task.id).state == "QUEUED"  # type: ignore[union-attr]


def test_worker_restart_and_scan_merge_release_dependent_resource(db: Session) -> None:
    _node(db, "bad-node", "bad", "DIRECTORY")
    _book(db, "bad-book", "bad-node")
    _resource(
        db,
        resource_id="bad-resource",
        node_id="bad-node",
        book_id="bad-book",
        file_format="IMAGE_DIR",
        adapter_id="image_dir",
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    task, _ = queue.request_library_scan(
        "library",
        missing_entry_policy=MissingEntryPolicy.PRESERVE,
        scan_scopes=(ScanScope("bad", True),),
    )
    queue.mark_running(task.id, started_at=datetime(2026, 9, 13, tzinfo=UTC))
    resource_task = queue.enqueue(
        kind="IMPORT_RESOURCE",
        library_id="library",
        resource_id="bad-resource",
        source_node_id="bad-node",
    )
    db.flush()

    # A restart turns the interrupted scan into a recoverable failure.
    assert queue.fail_interrupted_tasks_on_startup(
        finished_at=datetime(2026, 9, 13, tzinfo=UTC)
    ) == 1
    db.flush()
    assert queue.next_queued() is None

    # A new request merges the unfinished range back into one queued scan.
    merged, inserted = queue.request_library_scan(
        "library",
        missing_entry_policy=MissingEntryPolicy.PRESERVE,
        scan_scopes=(ScanScope("bad", True),),
    )
    assert inserted is True and merged.state == "QUEUED"
    db.flush()
    # The queued scan itself is runnable; the dependent resource still waits.
    runnable_scan = queue.next_queued()
    assert runnable_scan is not None and runnable_scan.kind == "SCAN_LIBRARY"

    queue.mark_running(merged.id, started_at=datetime(2026, 9, 13, tzinfo=UTC))
    queue.mark_succeeded(merged.id, finished_at=datetime(2026, 9, 13, tzinfo=UTC))
    db.flush()

    selected = queue.next_queued()
    assert selected is not None and selected.id == resource_task.id


def test_scoped_scan_does_not_block_identification_of_other_book(db: Session) -> None:
    _node(db, "other-node", "other", "DIRECTORY")
    _node(db, "book-node", "book.epub", "REGULAR_FILE")
    _book(db, "book", "book-node")
    db.add(
        LibraryBookMetadata(
            book_id="book",
            title="Book",
            normalized_title="book",
            metadata_pending=True,
            import_revision=1,
        )
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    queue.request_library_scan(
        "library",
        missing_entry_policy=MissingEntryPolicy.PRESERVE,
        scan_scopes=(ScanScope("other", True),),
    )
    db.flush()

    prepared = BookImportCompletion(db).prepare_ready()

    assert [item.book_id for item in prepared] == ["book"]


def test_full_scan_still_waits_for_identification(db: Session) -> None:
    _node(db, "book-node", "book.epub", "REGULAR_FILE")
    _book(db, "book", "book-node")
    db.add(
        LibraryBookMetadata(
            book_id="book",
            title="Book",
            normalized_title="book",
            metadata_pending=True,
            import_revision=1,
        )
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    queue.request_library_scan(
        "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
    )
    db.flush()

    assert BookImportCompletion(db).prepare_ready() == ()
