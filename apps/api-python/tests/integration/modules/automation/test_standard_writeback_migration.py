import sqlalchemy as sa
from alembic import command

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine


def test_standard_writeback_schema_upgrade_downgrade_reentry(tmp_path):
    engine = create_sqlite_engine(tmp_path / "migration.sqlite")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0024_file_move_recovery_limits")
        for _ in range(2):
            command.upgrade(config, "0025_standard_writeback_plans")
            schema = sa.inspect(engine)
            assert "MetadataStandardWriteTarget" in schema.get_table_names()
            assert {
                column["name"]
                for column in schema.get_columns("MetadataStandardWriteTarget")
            } >= {"operationId", "queueTargetId", "reservedBytes", "recoveryReleased"}
            command.downgrade(config, "0024_file_move_recovery_limits")
            assert (
                "MetadataStandardWritePlan" not in sa.inspect(engine).get_table_names()
            )
    finally:
        engine.dispose()
