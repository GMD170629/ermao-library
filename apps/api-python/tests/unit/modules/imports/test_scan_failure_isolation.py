"""Scan gaps retain input facts without gating independently accepted Book work.

ADR 0029 retires queued/running coalescing and scan-gate projections. Explicit
requests have separate execution identities; completing a scan only clears its
covered gap and never revives historical tasks.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.contracts.source_relocation import SourceRelocation
from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryBook,
    LibraryImportScanGap,
    LibrarySourceNode,
)
from app.modules.imports.application.readable_resource.book_work import BookWork
from app.modules.imports.domain.scan_policy import (
    MissingEntryPolicy,
    ScanScope,
    completed_scope_resolves,
    decode_scan_scopes,
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


def _node(
    db: Session,
    node_id: str,
    relative_path: str,
    kind: str,
    library_id: str = "library",
) -> None:
    is_directory = kind == "DIRECTORY"
    db.add(
        LibrarySourceNode(
            id=node_id,
            library_id=library_id,
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
    library_id: str = "library",
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


def _book(db: Session, book_id: str, node_id: str, library_id: str = "library") -> None:
    db.add(
        LibraryBook(id=book_id, library_id=library_id, source_node_id=node_id)
    )
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


def test_failed_scan_record_does_not_block_single_file_resource(db: Session) -> None:
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
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("", True),)
    )
    task = queue.request_book_work(
        book_id="file-book",
        work=BookWork(resource_ids=("file-resource",)),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    _created(db, task.id, 10)
    db.flush()

    selected = queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC))

    assert selected is not None and selected.id == task.id


def test_unrelated_incomplete_range_does_not_block_directory_resource(
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
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("bad", True),)
    )
    good = queue.request_book_work(
        book_id="good-node-book",
        work=BookWork(resource_ids=("good-node-resource",)),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    blocked = queue.request_book_work(
        book_id="bad-node-book",
        work=BookWork(resource_ids=("bad-node-resource",)),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    _created(db, blocked.id, 10)
    _created(db, good.id, 20)
    db.flush()

    selected = queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC))

    assert selected is not None and selected.id == blocked.id
    assert queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC)).id == good.id


def test_completed_scan_range_clears_gap_without_restarting_book(
    db: Session,
) -> None:
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
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("bad", True),)
    )
    task = queue.request_book_work(
        book_id="bad-book",
        work=BookWork(resource_ids=("bad-resource",)),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    db.flush()
    assert queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC)).id == task.id

    # A completed scan is the only operation that clears the range.
    queue.apply_scan_round(
        None, "library", resolved=(ScanScope("bad", True),), incomplete=()
    )
    db.flush()

    selected = queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC))
    assert selected is None
    assert db.get(LibraryImportTask, task.id).state == "RUNNING"
    assert not queue.book_requires_scan("bad-book")


def test_cleaning_failed_task_record_does_not_release_gap(db: Session) -> None:
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
    queue.apply_scan_round(
        failed_id, "library", resolved=(), incomplete=(ScanScope("bad", True),)
    )
    task = queue.request_book_work(
        book_id="bad-book",
        work=BookWork(resource_ids=("bad-resource",)),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    db.flush()
    assert queue.book_requires_scan("bad-book")

    # Remove all historical task records without completing the input.
    db.delete(db.get(LibraryImportTask, failed_id))
    db.flush()
    assert (
        db.scalar(
            select(LibraryImportTask.id).where(
                LibraryImportTask.library_id == "library",
                LibraryImportTask.kind == "SCAN_LIBRARY",
            )
        )
        is None
    )

    assert queue.book_requires_scan("bad-book")
    assert queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC)).id == task.id
    assert db.get(LibraryImportTask, task.id).state == "RUNNING"  # type: ignore[union-attr]


def test_unrelated_library_gap_does_not_block_other_library_task(
    db: Session,
) -> None:
    db.add(
        Library(
            id="other-library",
            name="Other",
            root_path="/tmp/other",
            organization_mode="FLAT",
        )
    )
    db.flush()
    _node(db, "other-file-node", "other.epub", "REGULAR_FILE", "other-library")
    _book(db, "other-book", "other-file-node", library_id="other-library")
    _resource(
        db,
        resource_id="other-resource",
        node_id="other-file-node",
        book_id="other-book",
        file_format="EPUB",
        adapter_id="epub",
        library_id="other-library",
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("bad", True),)
    )
    task = queue.request_book_work(
        book_id="other-book",
        work=BookWork(resource_ids=("other-resource",)),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    db.flush()

    selected = queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC))

    assert selected is not None and selected.id == task.id


def test_scoped_scan_gap_does_not_block_unrelated_book_work(db: Session) -> None:
    _node(db, "other-node", "other", "DIRECTORY")
    _node(db, "book-node", "book", "DIRECTORY")
    _book(db, "book", "book-node")
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    queue.apply_scan_round(
        None,
        "library",
        resolved=(),
        incomplete=(ScanScope("other", True),),
    )
    task = queue.request_book_work(
        book_id="book",
        work=BookWork(identify=True),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    db.flush()

    selected = queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC))

    assert selected is not None and selected.id == task.id


def test_full_scan_gap_preserves_independent_directory_book_work(db: Session) -> None:
    _node(db, "book-node", "book", "DIRECTORY")
    _book(db, "book", "book-node")
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    queue.apply_scan_round(
        None,
        "library",
        resolved=(),
        incomplete=(ScanScope("", True),),
    )
    queue.request_book_work(
        book_id="book",
        work=BookWork(identify=True),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    db.flush()

    assert queue.book_requires_scan("book")
    assert queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC)).book_id == "book"


def test_root_non_recursive_completion_does_not_clear_recursive_gap(
    db: Session,
) -> None:
    assert not completed_scope_resolves(ScanScope("", False), ScanScope("", True))
    assert completed_scope_resolves(ScanScope("", False), ScanScope("", False))
    assert completed_scope_resolves(ScanScope("", True), ScanScope("a/b", True))
    assert not completed_scope_resolves(ScanScope("a", False), ScanScope("a/b", True))

    queue = SqlAlchemyLibraryImportTaskQueue(db)
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("", True),)
    )
    db.flush()
    # A non-recursive root scan never enumerates nested directories.
    queue.apply_scan_round(
        None, "library", resolved=(ScanScope("", False),), incomplete=()
    )
    db.flush()

    gap = db.get(LibraryImportScanGap, "library")
    assert gap is not None
    assert decode_scan_scopes(gap.scopes) == (ScanScope("", True),)


@pytest.mark.parametrize("scope", [ScanScope("", True), ScanScope("zone", True), ScanScope("zone", False)])
@pytest.mark.parametrize("historical_gate", [None, False, True])
def test_claim_ignores_historical_gate_without_reading_gap(db, scope, historical_gate):
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    _node(db, "node", "zone", "DIRECTORY")
    _book(db, "book", "node")
    queue.apply_scan_round(None, "library", resolved=(), incomplete=(scope,))
    first = queue.request_book_work(book_id="book", work=BookWork(identify=True), requested_at=now)
    db.get(LibraryImportTask, first.id).scan_gate_blocked = historical_gate
    second = queue.request_book_work(book_id="book", work=BookWork(identify=True), requested_at=now + timedelta(seconds=1))
    db.commit()
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        assert queue.claim_next_book(started_at=now).id == first.id
        assert queue.claim_next_book(started_at=now).id == second.id
        assert queue.claim_next_book(started_at=now) is None
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert all("LibraryImportScanGap" not in statement for statement in statements)
    assert decode_scan_scopes(db.get(LibraryImportScanGap, "library").scopes) == (scope,)


def test_gap_survives_restart_without_blocking_or_rewriting_queued_work(db):
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    ids = set()
    for index in range(205):
        _node(db, f"node-{index}", f"zone/book-{index}", "DIRECTORY")
        _book(db, f"book-{index}", f"node-{index}")
        task = queue.request_book_work(book_id=f"book-{index}", work=BookWork(identify=True), requested_at=now)
        ids.add(task.id)
    queue.apply_scan_round(None, "library", resolved=(), incomplete=(ScanScope("zone", True),))
    db.commit()
    with Session(db.get_bind()) as resumed:
        restored = SqlAlchemyLibraryImportTaskQueue(resumed)
        assert {restored.claim_next_book(started_at=now).id for _ in range(205)} == ids
        assert restored.claim_next_book(started_at=now) is None
        assert restored.book_requires_scan("book-0")
        restored.apply_scan_round(None, "library", resolved=(ScanScope("zone", True),), incomplete=())
        assert not restored.book_requires_scan("book-0")
        assert all(row.state == "RUNNING" for row in resumed.scalars(select(LibraryImportTask)))


def test_gap_scope_paths_treat_percent_and_underscore_literally(db):
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    for path in ("A_%/inner", "Axy/inner"):
        _node(db, f"node-{path}", path, "DIRECTORY")
        _book(db, f"book-{path}", f"node-{path}")
    queue.apply_scan_round(None, "library", resolved=(), incomplete=(ScanScope("A_%", True),))
    assert queue.book_requires_scan("book-A_%/inner")
    assert not queue.book_requires_scan("book-Axy/inner")


def test_new_scan_request_does_not_supersede_running_resource_work(db):
    _node(db, "node", "book", "DIRECTORY")
    _book(db, "book", "node")
    _resource(db, resource_id="resource", node_id="node", book_id="book", file_format="IMAGE_DIR", adapter_id="image_dir")
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    first = queue.request_book_work(book_id="book", work=BookWork(resource_ids=("resource",)), requested_at=now)
    assert queue.claim_next_book(started_at=now).id == first.id
    queue.apply_scan_round(None, "library", resolved=(), incomplete=(ScanScope("book", True),))
    second = queue.request_book_work(book_id="book", work=BookWork(scan_scopes=(ScanScope("book", True),)), requested_at=now)
    assert second.id != first.id and second.execution_version is None
    assert queue.get_book_task(first.id).work.resource_ids == ("resource",)
    assert queue.get_book_task(first.id).state == "RUNNING"
    assert queue.claim_next_book(started_at=now).id == second.id


def test_relocation_preserves_gap_at_new_path_without_gating_tasks(db):
    _node(db, "node", "old/book", "DIRECTORY")
    _book(db, "book", "node")
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    queue.apply_scan_round(None, "library", resolved=(), incomplete=(ScanScope("old/book", True),))
    node = db.get(LibrarySourceNode, "node")
    node.relative_path = "new/book"
    node.path_key = SourceNodeRelativePath("new/book").path_key
    db.flush()
    queue.reconcile_relocation(SourceRelocation("library", "old/book", "library", "new/book", ("node",), ("book",)))
    assert decode_scan_scopes(db.get(LibraryImportScanGap, "library").scopes) == (ScanScope("new/book", True),)
    assert queue.book_requires_scan("book")
    queue.apply_scan_round(None, "library", resolved=(ScanScope("new/book", True),), incomplete=())
    assert not queue.book_requires_scan("book")


def test_releasing_shared_gap_preserves_independent_gap(db):
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    queue.apply_scan_round(None, "library", resolved=(), incomplete=(ScanScope("shared", True), ScanScope("other/two", True)))
    queue.apply_scan_round(None, "library", resolved=(ScanScope("shared", True),), incomplete=())
    assert decode_scan_scopes(db.get(LibraryImportScanGap, "library").scopes) == (ScanScope("other/two", True),)


def test_failed_full_book_scan_records_only_its_anchor(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    for path in ("bad", "good"):
        _node(db, f"node-{path}", path, "DIRECTORY")
        _book(db, f"book-{path}", f"node-{path}")
    failed = queue.request_book_work(
        book_id="book-bad", work=BookWork(scan_scopes=None), requested_at=now
    )
    claimed = queue.claim_next_book(started_at=now)
    assert claimed is not None and claimed.execution_version == 1
    queue.fail_book_run(
        failed.id, execution_version=1, error_summary="SCAN_FAILED",
        failed_at=now,
    )
    assert decode_scan_scopes(db.get(LibraryImportScanGap, "library").scopes) == (
        ScanScope("bad", True),
    )
    good = queue.request_book_work(
        book_id="book-good", work=BookWork(identify=True), requested_at=now
    )
    selected = queue.claim_next_book(started_at=now)
    assert selected is not None and selected.id == good.id
