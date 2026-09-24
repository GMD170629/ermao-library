"""Historical incomplete ranges remain visible without gating new imports."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibraryBook, LibrarySourceNode
from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    encode_book_work,
)
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath


@pytest.mark.parametrize("partial_schema", [False, True])
def test_upgrade_keeps_directory_book_unknown_until_gap_reconciled(
    tmp_path: Path, partial_schema: bool,
) -> None:
    engine = create_sqlite_engine(tmp_path / "upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    try:
        command.upgrade(config, "0032_source_node_scan_seen_generation")
        now = datetime(2026, 9, 23, tzinfo=UTC)
        with Session(engine) as db:
            db.add(
                Library(
                    id="library",
                    name="Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                )
            )
            db.add(
                LibrarySourceNode(
                    id="node",
                    library_id="library",
                    relative_path="missing/book",
                    path_key=SourceNodeRelativePath("missing/book").path_key,
                    name="book",
                    physical_kind="DIRECTORY",
                    observed_size_bytes=None,
                    observed_mtime_ns=0,
                    observed_at=now,
                )
            )
            db.flush()
            db.add(LibraryBook(id="book", library_id="library", source_node_id="node"))
            db.commit()
        old_task = sa.table(
            "LibraryImportTask",
            sa.column("id", sa.String),
            sa.column("kind", sa.String),
            sa.column("libraryId", sa.String),
            sa.column("sourceNodeId", sa.String),
            sa.column("bookId", sa.String),
            sa.column("state", sa.String),
            sa.column("phase", sa.String),
            sa.column("bookWork", sa.Text),
            sa.column("requestVersion", sa.Integer),
            sa.column("nextAttemptAt", sa.BigInteger),
        )
        gap = sa.table(
            "LibraryImportScanGap",
            sa.column("libraryId", sa.String),
            sa.column("scopes", sa.Text),
        )
        with engine.begin() as connection:
            connection.execute(
                sa.insert(gap).values(
                    libraryId="library",
                    scopes='[{"relativePath":"missing","recursive":true}]',
                )
            )
            connection.execute(
                sa.insert(old_task).values(
                    id="task",
                    kind="IMPORT_BOOK",
                    libraryId="library",
                    sourceNodeId="node",
                    bookId="book",
                    state="QUEUED",
                    phase="IDENTIFY",
                    bookWork=encode_book_work(BookWork(identify=True)),
                    requestVersion=1,
                    nextAttemptAt=int(now.timestamp() * 1000),
                )
            )
        if partial_schema:
            with engine.begin() as connection:
                operations = Operations(MigrationContext.configure(connection))
                operations.add_column(
                    "LibraryImportTask",
                    sa.Column("scanGateBlocked", sa.Boolean(), nullable=True),
                )
                operations.create_index(
                    "LibraryImportTask_book_gate_pending_idx",
                    "LibraryImportTask",
                    ["id"],
                    sqlite_where=sa.and_(
                        sa.column("kind") == "IMPORT_BOOK",
                        sa.column("state") == "QUEUED",
                        sa.column("scanGateBlocked").is_(None),
                    ),
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with Session(engine) as db:
            queue = SqlAlchemyLibraryImportTaskQueue(db)
            task = db.get(LibraryImportTask, "task")
            assert task is not None
            assert queue.has_incomplete_ranges("library")
            assert queue.book_requires_scan("book")
            selected = queue.claim_next_book(started_at=now)
            assert selected is not None and selected.id == "task"
            assert queue.has_incomplete_ranges("library")
    finally:
        engine.dispose()
