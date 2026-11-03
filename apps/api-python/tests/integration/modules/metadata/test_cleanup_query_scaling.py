import hashlib
import importlib
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibrarySourceNode
from app.modules.metadata.infrastructure.writeback_queue import (
    load_writeback_cleanup_projection,
)


def test_cleanup_page_work_stays_bounded_as_library_grows(db_session):
    db = db_session
    now = datetime.now(UTC)
    steps_per_page = []
    statements = []
    for start, end in [(0, 5000), (5000, 30000)]:
        for offset in range(start, end, 1000):
            db.execute(
                sa.insert(LibrarySourceNode),
                [
                    {
                        "id": f"node-{i:06d}",
                        "library_id": "test-library",
                        "name": f"{i}.txt",
                        "relative_path": f"folder/{i}.txt",
                        "path_key": "v1:" + hashlib.sha256(str(i).encode()).hexdigest(),
                        "physical_kind": "REGULAR_FILE",
                            "observed_size_bytes": 1,
                        "observed_mtime_ns": 1,
                        "observed_at": now,
                    }
                    for i in range(offset, offset + 1000)
                ],
            )
        db.commit()
        raw = db.connection().connection.driver_connection
        steps = [0]

        def progress(steps=steps):
            steps[0] += 100
            return 0

        def before(_conn, _cursor, sql, parameters, _context, _many):
            statements.append((sql, parameters))

        sa.event.listen(db.get_bind(), "before_cursor_execute", before)
        raw.set_progress_handler(progress, 100)
        try:
            page = load_writeback_cleanup_projection(db)
        finally:
            raw.set_progress_handler(None, 0)
            sa.event.remove(db.get_bind(), "before_cursor_execute", before)
        assert len(page.sources) == 512
        assert page.next_cursor == "node-000511"
        steps_per_page.append(steps[0])
        sql, bindings = statements[-1]
        plan = (
            db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + sql, bindings).all()
        )
        assert any(
            "COVERING INDEX LibrarySourceNode_cleanup_page_idx" in row[3]
            for row in plan
        )
        assert steps[0] < 30_000
    assert steps_per_page[1] <= steps_per_page[0] * 2 + 1000


def test_cleanup_filters_deleting_libraries_before_page_limit(db_session):
    db = db_session
    db.add(
        Library(
            id="deleting",
            name="deleting",
            root_path="/deleting",
            organization_mode="FLAT",
            deletion_requested_at=datetime.now(UTC),
        )
    )
    db.flush()
    for i in range(12):
        db.add(
            LibrarySourceNode(
                id=f"node-{i:02d}",
                library_id="deleting" if i % 2 else "test-library",
                name=str(i),
                relative_path=str(i),
                path_key="v1:" + hashlib.sha256(str(i).encode()).hexdigest(),
                physical_kind="REGULAR_FILE",
                observed_size_bytes=1,
                observed_mtime_ns=1,
                observed_at=datetime.now(UTC),
            )
        )
    db.commit()
    first = load_writeback_cleanup_projection(db, limit=4)
    assert [p[0] for p in first.sources] == ["0", "2", "4", "6"]
    assert first.next_cursor == "node-06"
    second = load_writeback_cleanup_projection(db, limit=4, after_id=first.next_cursor)
    assert [p[0] for p in second.sources] == ["8", "10"]
    assert second.next_cursor is None


@pytest.mark.parametrize("partial", [False, True])
def test_cleanup_cover_index_migration_is_restartable(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "cleanup.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0046_import_task_page_indexes")
        migration = importlib.import_module(
            "app.db.alembic.versions.0047_source_cleanup_page_index"
        )
        if partial:
            with engine.begin() as c, Operations.context(MigrationContext.configure(c)):
                migration.upgrade()
                migration.upgrade()
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert next(
            i
            for i in sa.inspect(engine).get_indexes("LibrarySourceNode")
            if i["name"] == migration.INDEX
        )["column_names"] == ["id", "libraryId", "relativePath"]
    finally:
        engine.dispose()
