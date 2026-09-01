from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import Library
from app.modules.imports.domain.scan_policy import MissingEntryPolicy
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


def test_running_scan_merges_same_policy_without_follow_up(tmp_path: Path) -> None:
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
            assert inserted is False
            assert duplicate.id == first.id
            queue.mark_running(first.id, started_at=datetime(2026, 8, 24, tzinfo=UTC))
            merged, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is False
            assert merged.id == first.id
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
            assert counts == {"RUNNING": 1}
    finally:
        engine.dispose()


def test_running_preserve_scan_keeps_one_prune_follow_up(tmp_path: Path) -> None:
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
            assert inserted is False
            assert merged.id == follow_up.id
    finally:
        engine.dispose()


def test_manual_library_scan_upgrades_queued_preserve_policy(tmp_path: Path) -> None:
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
            assert inserted is False
            assert upgraded.id == first.id
            assert upgraded.missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING

            retained, inserted = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE
            )
            assert inserted is False
            assert retained.id == first.id
            assert retained.missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
    finally:
        engine.dispose()


def test_running_source_preserve_gets_one_prune_follow_up(tmp_path: Path) -> None:
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
            assert inserted is False
            assert merged.id == follow_up.id
            assert merged.missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
    finally:
        engine.dispose()


def test_requeue_failed_source_task_retains_original_policy(tmp_path: Path) -> None:
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

            retried, requeued = queue.requeue_failed_task(task.id)
            assert requeued is True
            assert retried.state == "QUEUED"
            assert retried.missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
    finally:
        engine.dispose()
