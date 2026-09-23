"""Book import task constraints preserve legacy work and enforce the new shape."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibraryBook, LibrarySourceNode
from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    BookWorkState,
    encode_book_work,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath

_PREVIOUS_REVISION = "0029_file_deletions"


def _engine(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_sqlite_engine(settings.database_path)


def test_book_task_shape_migration_preserves_legacy_and_enforces_book_shape(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    config = alembic_config_for_engine(engine)
    command.upgrade(config, _PREVIOUS_REVISION)

    with Session(engine) as db:
        library = Library(
            id="library",
            name="library",
            root_path=str(tmp_path / "library"),
            organization_mode="FLAT",
            min_file_size_bytes=0,
        )
        db.add(library)
        db.commit()

    old_task = sa.table(
        "LibraryImportTask",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("libraryId", sa.String),
        sa.column("state", sa.String),
        sa.column("createdAt", sa.BigInteger),
        sa.column("errorSummary", sa.Text),
    )
    created_at = datetime(2026, 9, 20, tzinfo=UTC)
    created_at_ms = int(created_at.timestamp() * 1000)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(old_task).values(
                id="legacy-task",
                kind="SCAN_LIBRARY",
                libraryId="library",
                state="FAILED",
                createdAt=created_at_ms,
                errorSummary="legacy failure",
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        migrated = connection.execute(
            sa.select(
                LibraryImportTask.__table__.c.kind,
                LibraryImportTask.__table__.c.state,
                LibraryImportTask.__table__.c["createdAt"],
                LibraryImportTask.__table__.c["errorSummary"],
                LibraryImportTask.__table__.c["bookId"],
                LibraryImportTask.__table__.c.phase,
            ).where(LibraryImportTask.__table__.c.id == "legacy-task")
        ).one()
    assert migrated == (
        "SCAN_LIBRARY",
        "FAILED",
        created_at,
        "legacy failure",
        None,
        None,
    )

    source_path = SourceNodeRelativePath("book.epub")
    with Session(engine) as db:
        db.add(
            LibrarySourceNode(
                id="source-node",
                library_id="library",
                relative_path="book.epub",
                path_key=source_path.path_key,
                name="book.epub",
                physical_kind="REGULAR_FILE",
                observed_size_bytes=10,
                observed_mtime_ns=0,
                observed_at=datetime(2026, 9, 20, tzinfo=UTC),
            )
        )
        db.flush()
        db.add(LibraryBook(id="book", library_id="library", source_node_id="source-node"))
        db.commit()

    task_table = LibraryImportTask.__table__
    valid_task = {
        "id": "book-task",
        "kind": "IMPORT_BOOK",
        "libraryId": "library",
        "sourceNodeId": "source-node",
        "bookId": "book",
        "bookWork": encode_book_work(BookWorkState(pending=BookWork(identify=True))),
        "phase": "SCAN",
        "state": "QUEUED",
        "createdAt": created_at,
    }
    with engine.begin() as connection:
        connection.execute(sa.insert(task_table).values(valid_task))

    invalid_shapes = (
        {**valid_task, "id": "book-task-no-node", "sourceNodeId": None},
        {**valid_task, "id": "book-task-no-work", "bookWork": None},
        {**valid_task, "id": "book-task-no-phase", "phase": None},
    )
    for values in invalid_shapes:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(sa.insert(task_table).values(values))

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.insert(task_table).values(
                {**valid_task, "id": "duplicate-book-task"}
            )
        )
