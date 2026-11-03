import importlib

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine


@pytest.mark.parametrize("partial", ["not_started", "created", "complete"])
def test_directory_member_cover_migration_restarts_and_replaces_prefix_index(tmp_path, partial):
    engine = create_sqlite_engine(tmp_path / "members.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0051_book_search_cover_index")
        migration = importlib.import_module("app.db.alembic.versions.0052_directory_member_cover_index")
        if partial != "not_started":
            with engine.begin() as c, Operations.context(MigrationContext.configure(c)):
                if partial == "created":
                    Operations(MigrationContext.configure(c)).create_index(
                        migration.INDEX, "LibrarySourceNode", ["libraryId", "relativePath", "id", "physicalKind"]
                    )
                else:
                    migration.upgrade()
                    migration.upgrade()
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as c:
            indexes = {i["name"]: i for i in sa.inspect(c).get_indexes("LibrarySourceNode")}
        assert indexes[migration.INDEX]["column_names"] == ["libraryId", "relativePath", "id", "physicalKind"]
        assert migration.OLD_INDEX not in indexes
        command.downgrade(config, "0051_book_search_cover_index")
        with engine.connect() as c:
            assert migration.OLD_INDEX in {i["name"] for i in sa.inspect(c).get_indexes("LibrarySourceNode")}
        command.upgrade(config, "head")
    finally:
        engine.dispose()
