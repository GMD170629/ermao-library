import hashlib
import importlib
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.orm import Session

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibrarySourceNode
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemySourceNodeRepository,
)

INDEX = "LibrarySourceNode_parent_path_scan_idx"


def node(i, *, parent=None, generation="current", library="test-library"):
    path = f"{parent or 'root'}/{i}"
    return {
        "id": f"{library}-{i}",
        "library_id": library,
        "parent_id": parent,
        "parent_physical_kind": "DIRECTORY" if parent else None,
        "relative_path": path,
        "path_key": "v1:" + hashlib.sha256(path.encode()).hexdigest(),
        "name": str(i),
        "physical_kind": "DIRECTORY",
        "observed_mtime_ns": 1,
        "observed_at": datetime.now(UTC),
        "scan_seen_generation": generation,
    }


@pytest.mark.parametrize("parent", [None, "test-library-parent"])
def test_unseen_children_cursor_and_scope(db_session: Session, parent):
    db = db_session
    if parent:
        db.execute(sa.insert(LibrarySourceNode), [node("parent")])
    db.add(
        Library(id="other", name="other", root_path="/other", organization_mode="FLAT")
    )
    db.flush()
    db.execute(
        sa.insert(LibrarySourceNode),
        [node("foreign", library="other", generation=None)],
    )
    db.execute(
        sa.insert(LibrarySourceNode),
        [
            node(i, parent=parent, generation=None if i % 2 else "old")
            for i in range(251)
        ]
        + [node("seen", parent=parent)],
    )
    db.commit()
    repo = SqlAlchemySourceNodeRepository(db)

    def page(cursor):
        return repo.page_unseen_direct_children(
            library_id="test-library",
            parent_id=parent,
            scan_seen_generation="current",
            after_path_key=cursor,
            limit=200,
        )

    first = page(None)
    second = page(first[-1].path_key)
    assert len(first) == 200
    assert len(second) == 51
    assert len({row.id for row in first + second}) == 251
    assert [row.path_key for row in first + second] == sorted(
        row.path_key for row in first + second
    )
    assert page(second[-1].path_key) == ()


def test_unseen_work_does_not_scale_with_other_directories(db_session: Session):
    db = db_session
    db.execute(sa.insert(LibrarySourceNode), [node("parent"), node("noise")])
    db.execute(
        sa.insert(LibrarySourceNode),
        [node(i, parent="test-library-parent") for i in range(100)],
    )
    db.commit()
    repo = SqlAlchemySourceNodeRepository(db)
    counts = []
    for start, end in [(0, 5000), (5000, 20000)]:
        db.execute(
            sa.insert(LibrarySourceNode),
            [
                node(f"noise-{i}", parent="test-library-noise")
                for i in range(start, end)
            ],
        )
        db.commit()
        raw = db.connection().connection.driver_connection
        steps = [0]

        def progress(steps=steps):
            steps[0] += 100
            return 0

        raw.set_progress_handler(progress, 100)
        try:
            assert (
                repo.page_unseen_direct_children(
                    library_id="test-library",
                    parent_id="test-library-parent",
                    scan_seen_generation="current",
                    after_path_key=None,
                    limit=200,
                )
                == ()
            )
        finally:
            raw.set_progress_handler(None, 0)
        counts.append(steps[0])
        query = repo._children_query("test-library", "test-library-parent").limit(200)
        compiled = query.compile(db.bind, compile_kwargs={"render_postcompile": True})
        plan = (
            db.connection()
            .exec_driver_sql(
                "EXPLAIN QUERY PLAN " + str(compiled),
                tuple(compiled.params[key] for key in compiled.positiontup),
            )
            .all()
        )
        assert any(INDEX in row[3] and "parentId=?" in row[3] for row in plan)
        assert not any("TEMP B-TREE" in row[3] for row in plan)
    assert counts[1] <= counts[0] * 2 + 1000


@pytest.mark.parametrize("interrupted", [False, True])
def test_scan_index_upgrade_and_restart(tmp_path, interrupted):
    engine = create_sqlite_engine(tmp_path / "index.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0044_library_background_deletion")
        with Session(engine) as db:
            db.add(
                Library(
                    id="kept", name="kept", root_path="/kept", organization_mode="FLAT"
                )
            )
            db.flush()
            db.execute(
                sa.insert(LibrarySourceNode), [node("kept-node", library="kept")]
            )
            db.commit()
        if interrupted:
            migration = importlib.import_module(
                "app.db.alembic.versions.0045_source_children_scan_index"
            )
            with (
                engine.begin() as connection,
                Operations.context(MigrationContext.configure(connection)),
            ):
                migration.upgrade()
                migration.upgrade()
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            indexes = sa.inspect(connection).get_indexes("LibrarySourceNode")
            assert next(i for i in indexes if i["name"] == INDEX)["column_names"] == [
                "libraryId",
                "parentId",
                "pathKey",
                "id",
                "scanSeenGeneration",
            ]
            assert (
                connection.scalar(
                    sa.select(sa.func.count()).select_from(LibrarySourceNode)
                )
                == 1
            )
            assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    finally:
        engine.dispose()


def test_scan_index_fresh_install(tmp_path):
    engine = create_sqlite_engine(tmp_path / "fresh.sqlite3")
    try:
        command.upgrade(alembic_config_for_engine(engine), "head")
        assert INDEX in {
            i["name"] for i in sa.inspect(engine).get_indexes("LibrarySourceNode")
        }
    finally:
        engine.dispose()
