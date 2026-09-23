"""An accepted import request owns one immutable task identity."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibraryBook, LibraryBookMetadata, LibrarySourceNode
from app.modules.imports.application.readable_resource.book_work import BookWork
from app.modules.imports.domain.scan_policy import MissingEntryPolicy, ScanScope
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath


def test_new_requests_keep_running_book_and_old_scan_unchanged(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "requests.sqlite3")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 24, tzinfo=UTC)
    try:
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
            db.add(LibraryBookMetadata(
                book_id="book", title="Book", normalized_title="book",
            ))
            db.commit()
            queue = SqlAlchemyLibraryImportTaskQueue(db)

            first = queue.request_book_work(
                book_id="book", work=BookWork(identify=True), requested_at=now,
            )
            db.commit()
            claimed = queue.claim_next_book(started_at=now)
            assert claimed is not None and claimed.id == first.id
            db.commit()
            metadata = db.get(LibraryBookMetadata, "book")
            assert metadata is not None
            revision = metadata.import_revision

            second = queue.request_book_work(
                book_id="book", work=BookWork(scan_scopes=None), requested_at=now,
            )
            scan_one, created_one = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                scan_scopes=(ScanScope("book.epub", False),),
            )
            scan_two, created_two = queue.request_library_scan(
                "library", missing_entry_policy=MissingEntryPolicy.PRESERVE,
                scan_scopes=None,
            )
            db.commit()
            db.expire_all()

            assert second.id != first.id
            assert queue.get_book_task(first.id).state == "RUNNING"
            assert queue.get_book_task(first.id).work.active == BookWork(identify=True)
            assert queue.get_book_task(first.id).work.pending.is_empty
            assert queue.get_book_task(second.id).state == "QUEUED"
            assert queue.get_book_task(second.id).work.pending.scan_scopes is None
            assert db.get(LibraryBookMetadata, "book").import_revision == revision
            assert created_one and created_two and scan_one.id != scan_two.id
            assert db.get(LibraryImportTask, scan_one.id).scan_scopes != db.get(
                LibraryImportTask, scan_two.id
            ).scan_scopes
            assert len(db.scalars(select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.book_id == "book",
            )).all()) == 2
            failed = queue.fail_book_run(
                first.id, execution_version=claimed.execution_version,
                error_summary="PARSE_FAILED", failed_at=now,
            )
            assert failed is not None and failed.state == "FAILED"
            again = queue.continue_book_task(first.id, continued_at=now)
            assert again is not None and again[0].id not in {first.id, second.id}
            db.commit()
            assert db.get(LibraryImportTask, first.id).state == "FAILED"
    finally:
        engine.dispose()
