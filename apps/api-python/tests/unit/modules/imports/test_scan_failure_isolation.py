"""Scan failures only block tasks that truly depend on their input.

Readiness is driven by a durable incomplete-range marker, not by the lifecycle
of the scan task row. Deleting a failed task therefore never releases work whose
member list was never fully enumerated; only a completed scan range does.
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

    assert selected is not None and selected.id == good.id


def test_completed_scan_range_releases_dependent_directory_resource(
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
    assert queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC)) is None

    # A completed scan is the only operation that clears the range.
    queue.apply_scan_round(
        None, "library", resolved=(ScanScope("bad", True),), incomplete=()
    )
    db.flush()

    selected = queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC))
    assert selected is not None and selected.id == task.id


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
    assert queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC)) is None

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

    assert queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC)) is None
    assert db.get(LibraryImportTask, task.id).state == "QUEUED"  # type: ignore[union-attr]


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


def test_full_scan_gap_blocks_directory_book_work(db: Session) -> None:
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

    assert queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC)) is None


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


@pytest.mark.parametrize("independent", [False, True])
def test_book_claim_does_not_derive_gap_from_each_candidate(
    db: Session, independent: bool
) -> None:
    """Real queued work must skip older blocked books without JSON in claim SQL."""
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    scopes = tuple(
        ScanScope(f"blocked-{index:04d}", True)
        for index in range(24)
    ) if independent else (ScanScope("blocked", True),)
    queue.apply_scan_round(None, "library", resolved=(), incomplete=scopes)
    for index in range(24):
        path = (
            f"blocked-{index:04d}" if independent else f"blocked/book-{index:04d}"
        )
        node_id = f"blocked-node-{index}"
        book_id = f"blocked-book-{index}"
        _node(db, node_id, path, "DIRECTORY")
        _book(db, book_id, node_id)
        queue.request_book_work(
            book_id=book_id,
            work=BookWork(identify=True),
            requested_at=datetime(2026, 9, 13, tzinfo=UTC),
        )
    _node(db, "ready-node", "ready.epub", "REGULAR_FILE")
    _book(db, "ready-book", "ready-node")
    ready = queue.request_book_work(
        book_id="ready-book",
        work=BookWork(identify=True),
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    db.commit()

    statements: list[str] = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "LibraryImportTask" in statement:
            statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        selected = queue.claim_next_book(started_at=datetime(2026, 9, 13, tzinfo=UTC))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)

    assert selected is not None and selected.id == ready.id
    assert statements
    assert all("LibraryImportScanGap" not in statement for statement in statements)


def test_changed_gap_recovers_paged_book_gates_after_restart(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    for index in range(205):
        node_id = f"node-{index}"
        book_id = f"book-{index}"
        _node(db, node_id, f"zone/book-{index}", "DIRECTORY")
        _book(db, book_id, node_id)
        queue.request_book_work(
            book_id=book_id, work=BookWork(identify=True), requested_at=now
        )
    db.commit()

    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("zone", True),)
    )
    db.commit()
    with Session(db.get_bind()) as restarted:
        resumed = SqlAlchemyLibraryImportTaskQueue(restarted)
        assert resumed.claim_next_book(started_at=now) is None
        assert resumed.refresh_scan_gate_page() == 5
        restarted.commit()
        assert resumed.claim_next_book(started_at=now) is None
        resumed.apply_scan_round(
            None, "library", resolved=(ScanScope("zone", True),), incomplete=()
        )
        restarted.commit()
        assert resumed.refresh_scan_gate_page() == 5
        restarted.commit()
        assert resumed.claim_next_book(started_at=now) is not None


def test_gap_scope_paths_treat_percent_and_underscore_literally(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    for path in ("A_%/inner", "Axy/inner"):
        node_id = f"node-{path}"
        book_id = f"book-{path}"
        _node(db, node_id, path, "DIRECTORY")
        _book(db, book_id, node_id)
        queue.request_book_work(
            book_id=book_id, work=BookWork(identify=True), requested_at=now
        )
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("A_%", True),)
    )
    db.commit()

    selected = queue.claim_next_book(started_at=now)
    assert selected is not None and selected.book_id == "book-Axy/inner"
    blocked = db.scalar(
        select(LibraryImportTask).where(LibraryImportTask.book_id == "book-A_%/inner")
    )
    assert blocked is not None and blocked.scan_gate_blocked is True


def test_queued_book_scan_request_can_repair_its_own_gap(db: Session) -> None:
    _node(db, "node", "book", "DIRECTORY")
    _book(db, "book", "node")
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    task = queue.request_book_work(
        book_id="book", work=BookWork(identify=True), requested_at=now
    )
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("book", True),)
    )
    assert queue.claim_next_book(started_at=now) is None

    merged = queue.request_book_work(
        book_id="book",
        work=BookWork(scan_scopes=(ScanScope("book", True),)),
        requested_at=now,
    )
    assert merged.id == task.id
    assert merged.phase == "SCAN"
    db.commit()

    selected = queue.claim_next_book(started_at=now)
    assert selected is not None and selected.id == task.id
    assert selected.work.active.scan_scopes == (ScanScope("book", True),)


def test_yielded_book_scan_request_supersedes_blocked_active_work(db: Session) -> None:
    _node(db, "node", "book", "DIRECTORY")
    _book(db, "book", "node")
    _resource(
        db, resource_id="resource", node_id="node", book_id="book",
        file_format="IMAGE_DIR", adapter_id="image_dir",
    )
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    task = queue.request_book_work(
        book_id="book", work=BookWork(resource_ids=("resource",)), requested_at=now
    )
    claimed = queue.claim_next_book(started_at=now)
    assert claimed is not None and claimed.execution_version == 1
    assert queue.yield_book_run(task.id, execution_version=1, yielded_at=now)
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("book", True),)
    )
    assert queue.claim_next_book(started_at=now) is None

    updated = queue.request_book_work(
        book_id="book",
        work=BookWork(scan_scopes=(ScanScope("book", True),)),
        requested_at=now,
    )
    assert updated.phase == "SCAN"
    assert updated.execution_version == 2
    db.commit()
    resumed = queue.claim_next_book(started_at=now)
    assert resumed is not None and resumed.phase == "SCAN"
    assert resumed.work.active.resource_ids == ("resource",)


def test_relocation_rebinds_gate_to_new_path_without_releasing_it(db: Session) -> None:
    _node(db, "node", "old/book", "DIRECTORY")
    _book(db, "book", "node")
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("old/book", True),)
    )
    task = queue.request_book_work(
        book_id="book", work=BookWork(identify=True), requested_at=now
    )
    assert queue.claim_next_book(started_at=now) is None

    node = db.get(LibrarySourceNode, "node")
    assert node is not None
    node.relative_path = "new/book"
    node.path_key = SourceNodeRelativePath("new/book").path_key
    db.flush()
    queue.reconcile_relocation(SourceRelocation(
        "library", "old/book", "library", "new/book", ("node",), ("book",),
    ))
    db.commit()
    queue.refresh_scan_gate_page()
    assert queue.claim_next_book(started_at=now) is None
    assert db.get(LibraryImportTask, task.id).scan_gate_blocked is True

    queue.apply_scan_round(
        None, "library", resolved=(ScanScope("new/book", True),), incomplete=()
    )
    db.commit()
    assert queue.claim_next_book(started_at=now) is not None


def test_nonrecursive_gap_blocks_ancestors_but_not_nested_siblings(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    for path in ("a", "a/b", "a/b/deep", "a/c"):
        _node(db, f"node-{path}", path, "DIRECTORY")
        _book(db, f"book-{path}", f"node-{path}")
        queue.request_book_work(
            book_id=f"book-{path}", work=BookWork(identify=True), requested_at=now
        )
    queue.apply_scan_round(
        None, "library", resolved=(), incomplete=(ScanScope("a/b", False),)
    )
    db.commit()

    blocked = {
        task.book_id: task.scan_gate_blocked
        for task in db.scalars(select(LibraryImportTask).where(
            LibraryImportTask.kind == "IMPORT_BOOK"
        ))
    }
    assert blocked == {
        "book-a": True, "book-a/b": True,
        "book-a/b/deep": False, "book-a/c": False,
    }
    queue.apply_scan_round(
        None, "library", resolved=(ScanScope("a", False),), incomplete=()
    )
    assert db.get(LibraryImportScanGap, "library").scopes is not None
    queue.apply_scan_round(
        None, "library", resolved=(ScanScope("a/b", False),), incomplete=()
    )
    db.commit()
    assert all(
        task.scan_gate_blocked is False
        for task in db.scalars(select(LibraryImportTask).where(
            LibraryImportTask.kind == "IMPORT_BOOK"
        ))
    )


def test_releasing_shared_gap_keeps_independent_gap_blocked(db: Session) -> None:
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    for path in ("shared/one", "other/two"):
        _node(db, f"node-{path}", path, "DIRECTORY")
        _book(db, f"book-{path}", f"node-{path}")
        queue.request_book_work(
            book_id=f"book-{path}", work=BookWork(identify=True), requested_at=now
        )
    queue.apply_scan_round(None, "library", resolved=(), incomplete=(
        ScanScope("shared", True), ScanScope("other/two", True),
    ))
    queue.apply_scan_round(
        None, "library", resolved=(ScanScope("shared", True),), incomplete=()
    )
    db.commit()
    selected = queue.claim_next_book(started_at=now)
    assert selected is not None and selected.book_id == "book-shared/one"
    assert db.scalar(select(LibraryImportTask.scan_gate_blocked).where(
        LibraryImportTask.book_id == "book-other/two"
    )) is True


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
        retryable=False, failed_at=now,
    )
    assert decode_scan_scopes(db.get(LibraryImportScanGap, "library").scopes) == (
        ScanScope("bad", True),
    )
    good = queue.request_book_work(
        book_id="book-good", work=BookWork(identify=True), requested_at=now
    )
    selected = queue.claim_next_book(started_at=now)
    assert selected is not None and selected.id == good.id
