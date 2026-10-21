import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.runner import alembic_config_for_engine, apply_schema
from app.db.sqlite import create_sqlite_engine


@pytest.mark.parametrize("revision", ["0041_system_setting_json", "0042_remove_metadata_task_payloads"])
@pytest.mark.parametrize("partial", [False, True])
def test_upgrade_discards_legacy_logs_and_preserves_cache(tmp_path, revision, partial):
    engine = create_sqlite_engine(tmp_path / "legacy.sqlite3")
    try:
        command.upgrade(alembic_config_for_engine(engine), revision)
        with engine.begin() as connection:
            logs = sa.Table("SystemEvent", sa.MetaData(), autoload_with=connection)
            cache = sa.Table("ExternalMetadataCache", sa.MetaData(), autoload_with=connection)
            connection.execute(logs.insert().values(
                id="old-log", source="test", action="failure",
                message="old diagnostic", metadata='{"trace":"' + "x" * 600_000 + '"}',
            ))
            connection.execute(cache.insert().values(
                id="cache", provider="test", queryKey="query", rawJson='{"candidates":[]}',
                expiresAt=1, createdAt=0, updatedAt=0,
            ))
            if partial:
                operations = Operations(MigrationContext.configure(connection))
                operations.drop_table("SystemEvent")
                operations.create_index(
                    "ExternalMetadataCache_expiresAt_id_idx",
                    "ExternalMetadataCache", ["expiresAt", "id"],
                )
        apply_schema(engine)
        apply_schema(engine)
        inspector = sa.inspect(engine)
        assert not inspector.has_table("SystemEvent")
        index = next(i for i in inspector.get_indexes("ExternalMetadataCache")
                     if i["name"] == "ExternalMetadataCache_expiresAt_id_idx")
        assert index["column_names"] == ["expiresAt", "id"]
        with engine.connect() as connection:
            assert connection.scalar(sa.select(cache.c.rawJson)) == '{"candidates":[]}'
            assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    finally:
        engine.dispose()


def test_fresh_schema_does_not_contain_legacy_event_table(tmp_path):
    engine = create_sqlite_engine(tmp_path / "fresh.sqlite3")
    try:
        apply_schema(engine)
        assert not sa.inspect(engine).has_table("SystemEvent")
    finally:
        engine.dispose()


def test_backup_import_ignores_removed_payloads_and_legacy_logs():
    from app.modules.backup.infrastructure.persistence import prepare_table_records

    assert prepare_table_records(
        "MetadataLookupTask",
        [{"id": "task", "status": "PENDING", "candidateRawJson": '{"old":"data"}'}],
    ) == ({"id": "task", "status": "PENDING"},)
    assert prepare_table_records("SystemEvent", [{"id": "old-log"}]) == ()
