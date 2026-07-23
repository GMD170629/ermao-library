import json
import sqlite3
import zipfile

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import bootstrap as bootstrap_module
from app.db.bootstrap import bootstrap_database
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
    "ImportTask",
    "KindleSendTask",
    "LibraryEdition",
    "LibraryEditionFacet",
    "LibraryFacet",
    "LibraryFile",
    "LibraryMetadata",
    "LibraryOperation",
    "LibraryReadingProgress",
    "LibraryConsumptionState",
    "LibraryReadingUnit",
    "LibraryVolume",
    "LibraryWork",
    "LibraryWorkFacet",
    "MetadataSuggestion",
    "MetadataLookupTask",
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
    "ShelfWork",
    "Source",
    "SourceSearchRecord",
    "SystemEvent",
    "SystemSetting",
    "User",
    "UserMonitorFolderAccess",
    "UserPreference",
    "WorkDetailPreference",
}


def test_empty_storage_bootstraps_complete_sqlite_database(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        bootstrap_database(engine, settings)

        assert settings.database_path.is_file()
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 10_000
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 13
            assert connection.execute(text("SELECT COUNT(*) FROM `User`")).scalar() == 0
            assert "avatarPath" in {column[1] for column in connection.exec_driver_sql("PRAGMA table_info(`User`)").fetchall()}
            assert "shelfId" in {column[1] for column in connection.exec_driver_sql("PRAGMA table_info(`MonitorFolder`)").fetchall()}
            organize_policy_columns = {
                column[1]: column
                for column in connection.exec_driver_sql("PRAGMA table_info(`OrganizePolicy`)").fetchall()
            }
            assert organize_policy_columns["overwriteTitleAuthor"][4] == "1"
            preference_columns = {
                column[1]: column
                for column in connection.exec_driver_sql("PRAGMA table_info(`ReaderBookPreference`)").fetchall()
            }
            assert preference_columns["schemaVersion"][4] == "3"
            assert ReaderBookPreference.__table__.c.schemaVersion.default.arg == 3
            assert str(ReaderBookPreference.__table__.c.schemaVersion.server_default.arg) == "3"
            assert connection.execute(text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'systemName'")).scalar() == "二毛图书"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None
    finally:
        engine.dispose()


def test_bootstrap_migrates_reader_preference_default_to_v3_without_losing_rows(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO `User` (`id`, `email`, `name`, `passwordHash`, `updatedAt`) "
                "VALUES ('reader-user', 'reader@example.test', 'Reader', 'hash', CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO `LibraryWork` (`id`, `title`, `normalizedTitle`, `workType`, `tags`, `updatedAt`) "
                "VALUES ('reader-work', 'Reader Work', 'reader work', 'EPUB', '[]', CURRENT_TIMESTAMP)"
            ))
            connection.execute(
                text(
                    "INSERT INTO `ReaderBookPreference` "
                    "(`id`, `userId`, `workId`, `schemaVersion`, `preferences`, `createdAt`, `updatedAt`) "
                    "VALUES ('preference-v2', 'reader-user', 'reader-work', 2, :preferences, "
                    "'2026-07-01T01:00:00', '2026-07-02T01:00:00')"
                ),
                {"preferences": '{"schemaVersion":2}'},
            )
            connection.exec_driver_sql("ALTER TABLE `ReaderBookPreference` RENAME TO `ReaderBookPreference_v2`")
            connection.exec_driver_sql(
                """
                CREATE TABLE `ReaderBookPreference` (
                    `id` TEXT NOT NULL PRIMARY KEY,
                    `userId` TEXT NOT NULL,
                    `workId` TEXT NOT NULL,
                    `schemaVersion` INTEGER NOT NULL DEFAULT 2,
                    `preferences` TEXT NOT NULL,
                    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    `updatedAt` TEXT NOT NULL,
                    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
                    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
                )
                """
            )
            connection.exec_driver_sql(
                "INSERT INTO `ReaderBookPreference` SELECT * FROM `ReaderBookPreference_v2`"
            )
            connection.exec_driver_sql("DROP TABLE `ReaderBookPreference_v2`")
            connection.exec_driver_sql("PRAGMA user_version = 2")

        bootstrap_database(engine, settings)

        with engine.begin() as connection:
            columns = {
                column[1]: column
                for column in connection.exec_driver_sql("PRAGMA table_info(`ReaderBookPreference`)").fetchall()
            }
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 13
            assert columns["schemaVersion"][4] == "3"
            migrated = connection.execute(text(
                "SELECT `id`, `userId`, `workId`, `schemaVersion`, `preferences`, `createdAt`, `updatedAt` "
                "FROM `ReaderBookPreference` WHERE `id` = 'preference-v2'"
            )).mappings().one()
            assert dict(migrated) == {
                "id": "preference-v2",
                "userId": "reader-user",
                "workId": "reader-work",
                "schemaVersion": 2,
                "preferences": '{"schemaVersion":2}',
                "createdAt": "1782867600000",
                "updatedAt": "1782954000000",
            }
            indexes = {
                row[1]: row
                for row in connection.exec_driver_sql("PRAGMA index_list(`ReaderBookPreference`)").fetchall()
            }
            assert {
                "ReaderBookPreference_userId_idx",
                "ReaderBookPreference_workId_idx",
                "ReaderBookPreference_userId_workId_key",
            }.issubset(indexes)
            assert indexes["ReaderBookPreference_userId_workId_key"][2] == 1
            foreign_keys = {
                (row[3], row[2], row[4], row[5], row[6])
                for row in connection.exec_driver_sql("PRAGMA foreign_key_list(`ReaderBookPreference`)").fetchall()
            }
            assert foreign_keys == {
                ("userId", "User", "id", "CASCADE", "CASCADE"),
                ("workId", "LibraryWork", "id", "CASCADE", "CASCADE"),
            }
            connection.execute(text("DELETE FROM `ReaderBookPreference` WHERE `id` = 'preference-v2'"))
            connection.execute(text(
                "INSERT INTO `ReaderBookPreference` (`id`, `userId`, `workId`, `preferences`, `updatedAt`) "
                "VALUES ('preference-default', 'reader-user', 'reader-work', '{}', CURRENT_TIMESTAMP)"
            ))
            assert connection.execute(text(
                "SELECT `schemaVersion` FROM `ReaderBookPreference` WHERE `id` = 'preference-default'"
            )).scalar() == 3
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None

        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 13
            assert connection.execute(text(
                "SELECT COUNT(*) FROM `ReaderBookPreference` WHERE `id` = 'preference-default'"
            )).scalar() == 1
            indexes = {
                row[1]: row
                for row in connection.exec_driver_sql("PRAGMA index_list(`ReaderBookPreference`)").fetchall()
            }
            assert indexes["ReaderBookPreference_userId_workId_key"][2] == 1
    finally:
        engine.dispose()


def test_bootstrap_adds_optional_shelf_to_legacy_monitor_folders(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE `MonitorFolder` (`id` TEXT PRIMARY KEY, `name` TEXT NOT NULL, `rootPath` TEXT NOT NULL)"))

        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            columns = {column[1] for column in connection.exec_driver_sql("PRAGMA table_info(`MonitorFolder`)").fetchall()}
            assert "shelfId" in columns
    finally:
        engine.dispose()


def test_bootstrap_migrates_v1_import_tasks_before_creating_new_indexes(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE `ImportTask` (
                        `id` TEXT NOT NULL PRIMARY KEY,
                        `monitorFolderId` TEXT NULL,
                        `workId` TEXT NULL,
                        `editionId` TEXT NULL,
                        `volumeId` TEXT NULL,
                        `origin` TEXT NOT NULL,
                        `status` TEXT NOT NULL DEFAULT 'PENDING',
                        `originalName` TEXT NULL,
                        `sourcePath` TEXT NOT NULL,
                        `contentHash` TEXT NULL,
                        `progress` INTEGER NOT NULL DEFAULT 0,
                        `duplicate` INTEGER NOT NULL DEFAULT 0,
                        `duration` INTEGER NOT NULL DEFAULT 0,
                        `errorSummary` TEXT NULL,
                        `message` TEXT NULL,
                        `startedAt` TEXT NULL,
                        `finishedAt` TEXT NULL,
                        `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        `updatedAt` TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `ImportTask` "
                    "(`id`, `origin`, `status`, `sourcePath`, `progress`, `updatedAt`) "
                    "VALUES ('legacy-import', 'WATCH', 'PENDING', '/monitor/legacy.epub', 37, CURRENT_TIMESTAMP)"
                )
            )
            connection.exec_driver_sql("PRAGMA user_version = 1")

        bootstrap_database(engine, settings)
        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            columns = {column[1] for column in connection.exec_driver_sql("PRAGMA table_info(`ImportTask`)").fetchall()}
            assert {"errorCode", "retryable", "attempts", "leaseOwner", "leaseExpiresAt"}.issubset(columns)
            legacy = connection.execute(
                text(
                    "SELECT `origin`, `status`, `sourcePath`, `progress`, `retryable`, `attempts`, "
                    "`leaseOwner`, `leaseExpiresAt` FROM `ImportTask` WHERE `id` = 'legacy-import'"
                )
            ).mappings().one()
            assert dict(legacy) == {
                "origin": "WATCH",
                "status": "PENDING",
                "sourcePath": "/monitor/legacy.epub",
                "progress": 37,
                "retryable": 0,
                "attempts": 0,
                "leaseOwner": None,
                "leaseExpiresAt": None,
            }
            indexes = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(`ImportTask`)").fetchall()}
            assert "ImportTask_status_leaseExpiresAt_idx" in indexes
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 13
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None

            backup_path = settings.database_path.parent / "migrations" / "shuku-before-v13.sqlite3"
        assert backup_path.is_file()
        with sqlite3.connect(backup_path) as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
            backup_columns = {row[1] for row in backup.execute("PRAGMA table_info(`ImportTask`)").fetchall()}
            assert "leaseExpiresAt" not in backup_columns
            assert backup.execute("SELECT progress FROM ImportTask WHERE id = 'legacy-import'").fetchone()[0] == 37
    finally:
        engine.dispose()


def test_v4_migration_promotes_one_primary_for_every_visible_media_group(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO `LibraryWork` "
                    "(`id`, `title`, `normalizedTitle`, `workType`, `tags`, `updatedAt`) "
                    "VALUES ('mixed-primary-work', '多媒介旧书', '多媒介旧书', 'EPUB', '[]', CURRENT_TIMESTAMP)"
                )
            )
            for edition_id, fmt, primary, created_at in (
                ("old-epub", "EPUB", 1, "2026-01-01T00:00:00"),
                ("old-comic-first", "COMIC", 0, "2026-01-02T00:00:00"),
                ("old-comic-second", "COMIC", 0, "2026-01-03T00:00:00"),
                ("old-audio", "AUDIO", 0, "2026-01-04T00:00:00"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO `LibraryEdition` "
                        "(`id`, `workId`, `format`, `versionName`, `versionKey`, `primary`, `createdAt`, `updatedAt`) "
                        "VALUES (:id, 'mixed-primary-work', :format, :id, :id, :primary, :created_at, :created_at)"
                    ),
                    {"id": edition_id, "format": fmt, "primary": primary, "created_at": created_at},
                )
            connection.exec_driver_sql("PRAGMA user_version = 3")

        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            grouped = connection.execute(
                text(
                    "SELECT `mediaKind`, COUNT(*) AS edition_count, SUM(`primary`) AS primary_count "
                    "FROM `LibraryEdition` WHERE `workId` = 'mixed-primary-work' AND `hidden` = 0 "
                    "GROUP BY `mediaKind` ORDER BY `mediaKind`"
                )
            ).all()
            assert grouped == [("AUDIOBOOK", 1, 1), ("COMIC", 2, 1), ("EBOOK", 1, 1)]
            assert connection.execute(
                text(
                    "SELECT `id` FROM `LibraryEdition` WHERE `workId` = 'mixed-primary-work' "
                    "AND `mediaKind` = 'COMIC' AND `primary` = 1"
                )
            ).scalar_one() == "old-comic-first"
    finally:
        engine.dispose()


def test_v5_migration_allows_duplicate_work_identity_keys(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX `LibraryWork_mergeKey_idx`")
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX `LibraryWork_mergeKey_key` ON `LibraryWork`(`mergeKey`)"
            )
            connection.execute(
                text(
                    "INSERT INTO `LibraryWork` "
                    "(`id`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`, `workType`, `tags`, `mergeKey`, `updatedAt`) "
                    "VALUES ('same-a', '同名书', '同名书', '同作者', '同作者', 'EPUB', '[]', '同名书:同作者', CURRENT_TIMESTAMP)"
                )
            )
            connection.exec_driver_sql("PRAGMA user_version = 4")

        bootstrap_database(engine, settings)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO `LibraryWork` "
                    "(`id`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`, `workType`, `tags`, `mergeKey`, `updatedAt`) "
                    "VALUES ('same-b', '同名书', '同名书', '同作者', '同作者', 'EPUB', '[]', '同名书:同作者', CURRENT_TIMESTAMP)"
                )
            )
            indexes = {
                row[1]: row
                for row in connection.exec_driver_sql("PRAGMA index_list(`LibraryWork`)").fetchall()
            }
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 13
            assert "LibraryWork_mergeKey_key" not in indexes
            assert indexes["LibraryWork_mergeKey_idx"][2] == 0
            assert connection.execute(
                text("SELECT COUNT(*) FROM `LibraryWork` WHERE `mergeKey` = '同名书:同作者'")
            ).scalar() == 2
    finally:
        engine.dispose()


def test_v10_migration_consolidates_duplicate_unresolved_organize_records(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX `OrganizeJob_unresolved_workId_key`"))
            connection.execute(
                text(
                    """
                    INSERT INTO `LibraryWork`
                        (`id`, `origin`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`,
                         `workType`, `tags`, `metadataQuality`, `organizeStatus`, `hidden`, `organized`,
                         `createdAt`, `updatedAt`)
                    VALUES
                        ('duplicate-unresolved-work', 'MANUAL', '重复未识别', '重复未识别',
                         '未知作者', '未知作者', 'EPUB', '[]', 0, 'REVIEWING', 0, 0,
                         '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO `OrganizeJob`
                        (`id`, `workId`, `status`, `issueCodes`, `summary`, `createdAt`, `updatedAt`)
                    VALUES
                        ('older-unresolved', 'duplicate-unresolved-work', 'FAILED', '[]', '旧记录',
                         '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
                        ('newer-unresolved', 'duplicate-unresolved-work', 'FAILED', '[]', '新记录',
                         '2026-02-01T00:00:00+00:00', '2026-02-01T00:00:00+00:00')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO `MetadataLookupTask`
                        (`id`, `workId`, `organizeJobId`, `status`, `providerOrder`, `attempts`,
                         `nextAttemptAt`, `createdAt`, `updatedAt`)
                    VALUES
                        ('older-lookup', 'duplicate-unresolved-work', 'older-unresolved', 'NO_PROVIDER',
                         '[]', 0, '2026-01-01T00:00:00+00:00',
                         '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """
                )
            )
            connection.exec_driver_sql("PRAGMA user_version = 9")

        bootstrap_database(engine, settings)

        with engine.begin() as connection:
            jobs = connection.execute(
                text(
                    "SELECT `id`, `status`, `summary` FROM `OrganizeJob` "
                    "WHERE `workId` = 'duplicate-unresolved-work' ORDER BY `id`"
                )
            ).mappings().all()
            assert [dict(job) for job in jobs] == [
                {
                    "id": "newer-unresolved",
                    "status": "FAILED",
                    "summary": "新记录",
                },
                {
                    "id": "older-unresolved",
                    "status": "CANCELLED",
                    "summary": "已取消",
                },
            ]
            assert connection.execute(
                text("SELECT `status` FROM `MetadataLookupTask` WHERE `id` = 'older-lookup'")
            ).scalar() == "CANCELLED"
            indexes = {
                row[1]: row
                for row in connection.exec_driver_sql("PRAGMA index_list(`OrganizeJob`)").fetchall()
            }
            assert indexes["OrganizeJob_unresolved_workId_key"][2] == 1
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        """
                        INSERT INTO `OrganizeJob`
                            (`id`, `workId`, `status`, `issueCodes`, `createdAt`, `updatedAt`)
                        VALUES
                            ('third-unresolved', 'duplicate-unresolved-work', 'LOOKUP_PENDING', '[]',
                             CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """
                    )
                )
    finally:
        engine.dispose()


def test_current_v10_bootstrap_repairs_terminal_lookup_linked_to_cancelled_duplicate(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO `LibraryWork`
                        (`id`, `origin`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`,
                         `workType`, `tags`, `metadataQuality`, `organizeStatus`, `hidden`, `organized`,
                         `createdAt`, `updatedAt`)
                    VALUES
                        ('already-v10-work', 'MANUAL', '升级恢复', '升级恢复',
                         '未知作者', '未知作者', 'EPUB', '[]', 0, 'REVIEWING', 0, 0,
                         '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO `OrganizeJob`
                        (`id`, `workId`, `status`, `issueCodes`, `summary`, `createdAt`, `updatedAt`)
                    VALUES
                        ('cancelled-v10-job', 'already-v10-work', 'CANCELLED', '[]', '已由较新的未识别记录取代',
                         '2026-01-01T00:00:00+00:00', '2026-03-01T00:00:00+00:00'),
                        ('current-v10-job', 'already-v10-work', 'FAILED', '[]', '没有启用的适用元数据源',
                         '2026-02-01T00:00:00+00:00', '2026-02-01T00:00:00+00:00')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO `MetadataLookupTask`
                        (`id`, `workId`, `organizeJobId`, `status`, `providerOrder`, `attempts`,
                         `nextAttemptAt`, `errorSummary`, `createdAt`, `updatedAt`)
                    VALUES
                        ('stale-v10-lookup', 'already-v10-work', 'cancelled-v10-job', 'NO_PROVIDER',
                         '[]', 1, NULL, '所有适用的元数据插件均未启用',
                         '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """
                )
            )
            connection.exec_driver_sql("PRAGMA user_version = 10")

        bootstrap_database(engine, settings)
        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            jobs = connection.execute(
                text(
                    "SELECT `id`, `status` FROM `OrganizeJob` "
                    "WHERE `workId` = 'already-v10-work' ORDER BY `id`"
                )
            ).all()
            assert jobs == [("cancelled-v10-job", "CANCELLED"), ("current-v10-job", "FAILED")]
            lookup = connection.execute(
                text(
                    "SELECT `status`, `nextAttemptAt`, `finishedAt` FROM `MetadataLookupTask` "
                    "WHERE `id` = 'stale-v10-lookup'"
                )
            ).mappings().one()
            assert lookup["status"] == "CANCELLED"
            assert lookup["nextAttemptAt"] is None
            assert lookup["finishedAt"] is not None
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    finally:
        engine.dispose()


def test_bootstrap_repairs_current_version_with_incomplete_import_task_schema(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE `ImportTask` (
                        `id` TEXT NOT NULL PRIMARY KEY,
                        `monitorFolderId` TEXT NULL,
                        `workId` TEXT NULL,
                        `editionId` TEXT NULL,
                        `volumeId` TEXT NULL,
                        `origin` TEXT NOT NULL,
                        `status` TEXT NOT NULL DEFAULT 'PENDING',
                        `originalName` TEXT NULL,
                        `sourcePath` TEXT NOT NULL,
                        `contentHash` TEXT NULL,
                        `progress` INTEGER NOT NULL DEFAULT 0,
                        `duplicate` INTEGER NOT NULL DEFAULT 0,
                        `duration` INTEGER NOT NULL DEFAULT 0,
                        `errorSummary` TEXT NULL,
                        `message` TEXT NULL,
                        `startedAt` TEXT NULL,
                        `finishedAt` TEXT NULL,
                        `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        `updatedAt` TEXT NOT NULL
                    )
                    """
                )
            )
            connection.exec_driver_sql("PRAGMA user_version = 3")

        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            columns = {column[1] for column in connection.exec_driver_sql("PRAGMA table_info(`ImportTask`)").fetchall()}
            assert {"errorCode", "retryable", "attempts", "leaseOwner", "leaseExpiresAt"}.issubset(columns)
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 13
            indexes = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(`ImportTask`)").fetchall()}
            assert "ImportTask_status_leaseExpiresAt_idx" in indexes
    finally:
        engine.dispose()


def test_failed_schema_migration_rolls_back_and_keeps_source_version(tmp_path, monkeypatch) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE `ImportTask` (`id` TEXT PRIMARY KEY, `status` TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO `ImportTask` (`id`, `status`) VALUES ('legacy-import', 'PENDING')"))
            connection.exec_driver_sql("PRAGMA user_version = 1")

        def failing_migration(connection):
            connection.execute("ALTER TABLE `ImportTask` ADD COLUMN `temporaryMigrationColumn` TEXT NULL")
            raise RuntimeError("simulated migration failure")

        monkeypatch.setitem(bootstrap_module.SCHEMA_MIGRATIONS, 2, failing_migration)
        with pytest.raises(RuntimeError, match="simulated migration failure"):
            bootstrap_database(engine, settings)

        with engine.connect() as connection:
            columns = {column[1] for column in connection.exec_driver_sql("PRAGMA table_info(`ImportTask`)").fetchall()}
            assert "temporaryMigrationColumn" not in columns
            assert connection.exec_driver_sql("PRAGMA user_version").scalar() == 1
            assert connection.execute(text("SELECT `status` FROM `ImportTask` WHERE `id` = 'legacy-import'")).scalar() == "PENDING"
    finally:
        engine.dispose()


def test_bootstrap_migrates_legacy_want_status_and_defaults_new_works_to_unread(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO `LibraryWork` "
                    "(`id`, `origin`, `title`, `normalizedTitle`, `workType`, `status`, `tags`, `updatedAt`) "
                    "VALUES ('legacy-want', 'MANUAL', '旧状态', '旧状态', 'EPUB', 'WANT', '[]', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `LibraryWork` "
                    "(`id`, `origin`, `title`, `normalizedTitle`, `workType`, `tags`, `updatedAt`) "
                    "VALUES ('fresh-unread', 'MANUAL', '新状态', '新状态', 'EPUB', '[]', CURRENT_TIMESTAMP)"
                )
            )

        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            statuses = connection.execute(text("SELECT `id`, `status` FROM `LibraryWork` ORDER BY `id`")).all()
            assert statuses == [("fresh-unread", "UNREAD"), ("legacy-want", "UNREAD")]
    finally:
        engine.dispose()


def test_backup_restore_preserves_monitor_folder_target_shelf(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"), monitor_root=str(tmp_path / "books"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.execute(text("INSERT INTO `Shelf` (`id`, `name`, `createdAt`, `updatedAt`) VALUES ('auto-shelf', '自动收录', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            db.execute(
                text(
                    "INSERT INTO `MonitorFolder` (`id`, `name`, `rootPath`, `shelfId`, `enabled`, `ignoreHidden`, `minFileSizeBytes`, `createdAt`, `updatedAt`) "
                    "VALUES ('watch-folder', '收件箱', :root_path, 'auto-shelf', 1, 1, 10240, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"root_path": str(settings.resolved_monitor_root)},
            )
            db.commit()
            backup = create_backup(db, settings)

            restored = restore_backup(db, settings, backup.id)

            assert restored["restored"] is True
            assert db.execute(text("SELECT `shelfId` FROM `MonitorFolder` WHERE `id` = 'watch-folder'")).scalar() == "auto-shelf"
            assert db.execute(text("PRAGMA foreign_key_check")).first() is None
    finally:
        engine.dispose()


def test_backup_restore_preserves_multi_user_authorization_preferences_and_bookmarks(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"), monitor_root=str(tmp_path / "books"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.execute(
                text(
                    "INSERT INTO `User` "
                    "(`id`, `email`, `name`, `passwordHash`, `role`, `canManageSystem`, "
                    "`canViewManualImports`, `authzVersion`, `createdAt`, `updatedAt`) "
                    "VALUES ('backup-user', 'backup-user@example.test', 'Backup User', 'hash', "
                    "'member', 1, 0, 7, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `MonitorFolder` "
                    "(`id`, `name`, `rootPath`, `enabled`, `ignoreHidden`, `minFileSizeBytes`, "
                    "`createdAt`, `updatedAt`) "
                    "VALUES ('backup-folder', 'Backup Folder', :root_path, 1, 1, 10240, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"root_path": str(settings.resolved_monitor_root)},
            )
            db.execute(
                text(
                    "INSERT INTO `UserMonitorFolderAccess` (`userId`, `monitorFolderId`, `createdAt`) "
                    "VALUES ('backup-user', 'backup-folder', CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `UserPreference` (`userId`, `key`, `value`, `createdAt`, `updatedAt`) "
                    "VALUES ('backup-user', 'locale', '\"en-US\"', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `Shelf` (`id`, `ownerUserId`, `name`, `createdAt`, `updatedAt`) "
                    "VALUES ('backup-shelf', 'backup-user', 'Backup Shelf', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `LibraryWork` "
                    "(`id`, `monitorFolderId`, `origin`, `title`, `normalizedTitle`, `workType`, "
                    "`status`, `tags`, `createdAt`, `updatedAt`) "
                    "VALUES ('backup-work', 'backup-folder', 'WATCH', 'Backup Work', 'backup work', "
                    "'EPUB', 'UNREAD', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `LibraryEdition` "
                    "(`id`, `workId`, `monitorFolderId`, `origin`, `mediaKind`, `format`, "
                    "`versionName`, `versionKey`, `importStatus`, `primary`, `hidden`, `createdAt`, `updatedAt`) "
                    "VALUES ('backup-edition', 'backup-work', 'backup-folder', 'WATCH', 'EBOOK', "
                    "'EPUB', 'Default', 'backup-edition', 'COMPLETED', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `ReaderBookmark` "
                    "(`id`, `userId`, `workId`, `editionId`, `contentFingerprint`, `bookmarkId`, "
                    "`locationJson`, `label`, `percent`, `bookmarkCreatedAt`, `createdAt`, `updatedAt`) "
                    "VALUES ('backup-bookmark', 'backup-user', 'backup-work', 'backup-edition', "
                    "'sha256:backup', 'epub:backup', '{\"kind\":\"epub\"}', 'Backup', 25, "
                    "'2026-07-23T00:00:00Z', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            db.commit()
            backup = create_backup(db, settings)

            db.execute(text("DELETE FROM `ReaderBookmark` WHERE `userId` = 'backup-user'"))
            db.execute(text("DELETE FROM `UserMonitorFolderAccess` WHERE `userId` = 'backup-user'"))
            db.execute(text("DELETE FROM `UserPreference` WHERE `userId` = 'backup-user'"))
            db.execute(text("DELETE FROM `Shelf` WHERE `ownerUserId` = 'backup-user'"))
            db.commit()

            restored = restore_backup(db, settings, backup.id)

            assert restored["restored"] is True
            assert db.execute(
                text(
                    "SELECT `monitorFolderId` FROM `UserMonitorFolderAccess` "
                    "WHERE `userId` = 'backup-user'"
                )
            ).scalar_one() == "backup-folder"
            assert db.execute(
                text(
                    "SELECT `value` FROM `UserPreference` "
                    "WHERE `userId` = 'backup-user' AND `key` = 'locale'"
                )
            ).scalar_one() == '"en-US"'
            assert db.execute(
                text("SELECT `ownerUserId` FROM `Shelf` WHERE `id` = 'backup-shelf'")
            ).scalar_one() == "backup-user"
            assert db.execute(
                text(
                    "SELECT `bookmarkId` FROM `ReaderBookmark` "
                    "WHERE `userId` = 'backup-user' AND `editionId` = 'backup-edition'"
                )
            ).scalar_one() == "epub:backup"
    finally:
        engine.dispose()


def test_restore_pre_v4_backup_normalizes_media_kinds_and_backfills_consumption_state(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"), monitor_root=str(tmp_path / "books"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        legacy_id = "backup-42"
        export = {
            "users": [
                {
                    "id": "legacy-user",
                    "email": "legacy@example.test",
                    "name": "Legacy",
                    "passwordHash": "hash",
                    "role": "admin",
                    "createdAt": "2026-01-01T00:00:00",
                    "updatedAt": "2026-01-01T00:00:00",
                }
            ],
            "works": [
                {
                    "id": "legacy-mixed-work",
                    "origin": "MANUAL",
                    "title": "旧版多媒介",
                    "normalizedTitle": "旧版多媒介",
                    "workType": "EPUB",
                    "status": "READING",
                    "primaryEditionId": "legacy-epub",
                    "tags": "[]",
                    "createdAt": "2026-01-01T00:00:00",
                    "updatedAt": "2026-01-01T00:00:00",
                }
            ],
            # A pre-v4 export has no mediaKind. Both records were legal under
            # the old work-wide primary model and must restore as distinct
            # media primaries, not both default to EBOOK.
            "editions": [
                {
                    "id": "legacy-epub",
                    "workId": "legacy-mixed-work",
                    "origin": "MANUAL",
                    "format": "EPUB",
                    "versionName": "电子版",
                    "versionKey": "legacy:epub",
                    "importStatus": "COMPLETED",
                    "sizeBytes": 0,
                    "coverStatus": "PENDING",
                    "primary": 1,
                    "hidden": 0,
                    "createdAt": "2026-01-01T00:00:00",
                    "updatedAt": "2026-01-01T00:00:00",
                },
                {
                    "id": "legacy-comic",
                    "workId": "legacy-mixed-work",
                    "origin": "MANUAL",
                    "format": "COMIC",
                    "versionName": "漫画版",
                    "versionKey": "legacy:comic",
                    "importStatus": "COMPLETED",
                    "sizeBytes": 0,
                    "coverStatus": "PENDING",
                    "primary": 1,
                    "hidden": 0,
                    "createdAt": "2026-01-02T00:00:00",
                    "updatedAt": "2026-01-02T00:00:00",
                },
            ],
        }
        path = backup_path(settings, legacy_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "metadata.json",
                json.dumps({"id": legacy_id, "app": "shuku-starship", "version": 2, "counts": {}}),
            )
            archive.writestr("database-export.json", json.dumps(export, ensure_ascii=False))

        with Session(engine) as db:
            restored = restore_backup(db, settings, legacy_id)
            assert restored["restored"] is True
            editions = db.execute(
                text("SELECT `id`, `mediaKind`, `primary` FROM `LibraryEdition` ORDER BY `id`")
            ).mappings().all()
            assert [dict(row) for row in editions] == [
                {"id": "legacy-comic", "mediaKind": "COMIC", "primary": 1},
                {"id": "legacy-epub", "mediaKind": "EBOOK", "primary": 1},
            ]
            states = db.execute(
                text(
                    "SELECT `mediaKind`, `status` FROM `LibraryConsumptionState` "
                    "WHERE `userId` = 'legacy-user' AND `workId` = 'legacy-mixed-work' ORDER BY `mediaKind`"
                )
            ).all()
            assert states == [("COMIC", "UNREAD"), ("EBOOK", "READING")]
            assert db.execute(text("PRAGMA foreign_key_check")).first() is None
    finally:
        engine.dispose()


def test_bootstrap_migrates_only_legacy_default_system_names(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(text("UPDATE `SystemSetting` SET `value` = :value WHERE `key` = 'language'"), {"value": '"en-US"'})

        for legacy_name in ('"书库星舰"', '"书栖"'):
            with engine.begin() as connection:
                connection.execute(text("UPDATE `SystemSetting` SET `value` = :value WHERE `key` = 'systemName'"), {"value": legacy_name})

            bootstrap_database(engine, settings)
            with engine.connect() as connection:
                assert connection.execute(text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'systemName'")).scalar() == "二毛图书"
                assert connection.execute(text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'language'")).scalar() == '"en-US"'

        with engine.begin() as connection:
            connection.execute(text("UPDATE `SystemSetting` SET `value` = :value WHERE `key` = 'systemName'"), {"value": '"我的书房"'})

        bootstrap_database(engine, settings)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'systemName'")).scalar() == '"我的书房"'
    finally:
        engine.dispose()


def test_bootstrap_preserves_an_existing_customized_account(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO `User` (`id`, `email`, `name`, `passwordHash`, `role`, `createdAt`, `updatedAt`) "
                    "VALUES ('existing-user', 'custom@example.com', 'Custom name', 'custom-hash', 'admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        bootstrap_database(engine, settings)

        with engine.connect() as connection:
            users = connection.execute(text("SELECT `email`, `name`, `passwordHash` FROM `User`")).mappings().all()
            assert [dict(user) for user in users] == [
                {"email": "custom@example.com", "name": "Custom name", "passwordHash": "custom-hash"}
            ]
    finally:
        engine.dispose()


def test_v13_migration_changes_implicit_user_role_default_without_demoting_owner(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE `User` (
                        `id` TEXT NOT NULL PRIMARY KEY,
                        `email` TEXT NOT NULL,
                        `name` TEXT NOT NULL,
                        `passwordHash` TEXT NOT NULL,
                        `avatarPath` TEXT NULL,
                        `role` TEXT NOT NULL DEFAULT 'admin',
                        `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        `updatedAt` TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `User` "
                    "(`id`, `email`, `name`, `passwordHash`, `createdAt`, `updatedAt`) "
                    "VALUES ('owner', 'owner@example.test', 'Owner', 'hash', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.exec_driver_sql("PRAGMA user_version = 12")

        bootstrap_database(engine, settings)

        with engine.begin() as connection:
            role_column = next(
                row
                for row in connection.exec_driver_sql("PRAGMA table_info(`User`)").fetchall()
                if row[1] == "role"
            )
            assert str(role_column[4]).strip("'\"") == "member"
            assert connection.execute(text("SELECT `role` FROM `User` WHERE `id` = 'owner'")).scalar() == "admin"
            connection.execute(
                text(
                    "INSERT INTO `User` "
                    "(`id`, `email`, `name`, `passwordHash`, `createdAt`, `updatedAt`) "
                    "VALUES ('new-member', 'member@example.test', 'Member', 'hash', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            assert connection.execute(
                text("SELECT `role` FROM `User` WHERE `id` = 'new-member'")
            ).scalar() == "member"
    finally:
        engine.dispose()


def test_legacy_global_reading_status_is_never_reassigned_after_original_owner_deletion(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO `User` (`id`, `email`, `name`, `passwordHash`, `role`, `createdAt`, `updatedAt`) "
                    "VALUES "
                    "('original-owner', 'owner@example.test', 'Owner', 'hash', 'admin', 1000, 1000), "
                    "('member', 'member@example.test', 'Member', 'hash', 'member', 2000, 2000)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `LibraryWork` "
                    "(`id`, `origin`, `title`, `normalizedTitle`, `workType`, `status`, `tags`, `createdAt`, `updatedAt`) "
                    "VALUES ('legacy-finished', 'MANUAL', 'Legacy', 'legacy', 'EPUB', 'FINISHED', '[]', 1000, 1000)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `LibraryEdition` "
                    "(`id`, `workId`, `origin`, `mediaKind`, `format`, `versionName`, `versionKey`, "
                    "`importStatus`, `primary`, `hidden`, `createdAt`, `updatedAt`) "
                    "VALUES ('legacy-edition', 'legacy-finished', 'MANUAL', 'EBOOK', 'EPUB', "
                    "'Default', 'legacy-edition', 'COMPLETED', 1, 0, 1000, 1000)"
                )
            )

        bootstrap_database(engine, settings)
        with engine.connect() as connection:
            states = connection.execute(
                text(
                    "SELECT `userId`, `status` FROM `LibraryConsumptionState` "
                    "WHERE `workId` = 'legacy-finished' ORDER BY `userId`"
                )
            ).all()
            assert states == [("original-owner", "FINISHED")]
            assert json.loads(
                connection.execute(
                    text(
                        "SELECT `value` FROM `SystemSetting` "
                        "WHERE `key` = 'migration.multiUserLegacyReadingStatusOwnerId'"
                    )
                ).scalar_one()
            ) == "original-owner"

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM `User` WHERE `id` = 'original-owner'"))

        bootstrap_database(engine, settings)
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM `LibraryConsumptionState` "
                    "WHERE `userId` = 'member' AND `workId` = 'legacy-finished'"
                )
            ).scalar_one() == 0
    finally:
        engine.dispose()


def test_legacy_global_kindle_email_migrates_only_to_original_admin(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        bootstrap_module.apply_schema(engine, settings)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO `User` (`id`, `email`, `name`, `passwordHash`, `role`, `createdAt`, `updatedAt`) "
                    "VALUES "
                    "('original-admin', 'admin@example.test', 'Admin', 'hash', 'admin', 1000, 1000), "
                    "('member', 'member@example.test', 'Member', 'hash', 'member', 2000, 2000)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
                    "VALUES ('kindle.email', :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"value": json.dumps("legacy_123@kindle.com")},
            )

        bootstrap_database(engine, settings)
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT `userId`, `value` FROM `UserPreference` "
                    "WHERE `key` = 'kindle.email' ORDER BY `userId`"
                )
            ).all()
            assert rows == [("original-admin", json.dumps("legacy_123@kindle.com"))]
            assert json.loads(
                connection.execute(
                    text(
                        "SELECT `value` FROM `SystemSetting` "
                        "WHERE `key` = 'migration.personalKindleEmailOwnerId'"
                    )
                ).scalar_one()
            ) == "original-admin"
    finally:
        engine.dispose()


def test_timestamp_migration_and_triggers_persist_unix_milliseconds(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER `normalize_SystemSetting_timestamps_update`")
            connection.execute(
                text(
                    "UPDATE `SystemSetting` SET `createdAt` = '2026-07-22T14:42:51Z', "
                    "`updatedAt` = '2026-07-22T14:42:51.125+00:00' WHERE `key` = 'language'"
                )
            )
            connection.exec_driver_sql("PRAGMA user_version = 11")

        bootstrap_database(engine, settings)

        with engine.begin() as connection:
            migrated = connection.execute(
                text("SELECT `createdAt`, `updatedAt` FROM `SystemSetting` WHERE `key` = 'language'")
            ).one()
            assert migrated == ("1784731371000", "1784731371125")

            connection.execute(
                text(
                    "INSERT INTO `User` (`id`, `email`, `name`, `passwordHash`, `createdAt`, `updatedAt`) "
                    "VALUES ('timestamp-user', 'timestamp@example.test', 'Timestamp', 'hash', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            stored = connection.execute(
                text("SELECT `createdAt`, `updatedAt` FROM `User` WHERE `id` = 'timestamp-user'")
            ).one()
            assert all(str(value).isdigit() and len(str(value)) == 13 for value in stored)
    finally:
        engine.dispose()


def test_bootstrap_runs_library_facet_backfill_only_once(tmp_path, monkeypatch) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'migration.libraryFacetBackfillVersion'")
            ).scalar() == "1"

        def unexpected_backfill(_db):
            raise AssertionError("facet backfill must not run again after the migration marker is stored")

        monkeypatch.setattr("app.services.library_management.backfill_library_facets", unexpected_backfill)
        bootstrap_database(engine, settings)
    finally:
        engine.dispose()
