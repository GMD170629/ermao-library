import importlib

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine


@pytest.mark.parametrize("partial", [False, True])
def test_task_page_indexes_upgrade_restart_and_preserve_rows(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "task-indexes.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0045_source_children_scan_index")
        migration = importlib.import_module(
            "app.db.alembic.versions.0046_import_task_page_indexes"
        )
        with engine.begin() as c:
            library = sa.Table("Library", sa.MetaData(), autoload_with=c)
            task = sa.Table("LibraryImportTask", sa.MetaData(), autoload_with=c)
            c.execute(
                library.insert().values(
                    id="kept",
                    name="kept",
                    rootPath="/kept",
                    organizationMode="FLAT",
                    createdAt=1,
                    updatedAt=1,
                )
            )
            c.execute(
                task.insert().values(
                    id="task",
                    libraryId="kept",
                    kind="SCAN_LIBRARY",
                    state="FAILED",
                    createdAt=1,
                )
            )
            if partial:
                name, columns = next(iter(migration.INDEXES.items()))
                Operations(MigrationContext.configure(c)).create_index(
                    name, "LibraryImportTask", columns
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as c:
            indexes = {
                i["name"]: i["column_names"]
                for i in sa.inspect(c).get_indexes("LibraryImportTask")
            }
            assert all(
                indexes[name] == columns for name, columns in migration.INDEXES.items()
            )
            assert (
                c.scalar(sa.select(task.c.state).where(task.c.id == "task")) == "FAILED"
            )
            assert not c.exec_driver_sql("PRAGMA foreign_key_check").all()
    finally:
        engine.dispose()
