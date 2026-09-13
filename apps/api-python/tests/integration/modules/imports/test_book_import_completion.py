from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibraryBook, LibraryBookMetadata, LibrarySourceNode
from app.modules.imports.infrastructure.readable_resource.book_completion import (
    BookImportCompletion,
)
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "completion.sqlite3")
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


def _add_pending_books(db: Session, count: int = 1) -> None:
    for index in range(count):
        filename = f"{index:03d}.epub"
        db.add(
            LibrarySourceNode(
                id=f"source-{index:03d}",
                library_id="library",
                relative_path=filename,
                path_key=SourceNodeRelativePath(filename).path_key,
                name=filename,
                physical_kind="REGULAR_FILE",
                observed_size_bytes=1,
                observed_mtime_ns=1,
                observed_at=datetime(2026, 9, 13, tzinfo=UTC),
            )
        )
    db.flush()
    db.add_all(
        LibraryBook(
            id=f"book-{index:03d}",
            library_id="library",
            source_node_id=f"source-{index:03d}",
        )
        for index in range(count)
    )
    db.flush()
    db.add_all(
        LibraryBookMetadata(
            book_id=f"book-{index:03d}",
            title="Book",
            normalized_title="book",
            metadata_pending=True,
            import_revision=3,
        )
        for index in range(count)
    )
    db.commit()


def test_identification_preparation_is_read_only_and_batches_are_bounded(
    db: Session,
) -> None:
    _add_pending_books(db, 51)
    completion = BookImportCompletion(db)
    prepared = completion.prepare_ready()
    assert len(prepared) == 50
    assert [item.book_id for item in prepared] == [
        f"book-{index:03d}" for index in range(50)
    ]
    assert not db.new and not db.dirty
    assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 0
    db.rollback()

    with db.begin():
        assert completion.persist_ready(prepared) == 50
    with db.begin():
        assert completion.persist_ready(prepared) == 0

    remaining = completion.prepare_ready()
    assert [item.book_id for item in remaining] == ["book-050"]
    db.rollback()
    with db.begin():
        assert completion.persist_ready(remaining) == 1
    assert completion.prepare_ready() == ()
    assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 51
    assert set(db.scalars(select(LibraryBookMetadata.metadata_state))) == {"QUEUED"}


@pytest.mark.parametrize(
    "change", ("cancel", "revision", "scan", "identification", "delete")
)
def test_prepared_identification_rechecks_changes_before_persisting(
    db: Session, change: str
) -> None:
    _add_pending_books(db)
    completion = BookImportCompletion(db)
    prepared = completion.prepare_ready()
    assert len(prepared) == 1
    db.rollback()

    # Another request may commit after candidate preparation releases its read.
    with Session(db.get_bind()) as other:
        if change == "cancel":
            other.execute(update(LibraryBookMetadata).values(metadata_pending=False))
        elif change == "revision":
            other.execute(update(LibraryBookMetadata).values(import_revision=4))
        elif change == "scan":
            other.add(
                LibraryImportTask(
                    id="new-scan", library_id="library", kind="SCAN_LIBRARY"
                )
            )
        elif change == "identification":
            other.add(
                LibraryImportTask(
                    id="other-identification",
                    library_id="library",
                    kind="IDENTIFY_BOOK",
                    source_node_id="source-000",
                    book_metadata_revision=3,
                )
            )
        else:
            other.execute(delete(LibraryBook).where(LibraryBook.id == "book-000"))
        other.commit()

    with db.begin():
        assert completion.persist_ready(prepared) == 0
    assert db.get(LibraryImportTask, prepared[0].task_id) is None
    metadata = db.get(LibraryBookMetadata, "book-000")
    assert metadata is None or metadata.metadata_state == "WAITING_IMPORT"


@pytest.mark.parametrize("state", ("SUCCEEDED", "FAILED"))
def test_terminal_scan_commit_survives_later_identification_batch_failure(
    db: Session, state: str
) -> None:
    _add_pending_books(db)
    db.add(
        LibraryImportTask(
            id="scan", library_id="library", kind="SCAN_LIBRARY", state="RUNNING"
        )
    )
    db.commit()
    queue = SqlAlchemyLibraryImportTaskQueue(db)
    finished_at = datetime(2026, 9, 13, tzinfo=UTC)
    with db.begin():
        if state == "SUCCEEDED":
            queue.mark_succeeded("scan", finished_at=finished_at)
        else:
            queue.mark_failed(
                "scan", error_summary="SCAN_FAILED", finished_at=finished_at
            )
    assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 1
    db.rollback()

    completion = BookImportCompletion(db)
    prepared = completion.prepare_ready()
    assert len(prepared) == 1
    db.rollback()
    with pytest.raises(RuntimeError, match="batch interrupted"), db.begin():
        assert completion.persist_ready(prepared) == 1
        raise RuntimeError("batch interrupted before commit")

    assert (
        db.scalar(select(LibraryImportTask.state).where(LibraryImportTask.id == "scan"))
        == state
    )
    metadata = db.get(LibraryBookMetadata, "book-000")
    assert metadata is not None and metadata.metadata_pending
    assert metadata.metadata_state == "WAITING_IMPORT"
    db.rollback()

    # A later worker can reconstruct the pending batch without rerunning a scan.
    recovered = BookImportCompletion(db).prepare_ready()
    assert len(recovered) == 1
    db.rollback()
    with db.begin():
        assert completion.persist_ready(recovered) == 1
    assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 2


@pytest.mark.parametrize("task_revision", (2, 3))
def test_failed_identification_updates_only_its_matching_metadata_revision(
    db: Session, task_revision: int
) -> None:
    _add_pending_books(db, 2)
    db.add(
        LibraryImportTask(
            id="identification",
            library_id="library",
            kind="IDENTIFY_BOOK",
            source_node_id="source-000",
            book_metadata_revision=task_revision,
            state="RUNNING",
        )
    )
    db.commit()
    with db.begin():
        SqlAlchemyLibraryImportTaskQueue(db).mark_failed(
            "identification",
            error_summary="IDENTIFICATION_FAILED",
            finished_at=datetime(2026, 9, 13, tzinfo=UTC),
        )
    metadata = db.get(LibraryBookMetadata, "book-000")
    assert metadata is not None
    assert metadata.metadata_state == (
        "FAILED" if task_revision == 3 else "WAITING_IMPORT"
    )
    assert metadata.metadata_pending is (task_revision != 3)
    other = db.get(LibraryBookMetadata, "book-001")
    assert other is not None and other.metadata_state == "WAITING_IMPORT"
    assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 1
