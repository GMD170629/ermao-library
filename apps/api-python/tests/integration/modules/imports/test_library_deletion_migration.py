import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine


@pytest.mark.parametrize("interrupted", [False, True])
def test_library_removal_migration_is_restartable(tmp_path, interrupted):
    engine = create_sqlite_engine(tmp_path / "removal.sqlite3")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0043_remove_legacy_system_events")
        with engine.begin() as connection:
            library = sa.Table("Library", sa.MetaData(), autoload_with=connection)
            connection.execute(library.insert().values(
                id="kept", name="kept", rootPath="/kept", organizationMode="FLAT",
                createdAt=1, updatedAt=1,
            ))
            if interrupted:
                Operations(MigrationContext.configure(connection)).add_column(
                    "Library", sa.Column("deletionRequestedAt", sa.BigInteger(), nullable=True),
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            library = sa.Table("Library", sa.MetaData(), autoload_with=connection)
            row = connection.execute(sa.select(library)).mappings().one()
            assert row["id"] == "kept"
            assert row["deletionRequestedAt"] is None
            assert "deletionPhase" not in row
            assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    finally:
        engine.dispose()
