from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibrarySourceNode,
)
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


@pytest.mark.parametrize(
    ("kind", "role", "resource_anchor_node_id"),
    (("IMPORT_RESOURCE", None, "source-000"), ("IMPORT_ASSET", "PAGE", None)),
)
def test_resource_import_completion_uses_the_resource_book_id(
    db: Session,
    kind: str,
    role: str | None,
    resource_anchor_node_id: str | None,
) -> None:
    _add_pending_books(db, 3)
    db.add(
        LibraryReadableResource(
            id="resource-for-book-001",
            library_id="library",
            book_id="book-001",
            source_node_id="source-000",
            adapter_id="epub",
            adapter_version="1",
            format="EPUB",
        )
    )
    db.add(
        LibraryImportTask(
            id="resource-import",
            library_id="library",
            kind=kind,
            resource_id="resource-for-book-001",
            source_node_id="source-000",
            resource_anchor_node_id=resource_anchor_node_id,
            role=role,
        )
    )
    db.commit()

    completion = BookImportCompletion(db)
    task = db.get(LibraryImportTask, "resource-import")
    assert task is not None
    assert db.scalars(completion.affected_books(task)).all() == ["book-001"]
    completion.dirty(task)
    db.commit()

    target = db.get(LibraryBookMetadata, "book-001")
    assert target is not None
    assert target.import_revision == 4
    assert target.metadata_pending
    assert target.metadata_state == "WAITING_IMPORT"
    for book_id in ("book-000", "book-002"):
        metadata = db.get(LibraryBookMetadata, book_id)
        assert metadata is not None
        assert metadata.import_revision == 3
        assert metadata.metadata_pending

    completion.cancel(task)
    db.commit()
    assert target.import_revision == 5
    assert not target.metadata_pending
    for book_id in ("book-000", "book-002"):
        metadata = db.get(LibraryBookMetadata, book_id)
        assert metadata is not None
        assert metadata.import_revision == 3
        assert metadata.metadata_pending
