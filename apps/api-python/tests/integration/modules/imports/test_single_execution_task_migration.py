"""Upgrade permits new requests while retaining historical import task rows."""

from __future__ import annotations

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
