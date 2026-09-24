"""Upgrade permits new requests while retaining historical import task rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibraryBook, LibrarySourceNode
from app.modules.imports.application.readable_resource.book_work import BookWork
from app.modules.imports.domain.scan_policy import MissingEntryPolicy
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath


def test_upgrade_removes_single_book_and_queued_scan_keys(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    now = datetime(2026, 9, 24, tzinfo=UTC)
    try:
        command.upgrade(config, "0035_directory_member_cursor")
        with Session(engine) as db:
            db.add(Library(
                id="library", name="Library", root_path=str(tmp_path),
                organization_mode="FLAT",
            ))
            db.add(LibrarySourceNode(
                id="node", library_id="library", relative_path="book.epub",
                path_key=SourceNodeRelativePath("book.epub").path_key,
                name="book.epub", physical_kind="REGULAR_FILE",
                observed_size_bytes=1, observed_mtime_ns=1, observed_at=now,
            ))
            db.flush()
            db.add(LibraryBook(id="book", library_id="library", source_node_id="node"))
            db.commit()
            queue = SqlAlchemyLibraryImportTaskQueue(db)
            first = queue.request_book_work(
                book_id="book", work=BookWork(identify=True), requested_at=now,
            )
            scan, _ = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE,
            )
            db.commit()
        command.upgrade(config, "head")
        indexes = {item["name"] for item in inspect(engine).get_indexes("LibraryImportTask")}
        assert "LibraryImportTask_book_key" not in indexes
        assert "LibraryImportTask_scan_queued_key" not in indexes
        assert "LibraryImportTask_scan_running_key" not in indexes
        with Session(engine) as db:
            queue = SqlAlchemyLibraryImportTaskQueue(db)
            second = queue.request_book_work(
                book_id="book", work=BookWork(identify=True), requested_at=now,
            )
            another_scan, _ = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE,
            )
            db.commit()
            assert second.id != first.id and another_scan.id != scan.id
            assert queue.get_book_task(first.id) is not None
            assert queue.get_task(scan.id) is not None
    finally:
        engine.dispose()


def test_upgrade_preserves_only_unstarted_pending_scope(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "pending-upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    now = datetime(2026, 9, 24, tzinfo=UTC)
    active = {"scanScopes": [], "resourceIds": None, "identify": True, "reasons": []}
    pending = {"scanScopes": [], "resourceIds": [], "identify": True, "reasons": []}
    empty = {"scanScopes": [], "resourceIds": [], "identify": False, "reasons": []}
    try:
        command.upgrade(config, "0036_import_execution_identity")
        with Session(engine) as db:
            db.add(Library(
                id="library", name="Library", root_path=str(tmp_path),
                organization_mode="FLAT",
            ))
            db.add(LibrarySourceNode(
                id="node", library_id="library", relative_path="book.epub",
                path_key=SourceNodeRelativePath("book.epub").path_key,
                name="book.epub", physical_kind="REGULAR_FILE",
                observed_size_bytes=1, observed_mtime_ns=1, observed_at=now,
            ))
            db.flush()
            db.add(LibraryBook(id="book", library_id="library", source_node_id="node"))
            db.flush()
            queue = SqlAlchemyLibraryImportTaskQueue(db)
            attempted = queue.request_book_work(
                book_id="book", work=BookWork(identify=True), requested_at=now,
            )
            queued = queue.request_book_work(
                book_id="book", work=BookWork(identify=True), requested_at=now,
            )
            old = db.get(LibraryImportTask, attempted.id)
            old.state = "RUNNING"
            old.started_at = now
            old.execution_version = 1
            old.book_work = json.dumps({"active": active, "pending": pending})
            waiting = db.get(LibraryImportTask, queued.id)
            waiting.book_work = json.dumps({"active": empty, "pending": active})
            db.commit()
        command.upgrade(config, "head")
        with Session(engine) as db:
            rows = db.query(LibraryImportTask).filter_by(kind="IMPORT_BOOK").all()
            old = db.get(LibraryImportTask, attempted.id)
            waiting = db.get(LibraryImportTask, queued.id)
            assert old.state == "FAILED" and old.error_summary == "WORKER_INTERRUPTED"
            assert waiting.state == "QUEUED"
            queue = SqlAlchemyLibraryImportTaskQueue(db)
            assert queue.get_book_task(queued.id).work.resource_ids is None
            fresh = [row for row in rows if row.id not in {attempted.id, queued.id}]
            assert len(fresh) == 1 and fresh[0].state == "QUEUED"
            assert queue.get_book_task(fresh[0].id).work == BookWork(identify=True)
    finally:
        engine.dispose()
