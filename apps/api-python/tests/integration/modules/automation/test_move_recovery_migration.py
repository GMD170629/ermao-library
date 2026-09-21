import sqlalchemy as sa
from alembic import command

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine


def test_recovery_quota_migration_backfills_frozen_plan_and_roundtrips(tmp_path):
    engine = create_sqlite_engine(tmp_path / "migration.sqlite")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0023_file_move_operations")
        metadata = sa.MetaData()
        plan = sa.Table("LibraryFileMovePlan", metadata, autoload_with=engine)
        operation = sa.Table("LibraryFileMoveOperation", metadata, autoload_with=engine)
        target = sa.Table("LibraryFileMoveTarget", metadata, autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                plan.insert().values(
                    id="plan",
                    grantId="grant",
                    userId="user",
                    expiresAt=1000,
                    payload={
                        "moves": [
                            {
                                "inventory": {
                                    "byte_count": 42,
                                    "entries": [{"identity": {"device": 1}}],
                                },
                                "destination_inspection": {"device": 2},
                            }
                        ]
                    },
                )
            )
            connection.execute(
                operation.insert().values(
                    id="operation",
                    planId="plan",
                    grantId="grant",
                    userId="user",
                    requestId="request",
                    status="QUEUED",
                    cancelRequested=False,
                    createdAt=0,
                    updatedAt=0,
                )
            )
            connection.execute(
                target.insert().values(
                    operationId="operation",
                    ordinal=0,
                    sourceLibraryId="source",
                    destinationLibraryId="target",
                    stage="QUEUED",
                    recovery={},
                )
            )
        for _ in range(2):
            command.upgrade(config, "0024_file_move_recovery_limits")
            current = sa.Table(
                "LibraryFileMoveTarget", sa.MetaData(), autoload_with=engine
            )
            with engine.connect() as connection:
                row = connection.execute(
                    sa.select(current.c.byteCount, current.c.copyRequired)
                ).one()
                assert row.byteCount == 42 and row.copyRequired
            command.downgrade(config, "0023_file_move_operations")
            assert "byteCount" not in {
                column["name"]
                for column in sa.inspect(engine).get_columns("LibraryFileMoveTarget")
            }
    finally:
        engine.dispose()
