from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import Library
from app.modules.imports.domain.scan_policy import MissingEntryPolicy, ScanScope
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibrarySourceNode,
)
from app.modules.library.public import SourceNodeRelativePath


def test_scope_requests_persist_independently_and_preserve_running_scope(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "scope.sqlite3")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path),
                    organization_mode="FLAT",
                )
            )
            session.commit()
            queue = SqlAlchemyLibraryImportTaskQueue(session)
            first, _ = queue.request_library_scan(
                "library",
                missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                scan_scopes=(ScanScope("a", True),),
            )
            session.commit()
            session.expire_all()
            restored = queue.get_task(first.id)
            assert restored is not None and restored.scan_scopes == (
                ScanScope("a", True),
            )
            merged, added = queue.request_library_scan(
                "library",
                missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                scan_scopes=(ScanScope("a/b"), ScanScope("c")),
            )
            assert added and merged.id != first.id and merged.scan_scopes == (
                ScanScope("a/b"),
                ScanScope("c"),
            )
            queue.mark_running(first.id, started_at=datetime.now(UTC))
            following, added = queue.request_library_scan(
                "library",
                missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                scan_scopes=(ScanScope("d"),),
            )
            assert added and following.id != first.id
            full, added = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING
            )
            assert added and full.id != following.id and full.scan_scopes is None
            running = queue.get_task(first.id)
            assert running is not None and running.scan_scopes == first.scan_scopes
    finally:
        engine.dispose()


def test_running_scan_preserves_each_new_request(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "scan.sqlite3")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                    enabled=True,
                )
            )
            session.commit()
            queue = SqlAlchemyLibraryImportTaskQueue(session)
            first, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is True
            duplicate, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is True
            assert duplicate.id != first.id
            queue.mark_running(first.id, started_at=datetime(2026, 8, 24, tzinfo=UTC))
            merged, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is True
            assert merged.id != first.id
            session.commit()

            counts = dict(
                session.execute(
                    select(LibraryImportTask.state, func.count())
                    .where(
                        LibraryImportTask.library_id == "library",
                        LibraryImportTask.kind == "SCAN_LIBRARY",
                        LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
                    )
                    .group_by(LibraryImportTask.state)
                ).all()
            )
            assert counts == {"RUNNING": 1, "QUEUED": 2}
    finally:
        engine.dispose()


def test_running_preserve_scan_keeps_independent_prune_request(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "scan-upgrade.sqlite3")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                    enabled=True,
                )
            )
            session.commit()
            queue = SqlAlchemyLibraryImportTaskQueue(session)
            running, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is True
            queue.mark_running(running.id, started_at=datetime(2026, 8, 24, tzinfo=UTC))

            follow_up, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING
            )
            assert inserted is True
            assert follow_up.missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
            merged, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is True
            assert merged.id != follow_up.id
    finally:
        engine.dispose()


def test_manual_library_scan_does_not_change_queued_request_policy(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "upgrade.sqlite3")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                    enabled=True,
                )
            )
            session.commit()
            queue = SqlAlchemyLibraryImportTaskQueue(session)
            first, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is True
            upgraded, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING
            )
            assert inserted is True
            assert upgraded.id != first.id
            assert queue.get_task(first.id).missing_entry_policy is MissingEntryPolicy.PRESERVE
            assert upgraded.missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING

            retained, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is True
            assert retained.id not in {first.id, upgraded.id}
            assert retained.missing_entry_policy is MissingEntryPolicy.PRESERVE
    finally:
        engine.dispose()


def test_running_source_preserves_each_request_policy(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "source-upgrade.sqlite3")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                    enabled=True,
                )
            )
            session.add(
                LibrarySourceNode(
                    id="source",
                    library_id="library",
                    parent_id=None,
                    parent_physical_kind=None,
                    relative_path="source.epub",
                    path_key=SourceNodeRelativePath("source.epub").path_key,
                    name="source.epub",
                    physical_kind="REGULAR_FILE",
                    observed_size_bytes=1,
                    observed_mtime_ns=1,
                    observed_at=datetime(2026, 9, 1, tzinfo=UTC),
                )
            )
            session.commit()
            queue = SqlAlchemyLibraryImportTaskQueue(session)
            first = queue.enqueue(
                kind="CONTINUE_SOURCE",
                library_id="library",
                source_node_id="source",
                missing_entry_policy=MissingEntryPolicy.PRESERVE,
            )
            queue.mark_running(first.id, started_at=datetime(2026, 9, 1, tzinfo=UTC))

            follow_up, inserted = queue.request_source_scan(
                library_id="library",
                source_node_id="source",
                missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
            )
            assert inserted is True
            assert follow_up.missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
            merged, inserted = queue.request_source_scan(
                library_id="library",
                source_node_id="source",
                missing_entry_policy=MissingEntryPolicy.PRESERVE,
            )
            assert inserted is True
            assert merged.id != follow_up.id
            assert merged.missing_entry_policy is MissingEntryPolicy.PRESERVE
    finally:
        engine.dispose()


def test_new_request_after_failed_source_task_retains_original_policy(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "source-retry-policy.sqlite3")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                    enabled=True,
                )
            )
            session.add(
                LibrarySourceNode(
                    id="source",
                    library_id="library",
                    parent_id=None,
                    parent_physical_kind=None,
                    relative_path="source.epub",
                    path_key=SourceNodeRelativePath("source.epub").path_key,
                    name="source.epub",
                    physical_kind="REGULAR_FILE",
                    observed_size_bytes=1,
                    observed_mtime_ns=1,
                    observed_at=datetime(2026, 9, 1, tzinfo=UTC),
                )
            )
            session.commit()
            queue = SqlAlchemyLibraryImportTaskQueue(session)
            task = queue.enqueue(
                kind="CONTINUE_SOURCE",
                library_id="library",
                source_node_id="source",
                missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
            )
            queue.mark_running(task.id, started_at=datetime(2026, 9, 1, tzinfo=UTC))
            queue.mark_failed(
                task.id,
                error_summary="SOURCE_SCAN_START_UNAVAILABLE",
                finished_at=datetime(2026, 9, 1, tzinfo=UTC),
            )

            failed = queue.get_task(task.id)
            retried, inserted = queue.request_source_scan(
                library_id=failed.library_id,
                source_node_id=failed.source_node_id,
                missing_entry_policy=failed.missing_entry_policy,
            )
            assert inserted is True and retried.id != task.id
            assert queue.get_task(task.id).state == "FAILED"
            assert retried.state == "QUEUED"
            assert retried.missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
    finally:
        engine.dispose()


@pytest.mark.parametrize("state", ["RUNNING", "SUCCEEDED", "FAILED"])
def test_nonqueued_task_is_not_reported_as_file_activity_busy(db_session, state):
    queue = SqlAlchemyLibraryImportTaskQueue(db_session)
    task = queue.enqueue(kind="SCAN_LIBRARY", library_id="test-library")
    row = db_session.get(LibraryImportTask, task.id)
    row.state = state
    started = datetime(2026, 9, 1, tzinfo=UTC)
    row.started_at = started
    row.error_summary = "previous-result"
    db_session.commit()
    db_session.refresh(row)
    previous_started_at = row.started_at

    with pytest.raises(ValueError, match="IMPORT_TASK_NOT_QUEUED"):
        queue.mark_running(task.id, started_at=datetime(2026, 9, 2, tzinfo=UTC))
    db_session.rollback()
    current = db_session.get(LibraryImportTask, task.id)
    assert current is not None and current.state == state
    assert current.started_at == previous_started_at
    assert current.error_summary == "previous-result"
