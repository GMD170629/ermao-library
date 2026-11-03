import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine


@pytest.mark.parametrize("partial", [False, True])
def test_import_status_page_index_restart(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "status.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0049_book_list_identity_indexes")
        if partial:
            with engine.begin() as c:
                Operations(MigrationContext.configure(c)).create_index(
                    "LibraryBook_library_imported_page_idx",
                    "LibraryBook",
                    ["libraryId", "visibilityState", "createdAt", "id"],
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert next(
            i
            for i in sa.inspect(engine).get_indexes("LibraryBook")
            if i["name"] == "LibraryBook_library_imported_page_idx"
        )["column_names"] == ["libraryId", "visibilityState", "createdAt", "id"]
    finally:
        engine.dispose()
