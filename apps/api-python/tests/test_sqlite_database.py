import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import bootstrap as bootstrap_module
from app.db import runner as runner_module
from app.db.base import Base
from app.db.bootstrap import bootstrap_database
from app.db.runner import _run_alembic, head_revision
from app.db.seed import seed_baseline_data
from app.db.sqlite import create_sqlite_engine
from app.models.settings import ReaderBookPreference
from app.services.backup_service import backup_path, create_backup, restore_backup

EXPECTED_TABLES = {
    "BookIdentityCache",
    "BookConversionTask",
    "DownloadTask",
    "DuplicateCandidate",
    "ExternalMetadataCache",
    "ImportLog",
    "ImportAsset",
    "ImportScanJob",
    "ImportTask",
    "ImportWorkItem",
    "KindleSendTask",
    "LibraryFacet",
    "LibraryFile",
    "LibraryMetadata",
    "LibraryOperation",
    "LibraryReadingProgress",
    "LibraryMediaVersion",
    "LibraryVolumeFacet",
    "UserMediaHistory",
    "MediaVersionMigrationEvent",
    "LibraryReadingUnit",
    "LibraryVolume",
    "LibraryWork",
    "LibraryWorkFacet",
    "MetadataSuggestion",
    "MetadataLookupTask",
    "MetadataWritebackOperation",
    "MetadataWritebackTarget",
    "MetadataOpfQueueState",
    "MetadataProviderExecution",
    "MetadataProviderPipeline",
    "MonitorFolder",
    "OrganizeJob",
    "OrganizePolicy",
    "OrganizeRun",
    "PasswordResetToken",
    "ReaderBookPreference",
    "ReaderBookmark",
    "ReaderPreference",
    "ReaderProgressCursor",
    "Session",
    "Shelf",
    "ShelfCollectionMembership",
    "ShelfWork",
    "Source",
    "SourceSearchRecord",
    "SystemEvent",
    "SystemHealthRun",
    "QueueRuntimeState",
    "QueueControlOperation",
    "SystemSetting",
    "User",
    "UserMonitorFolderAccess",
    "UserPreference",
    "WorkDetailPreference",
}

EXPECTED_BASELINE_DEFAULTS = {
    ("LibraryFacet", "aliases"): "[]",
    ("LibraryOperation", "inverseJson"): "{}",
    ("LibraryOperation", "payloadJson"): "{}",
    ("LibraryOperation", "status"): "COMPLETED",
    ("LibraryWorkFacet", "sortOrder"): "0",
    ("LibraryWork", "facetIndexVersion"): "0",
    ("ReaderBookmark", "percent"): "0",
    ("ReaderProgressCursor", "highWater"): "-1",
    ("SystemEvent", "actorType"): "system",
    ("SystemEvent", "level"): "info",
    ("SystemHealthRun", "status"): "running",
    ("SystemHealthRun", "version"): "1",
}

EXPECTED_RESTORED_INDEXES = {
    "BookIdentityCache": {
        "BookIdentityCache_parserVersion_idx": ("parserVersion",),
    },
    "PasswordResetToken": {
        "PasswordResetToken_expiresAt_idx": ("expiresAt",),
        "PasswordResetToken_userId_createdAt_idx": ("userId", "createdAt"),
    },
    "SystemEvent": {
        "SystemEvent_action_createdAt_idx": ("action", "createdAt"),
        "SystemEvent_actorType_createdAt_idx": ("actorType", "createdAt"),
        "SystemEvent_createdAt_idx": ("createdAt",),
        "SystemEvent_level_createdAt_idx": ("level", "createdAt"),
        "SystemEvent_source_createdAt_idx": ("source", "createdAt"),
        "SystemEvent_targetType_targetId_idx": ("targetType", "targetId"),
    },
    "UserMonitorFolderAccess": {
        "UserMonitorFolderAccess_folder_idx": ("monitorFolderId",),
    },
    "UserPreference": {
        "UserPreference_userId_idx": ("userId",),
    },
}


def _alembic_version(connection) -> str | None:
    exists = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version' LIMIT 1"
    ).first()
    if exists is None:
        return None
    version = connection.exec_driver_sql(
        "SELECT version_num FROM alembic_version LIMIT 1"
    ).scalar()
    return None if version is None else str(version)


def _application_tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def _drop_alembic_version(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS `alembic_version`")


def _alembic_backup_paths(settings: Settings) -> list[Path]:
    migrations_dir = settings.database_path.parent / "migrations"
    if not migrations_dir.is_dir():
        return []
    return sorted(migrations_dir.glob("shuku-before-alembic-*.sqlite3"))


def _default_text(value: object) -> str:
    return str(value).strip().strip("'\"")


def _replace_backup_revision(path: Path, revision: str | None) -> None:
    with zipfile.ZipFile(path) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    metadata = json.loads(entries["metadata.json"].decode())
    if revision is None:
        metadata.pop("databaseRevision", None)
    else:
        metadata["databaseRevision"] = revision
    entries["metadata.json"] = json.dumps(metadata, ensure_ascii=False).encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, content in entries.items():
            target.writestr(name, content)


def _replace_backup_version(path: Path, version: int) -> None:
    with zipfile.ZipFile(path) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    metadata = json.loads(entries["metadata.json"].decode())
    metadata["version"] = version
    entries["metadata.json"] = json.dumps(metadata, ensure_ascii=False).encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, content in entries.items():
            target.writestr(name, content)


def test_empty_storage_bootstraps_complete_sqlite_database(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        bootstrap_database(engine, settings)

        assert settings.database_path.is_file()
        assert _application_tables(engine) == EXPECTED_TABLES
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 10_000
            assert _alembic_version(connection) == head_revision(engine)
            assert connection.execute(text("SELECT COUNT(*) FROM `User`")).scalar() == 0
            settings_rows = dict(
                connection.execute(
                    text("SELECT `key`, `value` FROM `SystemSetting` ORDER BY `key`")
                ).all()
            )
            assert settings_rows == {
                "language": "zh-CN",
                "systemName": "二毛图书",
                "workDetail.tabOrder": '["EBOOK", "COMIC", "AUDIOBOOK", "STRUCTURE"]',
            }
            sources = connection.execute(
                text(
                    "SELECT `providerType`, `enabled` FROM `Source` "
                    "WHERE `kind` = 'metadata' ORDER BY `providerType`"
                )
            ).all()
            assert sources == [("ai", 0), ("bangumi", 1), ("douban", 1)]
            assert (
                connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None
            )

        inspector = inspect(engine)
        for table_name in EXPECTED_TABLES:
            columns = {
                column["name"]: column for column in inspector.get_columns(table_name)
            }
            created_at = columns.get("createdAt")
            if created_at is not None:
                assert created_at["default"] == "unixepoch() * 1000", table_name

        for (
            table_name,
            column_name,
        ), expected_default in EXPECTED_BASELINE_DEFAULTS.items():
            columns = {
                column["name"]: column for column in inspector.get_columns(table_name)
            }
            assert _default_text(columns[column_name]["default"]) == expected_default

        for table_name, expected_indexes in EXPECTED_RESTORED_INDEXES.items():
            indexes = {
                index["name"]: tuple(index["column_names"])
                for index in inspector.get_indexes(table_name)
            }
            assert expected_indexes.items() <= indexes.items()

        for table_name in EXPECTED_TABLES:
            for foreign_key in inspector.get_foreign_keys(table_name):
                assert foreign_key["options"].get("onupdate") == "CASCADE", (
                    table_name,
                    foreign_key,
                )

        for table_name in ("DuplicateCandidate", "MetadataSuggestion"):
            columns = {
                column["name"]: column for column in inspector.get_columns(table_name)
            }
            assert columns["jobId"]["nullable"] is False
        assert ReaderBookPreference.__table__.c.schemaVersion.default.arg == 3
        assert (
            str(ReaderBookPreference.__table__.c.schemaVersion.server_default.arg)
            == "3"
        )
    finally:
        engine.dispose()


def test_alembic_baseline_matches_sqlalchemy_metadata(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_management_query_indexes_upgrade_and_downgrade(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    index_names = {
        "LibraryWork": {
            "LibraryWork_hidden_normalizedTitle_normalizedAuthor_id_idx"
        },
        "ImportTask": {
            "ImportTask_monitorFolderId_createdAt_id_idx",
            "ImportTask_monitorFolderId_status_createdAt_id_idx",
        },
        "SystemEvent": {
            "SystemEvent_createdAt_id_idx",
            "SystemEvent_targetType_createdAt_id_idx",
        },
    }
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0014_dashboard_query_indexes"),
        )
        inspector = inspect(engine)
        for table, expected_names in index_names.items():
            assert expected_names.isdisjoint(
                {index["name"] for index in inspector.get_indexes(table)}
            )

        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0015_management_query_indexes"),
        )
        inspector = inspect(engine)
        for table, expected_names in index_names.items():
            assert expected_names <= {
                index["name"] for index in inspector.get_indexes(table)
            }

        _run_alembic(
            engine,
            lambda config: command.downgrade(config, "0014_dashboard_query_indexes"),
        )
        inspector = inspect(engine)
        for table, expected_names in index_names.items():
            assert expected_names.isdisjoint(
                {index["name"] for index in inspector.get_indexes(table)}
            )
    finally:
        engine.dispose()


def test_seed_is_insert_only_and_safe_across_concurrent_sessions(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE `SystemSetting` SET `value` = '我的书库' WHERE `key` = 'systemName'"
                )
            )
            connection.execute(
                text(
                    "UPDATE `Source` SET `name` = '自定义豆瓣', `enabled` = 0 "
                    "WHERE `providerType` = 'douban'"
                )
            )

        def seed_once() -> None:
            with Session(engine) as db:
                seed_baseline_data(db)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _index: seed_once(), range(8)))

        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT `value` FROM `SystemSetting` WHERE `key` = 'systemName'"
                    )
                ).scalar_one()
                == "我的书库"
            )
            assert connection.execute(
                text(
                    "SELECT `name`, `enabled` FROM `Source` WHERE `providerType` = 'douban'"
                )
            ).one() == ("自定义豆瓣", 0)
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM `SystemSetting`")
                ).scalar_one()
                == 3
            )
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM `Source` WHERE `kind` = 'metadata'")
                ).scalar_one()
                == 3
            )
    finally:
        engine.dispose()


def test_bootstrap_upgrades_0001_database_to_media_version_head(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine, lambda config: command.upgrade(config, "0001_current_schema")
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO `LibraryWork` "
                    "(`id`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`, `workType`, "
                    "`status`, `tags`, `mergeKey`, `updatedAt`) "
                    "VALUES ('legacy-work', '旧作品', '旧作品', '旧作者', '旧作者', 'EPUB', "
                    "'WANT', '[]', 'legacy-identity-key', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `LibraryFacet` "
                    "(`id`, `kind`, `name`, `normalizedName`, `aliases`, `updatedAt`) "
                    "VALUES ('legacy-facet', 'TAG', '旧标签', '旧标签', '[\"旧别名\"]', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `OrganizeJob` "
                    "(`id`, `workId`, `status`, `issueCodes`, `summary`, `updatedAt`) "
                    "VALUES ('legacy-job', 'legacy-work', 'FAILED', '[]', '保持失败', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `MetadataLookupTask` "
                    "(`id`, `workId`, `organizeJobId`, `status`, `providerOrder`, `attempts`, "
                    "`finishedAt`, `updatedAt`) "
                    "VALUES ('legacy-lookup', 'legacy-work', 'legacy-job', 'NO_MATCH', "
                    "'[]', 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.exec_driver_sql(
                "UPDATE alembic_version SET version_num = '0001_current_schema'"
            )
            connection.exec_driver_sql("PRAGMA user_version = 14")

        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            assert _alembic_version(connection) == head_revision(engine)
            assert (
                connection.execute(
                    text(
                        "SELECT `mergeKey` FROM `LibraryWork` WHERE `id` = 'legacy-work'"
                    )
                ).scalar_one()
                == "legacy-identity-key"
            )
            assert connection.execute(
                text(
                    "SELECT `status`, `attempts` FROM `MetadataLookupTask` "
                    "WHERE `id` = 'legacy-lookup'"
                )
            ).one() == ("NO_MATCH", 2)
            assert connection.execute(
                text(
                    "SELECT `status`, `summary` FROM `OrganizeJob` WHERE `id` = 'legacy-job'"
                )
            ).one() == ("FAILED", "保持失败")
            assert (
                connection.execute(
                    text(
                        "SELECT `aliases` FROM `LibraryFacet` WHERE `id` = 'legacy-facet'"
                    )
                ).scalar_one()
                == '["旧别名"]'
            )
            assert (
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM `SystemSetting` WHERE `key` LIKE 'migration.%'"
                    )
                ).scalar_one()
                == 0
            )
        assert _alembic_backup_paths(settings)
    finally:
        engine.dispose()


def test_bootstrap_runs_normalization_after_stamping_v14_boundary(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage-v14"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0003_import_work_queue"),
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO SystemSetting (`key`, `value`, `updatedAt`) "
                    "VALUES ('v14-preserved', 'yes', CURRENT_TIMESTAMP)"
                )
            )
            connection.exec_driver_sql("DROP TABLE alembic_version")
            connection.exec_driver_sql("PRAGMA user_version = 14")

        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            assert _alembic_version(connection) == "0018_library_facet_index_version"
            inspector = inspect(connection)
            assert "LibraryWork_hidden_createdAt_id_idx" in {
                index["name"] for index in inspector.get_indexes("LibraryWork")
            }
            assert "LibraryVolume_mediaVersionId_hidden_monitorFolderId_idx" in {
                index["name"] for index in inspector.get_indexes("LibraryVolume")
            }
            assert "LibraryReadingProgress_userId_updatedAt_volumeId_idx" in {
                index["name"]
                for index in inspector.get_indexes("LibraryReadingProgress")
            }
            assert "UserMediaHistory_userId_updatedAt_mediaVersionId_idx" in {
                index["name"] for index in inspector.get_indexes("UserMediaHistory")
            }
            assert (
                "LibraryWork_hidden_normalizedTitle_normalizedAuthor_id_idx"
                in {
                    index["name"]
                    for index in inspector.get_indexes("LibraryWork")
                }
            )
            assert "ImportTask_monitorFolderId_createdAt_id_idx" in {
                index["name"] for index in inspector.get_indexes("ImportTask")
            }
            assert "ImportTask_monitorFolderId_status_createdAt_id_idx" in {
                index["name"] for index in inspector.get_indexes("ImportTask")
            }
            assert "SystemEvent_createdAt_id_idx" in {
                index["name"] for index in inspector.get_indexes("SystemEvent")
            }
            assert "SystemEvent_targetType_createdAt_id_idx" in {
                index["name"] for index in inspector.get_indexes("SystemEvent")
            }
            assert (
                connection.execute(
                    text(
                        "SELECT `value` FROM SystemSetting "
                        "WHERE `key` = 'v14-preserved'"
                    )
                ).scalar_one()
                == "yes"
            )
        assert _alembic_backup_paths(settings)
    finally:
        engine.dispose()


@pytest.mark.parametrize("user_version", [0, 1, 13])
def test_bootstrap_rejects_pre_v14_or_incomplete_database(
    tmp_path, user_version
) -> None:
    settings = Settings(storage_root=str(tmp_path / f"storage-{user_version}"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE LegacySentinel (value TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO LegacySentinel (value) VALUES ('preserve-me')"
            )
            connection.exec_driver_sql(f"PRAGMA user_version = {user_version}")

        with pytest.raises(RuntimeError, match="pre-v14"):
            bootstrap_database(engine, settings)

        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT value FROM LegacySentinel"
                ).scalar_one()
                == "preserve-me"
            )
            assert _alembic_version(connection) is None
        assert _alembic_backup_paths(settings) == []
    finally:
        engine.dispose()


def test_complete_create_all_database_without_revision_is_rejected(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        Base.metadata.create_all(engine)
        with pytest.raises(RuntimeError, match="未标记版本"):
            bootstrap_database(engine, settings)
        with engine.connect() as connection:
            assert _alembic_version(connection) is None
        assert _alembic_backup_paths(settings) == []
    finally:
        engine.dispose()


def test_backup_includes_current_database_revision_and_restores_matching_backup(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.execute(
                text(
                    "INSERT INTO `SystemSetting` (`key`, `value`, `updatedAt`) "
                    "VALUES ('backup.guard', 'archived', CURRENT_TIMESTAMP)"
                )
            )
            db.commit()
            backup = create_backup(db, settings)
            with zipfile.ZipFile(backup_path(settings, backup.id)) as archive:
                metadata = json.loads(archive.read("metadata.json"))
            assert metadata["version"] == 3
            assert metadata["databaseRevision"] == head_revision(engine)

            db.execute(
                text(
                    "UPDATE `SystemSetting` SET `value` = 'changed' WHERE `key` = 'backup.guard'"
                )
            )
            db.commit()
            restored = restore_backup(db, settings, backup.id)

            assert restored["restored"] is True
            assert (
                db.execute(
                    text(
                        "SELECT `value` FROM `SystemSetting` WHERE `key` = 'backup.guard'"
                    )
                ).scalar_one()
                == "archived"
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", [None, "different-revision"])
def test_restore_rejects_unsupported_revision_before_clearing_tables(
    tmp_path, revision
) -> None:
    settings = Settings(storage_root=str(tmp_path / f"storage-{revision or 'missing'}"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.execute(
                text(
                    "INSERT INTO `SystemSetting` (`key`, `value`, `updatedAt`) "
                    "VALUES ('restore.guard', 'archive-value', CURRENT_TIMESTAMP)"
                )
            )
            db.commit()
            backup = create_backup(db, settings)
            _replace_backup_revision(backup_path(settings, backup.id), revision)
            db.execute(
                text(
                    "UPDATE `SystemSetting` SET `value` = 'must-survive' "
                    "WHERE `key` = 'restore.guard'"
                )
            )
            db.commit()

            with pytest.raises(ValueError, match="BACKUP_REVISION_UNSUPPORTED"):
                restore_backup(db, settings, backup.id)

            assert (
                db.execute(
                    text(
                        "SELECT `value` FROM `SystemSetting` WHERE `key` = 'restore.guard'"
                    )
                ).scalar_one()
                == "must-survive"
            )
    finally:
        engine.dispose()


def test_restore_rejects_v2_backup_before_clearing_tables(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage-v2"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.execute(
                text(
                    "INSERT INTO `SystemSetting` (`key`, `value`, `updatedAt`) "
                    "VALUES ('restore.v2.guard', 'must-survive', CURRENT_TIMESTAMP)"
                )
            )
            db.commit()
            backup = create_backup(db, settings)
            _replace_backup_version(backup_path(settings, backup.id), 2)

            with pytest.raises(ValueError, match="BACKUP_REVISION_UNSUPPORTED"):
                restore_backup(db, settings, backup.id)

            assert (
                db.execute(
                    text(
                        "SELECT `value` FROM `SystemSetting` "
                        "WHERE `key` = 'restore.v2.guard'"
                    )
                ).scalar_one()
                == "must-survive"
            )
    finally:
        engine.dispose()


def test_timestamp_triggers_are_idempotent_and_normalize_raw_timestamps(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        runner_module.apply_schema(engine, settings)
        runner_module.apply_schema(engine, settings)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO `User` (`id`, `email`, `name`, `passwordHash`, `createdAt`, `updatedAt`) "
                    "VALUES ('timestamp-user', 'timestamp@example.test', 'Timestamp', 'hash', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            stored = connection.execute(
                text(
                    "SELECT `createdAt`, `updatedAt` FROM `User` WHERE `id` = 'timestamp-user'"
                )
            ).one()
            assert all(
                str(value).isdigit() and len(str(value)) == 13 for value in stored
            )

        with engine.connect() as connection:
            trigger_names = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND name LIKE 'normalize_SystemSetting_timestamps_%'"
                )
            }
            assert trigger_names == {
                "normalize_SystemSetting_timestamps_insert",
                "normalize_SystemSetting_timestamps_update",
            }
    finally:
        engine.dispose()


def test_apply_schema_retries_transient_database_lock(tmp_path, monkeypatch) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    original_apply = runner_module._apply_schema_once
    attempts = 0

    def apply_with_transient_lock(target_engine, target_settings):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return original_apply(target_engine, target_settings)

    monkeypatch.setattr(
        bootstrap_module, "_apply_schema_once", apply_with_transient_lock
    )
    monkeypatch.setattr(runner_module, "_apply_schema_once", apply_with_transient_lock)
    monkeypatch.setattr(runner_module.time, "sleep", lambda _seconds: None)
    try:
        bootstrap_module.apply_schema(engine, settings)
        assert attempts == 2
        with engine.connect() as connection:
            assert _alembic_version(connection) == head_revision(engine)
    finally:
        engine.dispose()
