import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine


@pytest.mark.parametrize("partial", [False, True])
def test_compact_task_totals_index_restart(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "totals.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0047_source_cleanup_page_index")
        if partial:
            with engine.begin() as c:
                Operations(MigrationContext.configure(c)).create_index(
                    "LibraryImportTask_library_state_totals_idx",
                    "LibraryImportTask",
                    ["libraryId", "state"],
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert next(
            i
            for i in sa.inspect(engine).get_indexes("LibraryImportTask")
            if i["name"] == "LibraryImportTask_library_state_totals_idx"
        )["column_names"] == ["libraryId", "state"]
    finally:
        engine.dispose()
