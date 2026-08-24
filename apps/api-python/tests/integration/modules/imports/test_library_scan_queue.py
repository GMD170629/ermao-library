from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import Library
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)


def test_running_scan_keeps_exactly_one_queued_follow_up(tmp_path: Path) -> None:
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
            first, inserted = queue.request_library_scan("library")
            assert inserted is True
            duplicate, inserted = queue.request_library_scan("library")
            assert inserted is False
            assert duplicate.id == first.id
            queue.mark_running(first.id, started_at=datetime(2026, 8, 24, tzinfo=UTC))
            follow_up, inserted = queue.request_library_scan("library")
            assert inserted is True
            merged, inserted = queue.request_library_scan("library")
            assert inserted is False
            assert merged.id == follow_up.id
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
            assert counts == {"QUEUED": 1, "RUNNING": 1}
    finally:
        engine.dispose()
