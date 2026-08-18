import json
import re
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db import bootstrap as bootstrap_module
from app.db import runner as runner_module
from app.db.base import Base
from app.db.bootstrap import bootstrap_database
from app.db.runner import _run_alembic, head_revision
from app.db.seed import seed_baseline_data
from app.db.sqlite import create_sqlite_engine
from app.models.import_pipeline import ImportTask
from app.models.settings import ReaderBookPreference, SystemSetting
from app.modules.backup.application.restore import PreparedRestorePlan
from app.modules.backup.infrastructure.persistence import (
    SqlAlchemyBackupRestoreWriter,
)
from app.modules.mobile.public import SERVER_IDENTITY_SETTING_KEY
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
    "MetadataWritebackPreparation",
    "MetadataWritebackTarget",
    "MetadataOpfQueueState",
    "MetadataProviderExecution",
    "MetadataProviderPipeline",
    "MonitorFolder",
    "OrganizeJob",
    "OrganizePolicy",
    "OrganizeRun",
    "PasswordResetToken",
    "PublicationNavigationCache",
    "ReaderBookPreference",
    "ReaderBookmark",
    "ReaderPreference",
    "ReaderProgressCursor",
    "ReaderProgressMutation",
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
    ("LibraryFile", "pageIndexVersion"): "0",
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
    "LibraryFile": {
        "LibraryFile_kind_pageIndexVersion_id_idx": (
            "kind",
            "pageIndexVersion",
            "id",
        ),
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


def _replace_backup_database_export(
    path: Path, database_export: dict[str, object]
) -> None:
    with zipfile.ZipFile(path) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    entries["database-export.json"] = json.dumps(
        database_export, ensure_ascii=False
    ).encode()
    temporary = path.with_name(f".{path.name}.test.part")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for name, content in entries.items():
                target.writestr(name, content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
            server_identity = settings_rows.pop("mobile.serverIdentity")
            assert re.fullmatch(r"server_[0-9a-f]{32}", server_identity)
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
                connection.execute(
                    text("SELECT COUNT(*) FROM `MetadataProviderPipeline`")
                ).scalar_one()
                == 7
            )
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

        library_file_columns = {
            column["name"]: column for column in inspector.get_columns("LibraryFile")
        }
        assert "volumeId" in library_file_columns
        assert "editionId" not in library_file_columns
        assert library_file_columns["pageIndexVersion"]["nullable"] is False
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

        with Session(engine) as db:
            server_identities = tuple(
                db.scalars(
                    select(SystemSetting.value).where(
                        SystemSetting.key == SERVER_IDENTITY_SETTING_KEY
                    )
                )
            )
        assert len(server_identities) == 1
        assert re.fullmatch(r"server_[0-9a-f]{32}", server_identities[0])

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
                == 4
            )
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM `Source` WHERE `kind` = 'metadata'")
                ).scalar_one()
                == 3
            )
    finally:
        engine.dispose()


def test_apply_schema_accepts_current_head_without_changing_revision(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        expected = head_revision(engine)
        with engine.connect() as connection:
            assert _alembic_version(connection) == expected

        runner_module.apply_schema(engine, settings)

        with engine.connect() as connection:
            assert _alembic_version(connection) == expected
        assert _application_tables(engine) == EXPECTED_TABLES
        assert not (settings.database_path.parent / "migrations").exists()
    finally:
        engine.dispose()


def test_apply_schema_rejects_old_alembic_revision(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    old_revision = "0021_reader_v4_exact_progress"
    try:
        _run_alembic(engine, lambda config: command.upgrade(config, old_revision))
        with pytest.raises(
            RuntimeError,
            match=(
                r"Database revision '0021_reader_v4_exact_progress' is not supported"
                r".*Expected '.*'.*fresh installation"
            ),
        ):
            runner_module.apply_schema(engine, settings)

        with engine.connect() as connection:
            assert _alembic_version(connection) == old_revision
        assert not (settings.database_path.parent / "migrations").exists()
    finally:
        engine.dispose()


def test_complete_create_all_database_without_revision_is_rejected(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        Base.metadata.create_all(engine)
        with pytest.raises(RuntimeError, match="fresh installation"):
            bootstrap_database(engine, settings)
        with engine.connect() as connection:
            assert _alembic_version(connection) is None
        assert not (settings.database_path.parent / "migrations").exists()
    finally:
        engine.dispose()


def test_apply_schema_bootstraps_empty_in_memory_database() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        runner_module.apply_schema(engine)
        assert _application_tables(engine) == EXPECTED_TABLES
        with engine.connect() as connection:
            assert _alembic_version(connection) == head_revision(engine)
    finally:
        engine.dispose()


def test_apply_schema_rejects_nonempty_unversioned_in_memory_database() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE User (id TEXT PRIMARY KEY NOT NULL)"
            )
        with pytest.raises(RuntimeError, match="fresh installation"):
            runner_module.apply_schema(engine)
        with engine.connect() as connection:
            assert _alembic_version(connection) is None
        assert "User" in _application_tables(engine)
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


def test_backup_restore_preserves_import_task_json_metadata(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage-json-metadata"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            original_metadata = {
                "title": "恢复前标题",
                "subjects": ["数据库", "备份"],
                "source": "PATH",
            }
            db.add(
                ImportTask(
                    id="backup-json-import-task",
                    origin="BACKUP_TEST",
                    status="COMPLETED",
                    source_path="/library/backup-test.epub",
                    source_key="backup-json-source-key",
                    recognized_metadata=original_metadata,
                )
            )
            db.commit()
            backup = create_backup(db, settings)

            task = db.get(ImportTask, "backup-json-import-task")
            assert task is not None
            task.recognized_metadata = {"title": "恢复后临时值"}
            db.commit()

            restored = restore_backup(db, settings, backup.id)

            assert restored["restored"] is True
            restored_task = db.get(ImportTask, "backup-json-import-task")
            assert restored_task is not None
            assert restored_task.recognized_metadata == original_metadata
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


def test_restore_validation_failure_does_not_touch_live_database(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage-invalid-restore"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.add(SystemSetting(key="restore.guard", value="must-survive"))
            db.commit()
            backup = create_backup(db, settings)
            _replace_backup_database_export(
                backup_path(settings, backup.id),
                {
                    "works": [],
                    "mediaVersions": [
                        {
                            "id": "dangling-media",
                            "workId": "missing-work",
                            "mediaKind": "EBOOK",
                        }
                    ],
                },
            )

            with pytest.raises(ValueError, match="BACKUP_FOREIGN_KEY_INVALID"):
                restore_backup(db, settings, backup.id)

            assert (
                db.scalar(
                    select(SystemSetting.value).where(
                        SystemSetting.key == "restore.guard"
                    )
                )
                == "must-survive"
            )
    finally:
        engine.dispose()


def test_live_restore_failure_rolls_back_and_clears_maintenance_state(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage-rollback-restore"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.add(SystemSetting(key="restore.guard", value="archived"))
            db.commit()
            backup = create_backup(db, settings)
            db.execute(
                update(SystemSetting)
                .where(SystemSetting.key == "restore.guard")
                .values(value="must-survive")
            )
            db.commit()

            original_apply = SqlAlchemyBackupRestoreWriter.apply
            restore_plan_calls = 0

            def fail_during_live_restore(
                writer: SqlAlchemyBackupRestoreWriter,
                plan: PreparedRestorePlan,
            ) -> None:
                nonlocal restore_plan_calls
                if plan.restored_counts:
                    restore_plan_calls += 1
                    if restore_plan_calls == 2:
                        original_apply(
                            writer,
                            PreparedRestorePlan((plan.statements[0],), {}),
                        )
                        raise RuntimeError("simulated live restore failure")
                original_apply(writer, plan)

            monkeypatch.setattr(
                SqlAlchemyBackupRestoreWriter,
                "apply",
                fail_during_live_restore,
            )

            with pytest.raises(RuntimeError, match="simulated live restore failure"):
                restore_backup(db, settings, backup.id)

            assert (
                db.scalar(
                    select(SystemSetting.value).where(
                        SystemSetting.key == "restore.guard"
                    )
                )
                == "must-survive"
            )
            assert db.get(SystemSetting, "databaseMaintenanceMode") is None
    finally:
        engine.dispose()


def test_temporary_restore_execution_failure_does_not_touch_live_database(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage-temp-restore-failure"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.add(SystemSetting(key="restore.guard", value="must-survive"))
            db.commit()
            backup = create_backup(db, settings)
            _replace_backup_database_export(
                backup_path(settings, backup.id),
                {
                    "users": [
                        {
                            "id": "duplicate-email-a",
                            "email": "same@example.com",
                            "name": "First",
                            "passwordHash": "hash-a",
                            "role": "user",
                            "status": "active",
                        },
                        {
                            "id": "duplicate-email-b",
                            "email": "same@example.com",
                            "name": "Second",
                            "passwordHash": "hash-b",
                            "role": "user",
                            "status": "active",
                        },
                    ]
                },
            )

            with pytest.raises(IntegrityError):
                restore_backup(db, settings, backup.id)

            assert (
                db.scalar(
                    select(SystemSetting.value).where(
                        SystemSetting.key == "restore.guard"
                    )
                )
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
