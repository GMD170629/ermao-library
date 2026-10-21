import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.orm import Session

from app.db.metadata_task_payload_cleanup import (
    backup_database,
    clear_metadata_task_payloads,
)
from app.db.runner import alembic_config_for_engine, apply_schema
from app.db.sqlite import create_sqlite_engine
from tests.test_library_delete_graph import graph_snapshot, seed_delete_graph


def indexes(engine, names):
    return {name: [
        {**index, "dialect_options": {
            key: str(value) for key, value in index["dialect_options"].items()
        }} for index in sa.inspect(engine).get_indexes(name)
    ] for name in names}


@pytest.mark.parametrize("mode", ["direct", "partial", "cleanup"])
def test_payload_upgrade_preserves_graph_and_recovers_between_drops(tmp_path, mode):
    engine = create_sqlite_engine(tmp_path / "payloads.sqlite3")
    config = alembic_config_for_engine(engine)
    try:
        command.upgrade(config, "0041_system_setting_json")
        with Session(engine) as db:
            seed_delete_graph(db, "migration")
            before = graph_snapshot(db)
        with engine.begin() as connection:
            for name, field in (("MetadataLookupTask", "candidateRawJson"),
                                ("MetadataProviderExecution", "rawResultJson")):
                table = sa.Table(name, sa.MetaData(), autoload_with=connection)
                connection.execute(table.update().values({field: '{"data":"' + "x" * 2_000_000 + '"}'}))
        old_indexes = indexes(engine, before)
        if mode == "cleanup":
            backup = tmp_path / "before-cleanup.sqlite3"
            backup_database(engine, backup)
            with pytest.raises(FileExistsError):
                backup_database(engine, backup)
            batches = clear_metadata_task_payloads(engine, batch_size=1)
            assert next(batches) == ("MetadataLookupTask", 1)
            batches.close()  # Process stopped after the first committed batch.
            assert sum(count for _, count in clear_metadata_task_payloads(
                engine, batch_size=1)) == 2
            assert list(clear_metadata_task_payloads(engine)) == []
            backup_engine = create_sqlite_engine(backup)
            try:
                lookup = sa.Table("MetadataLookupTask", sa.MetaData(), autoload_with=backup_engine)
                with backup_engine.connect() as connection:
                    assert connection.scalar(sa.select(
                        sa.func.length(lookup.c.candidateRawJson))) > 2_000_000
            finally:
                backup_engine.dispose()
        if mode == "partial":
            # Reproduce durable first DDL with the old revision still recorded.
            with engine.begin() as connection:
                Operations(MigrationContext.configure(connection)).drop_column(
                    "MetadataLookupTask", "candidateRawJson")
            with engine.connect() as connection:
                assert MigrationContext.configure(connection).get_current_revision() == "0041_system_setting_json"
        command.upgrade(config, "0042_remove_metadata_task_payloads")
        command.upgrade(config, "0042_remove_metadata_task_payloads")
        with Session(engine) as db:
            after = graph_snapshot(db)
            for name, rows in before.items():
                # Original snapshots precede the archived payload updates.
                assert after[name] == rows
            assert not db.connection().exec_driver_sql("PRAGMA foreign_key_check").all()
        for name, field in (("MetadataLookupTask", "candidateRawJson"),
                            ("MetadataProviderExecution", "rawResultJson")):
            assert field not in {item["name"] for item in sa.inspect(engine).get_columns(name)}
        assert indexes(engine, before) == old_indexes
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "0042_remove_metadata_task_payloads"
    finally:
        engine.dispose()


def test_fresh_schema_has_no_archived_task_payloads(tmp_path):
    engine = create_sqlite_engine(tmp_path / "fresh.sqlite3")
    try:
        apply_schema(engine)
        for name, field in (("MetadataLookupTask", "candidateRawJson"),
                            ("MetadataProviderExecution", "rawResultJson")):
            assert field not in {item["name"] for item in sa.inspect(engine).get_columns(name)}
    finally:
        engine.dispose()
