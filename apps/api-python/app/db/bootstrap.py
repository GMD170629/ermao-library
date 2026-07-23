from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from importlib import resources
import json
import logging
import sqlite3
import time
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.i18n import DEFAULT_LOCALE
from app.core.time import to_timestamp_ms
from app.services.book_identity import UNKNOWN_AUTHOR, identity_merge_key, normalize_identity_part

LOGGER = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 14
SCHEMA_LOCK_RETRY_SECONDS = 60.0
DEFAULT_SYSTEM_NAME = "二毛图书"
LEGACY_DEFAULT_SYSTEM_NAMES = {"书库星舰", "书栖"}
IDENTITY_MIGRATION_SETTING = "migration.libraryIdentityVersion"
IDENTITY_MIGRATION_VERSION = "1"
METADATA_TITLE_MATCH_MIGRATION_SETTING = "migration.metadataTitleMatchVersion"
METADATA_TITLE_MATCH_MIGRATION_VERSION = "1"
LIBRARY_FACET_BACKFILL_SETTING = "migration.libraryFacetBackfillVersion"
LIBRARY_FACET_BACKFILL_VERSION = "1"
LEGACY_READING_STATUS_OWNER_SETTING = "migration.multiUserLegacyReadingStatusOwnerId"
LEGACY_KINDLE_EMAIL_OWNER_SETTING = "migration.personalKindleEmailOwnerId"


def _decoded_setting_value(value: object) -> object:
    if value is None:
        return None
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def bootstrap_database(engine: Engine, settings: Settings) -> None:
    """Initialize the SQLite schema and baseline data."""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    apply_schema(engine, settings)
    with Session(engine) as db:
        seed_baseline_data(db)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone() is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info(`{table}`)").fetchall()}


def _add_missing_columns(connection: sqlite3.Connection, table: str, additions: dict[str, str]) -> None:
    columns = _table_columns(connection, table)
    if not columns:
        return
    for column, definition in additions.items():
        if column in columns:
            continue
        connection.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")
        columns.add(column)


def _migrate_schema_v1(connection: sqlite3.Connection) -> None:
    """Repair compatibility columns introduced before schema versioning."""
    _add_missing_columns(connection, "User", {"avatarPath": "TEXT NULL"})
    _add_missing_columns(connection, "MonitorFolder", {"shelfId": "TEXT NULL"})


def _migrate_schema_v2(connection: sqlite3.Connection) -> None:
    """Add persistent import queue retry and lease state before its index is created."""
    _add_missing_columns(
        connection,
        "ImportTask",
        {
            "errorCode": "TEXT NULL",
            "retryable": "INTEGER NOT NULL DEFAULT 0",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "leaseOwner": "TEXT NULL",
            "leaseExpiresAt": "TEXT NULL",
        },
    )


def _migrate_schema_v3(connection: sqlite3.Connection) -> None:
    """Move work-scoped reader preference defaults to schema 3 without losing rows."""
    if not _table_exists(connection, "ReaderBookPreference"):
        return
    connection.execute("DROP TABLE IF EXISTS `ReaderBookPreference_v3`")
    connection.execute(
        """
        CREATE TABLE `ReaderBookPreference_v3` (
            `id` TEXT NOT NULL,
            `userId` TEXT NOT NULL,
            `workId` TEXT NOT NULL,
            `schemaVersion` INTEGER NOT NULL DEFAULT 3,
            `preferences` TEXT NOT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`id`),
            FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )
    connection.execute(
        """
        INSERT INTO `ReaderBookPreference_v3`
            (`id`, `userId`, `workId`, `schemaVersion`, `preferences`, `createdAt`, `updatedAt`)
        SELECT `id`, `userId`, `workId`, `schemaVersion`, `preferences`, `createdAt`, `updatedAt`
        FROM `ReaderBookPreference`
        """
    )
    connection.execute("DROP TABLE `ReaderBookPreference`")
    connection.execute("ALTER TABLE `ReaderBookPreference_v3` RENAME TO `ReaderBookPreference`")

    connection.execute(
        "CREATE INDEX `ReaderBookPreference_userId_idx` "
        "ON `ReaderBookPreference`(`userId`)"
    )
    connection.execute(
        "CREATE INDEX `ReaderBookPreference_workId_idx` "
        "ON `ReaderBookPreference`(`workId`)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX `ReaderBookPreference_userId_workId_key` "
        "ON `ReaderBookPreference`(`userId`, `workId`)"
    )


def _migrate_schema_v4(connection: sqlite3.Connection) -> None:
    """Add multi-media identity, audio metadata, and per-media state."""

    _add_missing_columns(
        connection,
        "LibraryEdition",
        {
            "mediaKind": "TEXT NOT NULL DEFAULT 'EBOOK'",
            "durationMs": "INTEGER NULL",
            "trackCount": "INTEGER NULL",
            "narrator": "TEXT NULL",
            "abridged": "INTEGER NULL",
        },
    )
    _add_missing_columns(connection, "LibraryVolume", {"durationMs": "INTEGER NULL"})
    _add_missing_columns(
        connection,
        "LibraryFile",
        {
            "durationMs": "INTEGER NULL",
            "codec": "TEXT NULL",
            "bitrate": "INTEGER NULL",
            "sampleRate": "INTEGER NULL",
            "channels": "INTEGER NULL",
            "discNumber": "INTEGER NULL",
            "trackNumber": "INTEGER NULL",
        },
    )
    _add_missing_columns(
        connection,
        "LibraryReadingUnit",
        {"startMs": "INTEGER NULL", "endMs": "INTEGER NULL", "durationMs": "INTEGER NULL"},
    )
    _add_missing_columns(
        connection,
        "ImportTask",
        {
            "taskKind": "TEXT NOT NULL DEFAULT 'FILE'",
            "bundleKey": "TEXT NULL",
            "assetCount": "INTEGER NOT NULL DEFAULT 1",
            "processedAssetCount": "INTEGER NOT NULL DEFAULT 0",
            "requestedTitle": "TEXT NULL",
            "requestedAuthor": "TEXT NULL",
        },
    )
    if _table_exists(connection, "LibraryEdition"):
        connection.execute(
            "UPDATE `LibraryEdition` SET `mediaKind` = CASE "
            "WHEN UPPER(`format`) = 'COMIC' THEN 'COMIC' "
            "WHEN UPPER(`format`) = 'AUDIO' THEN 'AUDIOBOOK' "
            "ELSE 'EBOOK' END"
        )
        # Old databases treated primary as work-wide. Repair malformed data as
        # well so the per-media partial unique index can be created safely.
        connection.execute(
            """
            UPDATE `LibraryEdition` AS candidate
            SET `primary` = 0
            WHERE COALESCE(candidate.`primary`, 0) = 1
              AND COALESCE(candidate.`hidden`, 0) = 0
              AND EXISTS (
                SELECT 1 FROM `LibraryEdition` AS winner
                WHERE winner.`workId` = candidate.`workId`
                  AND winner.`mediaKind` = candidate.`mediaKind`
                  AND COALESCE(winner.`primary`, 0) = 1
                  AND COALESCE(winner.`hidden`, 0) = 0
                  AND (winner.`createdAt` < candidate.`createdAt`
                       OR (winner.`createdAt` = candidate.`createdAt` AND winner.`id` < candidate.`id`))
              )
            """
        )
        # The old model only guaranteed one work-wide primary. Promote the
        # earliest visible edition for every media group that has none, so all
        # non-empty (workId, mediaKind) groups leave migration with exactly one.
        connection.execute(
            """
            UPDATE `LibraryEdition` AS candidate
            SET `primary` = 1
            WHERE COALESCE(candidate.`hidden`, 0) = 0
              AND candidate.`id` = (
                SELECT winner.`id`
                FROM `LibraryEdition` AS winner
                WHERE winner.`workId` = candidate.`workId`
                  AND winner.`mediaKind` = candidate.`mediaKind`
                  AND COALESCE(winner.`hidden`, 0) = 0
                ORDER BY winner.`createdAt` ASC, winner.`id` ASC
                LIMIT 1
              )
              AND NOT EXISTS (
                SELECT 1 FROM `LibraryEdition` AS selected
                WHERE selected.`workId` = candidate.`workId`
                  AND selected.`mediaKind` = candidate.`mediaKind`
                  AND COALESCE(selected.`primary`, 0) = 1
                  AND COALESCE(selected.`hidden`, 0) = 0
              )
            """
        )


def _migrate_schema_v5(connection: sqlite3.Connection) -> None:
    """Allow multiple works to share the same normalized title and author."""
    if not _table_exists(connection, "LibraryWork"):
        return
    connection.execute("DROP INDEX IF EXISTS `LibraryWork_mergeKey_key`")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS `LibraryWork_mergeKey_idx` ON `LibraryWork`(`mergeKey`)"
    )


def _migrate_schema_v6(connection: sqlite3.Connection) -> None:
    """Add organizer-owned scheduling, runs, and provider execution history."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `OrganizePolicy` (
            `id` TEXT NOT NULL,
            `enabled` INTEGER NOT NULL DEFAULT 0,
            `scheduleMode` TEXT NOT NULL DEFAULT 'MANUAL',
            `intervalMinutes` INTEGER NOT NULL DEFAULT 60,
            `autoRunOnNew` INTEGER NOT NULL DEFAULT 0,
            `autoRunOnNewSince` TEXT NULL,
            `rulesJson` TEXT NOT NULL DEFAULT '{}',
            `autoApplyEmptyFields` INTEGER NOT NULL DEFAULT 1,
            `lastScheduledAt` TEXT NULL,
            `nextRunAt` TEXT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`id`)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `OrganizeRun` (
            `id` TEXT NOT NULL,
            `trigger` TEXT NOT NULL,
            `scopeJson` TEXT NOT NULL DEFAULT '{}',
            `dedupeKey` TEXT NULL,
            `status` TEXT NOT NULL DEFAULT 'QUEUED',
            `queuedCount` INTEGER NOT NULL DEFAULT 0,
            `completedCount` INTEGER NOT NULL DEFAULT 0,
            `reviewCount` INTEGER NOT NULL DEFAULT 0,
            `failedCount` INTEGER NOT NULL DEFAULT 0,
            `startedAt` TEXT NULL,
            `finishedAt` TEXT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`id`),
            UNIQUE (`dedupeKey`)
        )
        """
    )
    _add_missing_columns(
        connection,
        "OrganizeJob",
        {
            "runId": "TEXT NULL",
            "trigger": "TEXT NOT NULL DEFAULT 'LEGACY'",
            "reasonCodes": "TEXT NOT NULL DEFAULT '[]'",
            "startedAt": "TEXT NULL",
            "finishedAt": "TEXT NULL",
        },
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `MetadataProviderExecution` (
            `id` TEXT NOT NULL,
            `jobId` TEXT NULL,
            `lookupTaskId` TEXT NULL,
            `providerId` TEXT NOT NULL,
            `status` TEXT NOT NULL DEFAULT 'PENDING',
            `attempts` INTEGER NOT NULL DEFAULT 0,
            `rawResultJson` TEXT NULL,
            `errorSummary` TEXT NULL,
            `startedAt` TEXT NULL,
            `finishedAt` TEXT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`id`),
            FOREIGN KEY (`jobId`) REFERENCES `OrganizeJob`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (`lookupTaskId`) REFERENCES `MetadataLookupTask`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )
    if _table_exists(connection, "OrganizeJob"):
        organize_job_columns = {row[1] for row in connection.execute("PRAGMA table_info(`OrganizeJob`)").fetchall()}
        if {"runId", "status"}.issubset(organize_job_columns):
            connection.execute("CREATE INDEX IF NOT EXISTS `OrganizeJob_runId_status_idx` ON `OrganizeJob`(`runId`, `status`)")
    connection.execute("CREATE INDEX IF NOT EXISTS `OrganizeRun_status_createdAt_idx` ON `OrganizeRun`(`status`, `createdAt`)")
    connection.execute("CREATE INDEX IF NOT EXISTS `MetadataProviderExecution_jobId_status_idx` ON `MetadataProviderExecution`(`jobId`, `status`)")
    connection.execute("CREATE INDEX IF NOT EXISTS `MetadataProviderExecution_lookupTaskId_idx` ON `MetadataProviderExecution`(`lookupTaskId`)")


def _migrate_schema_v7(connection: sqlite3.Connection) -> None:
    """Add the independent title/author overwrite strategy, enabled by default."""
    _add_missing_columns(
        connection,
        "OrganizePolicy",
        {"overwriteTitleAuthor": "INTEGER NOT NULL DEFAULT 1"},
    )


def _migrate_schema_v8(connection: sqlite3.Connection) -> None:
    """Add independent, ordered provider pipelines for every media kind."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `MetadataProviderPipeline` (
            `workType` TEXT NOT NULL,
            `providerId` TEXT NOT NULL,
            `included` INTEGER NOT NULL DEFAULT 1,
            `enabled` INTEGER NOT NULL DEFAULT 0,
            `position` INTEGER NOT NULL DEFAULT 100,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`workType`, `providerId`)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS `MetadataProviderPipeline_workType_position_idx` "
        "ON `MetadataProviderPipeline`(`workType`, `included`, `position`)"
    )


def _migrate_schema_v9(connection: sqlite3.Connection) -> None:
    """Add saved smart shelves, normalized library facets, and reversible operations."""
    _add_missing_columns(
        connection,
        "Shelf",
        {
            "kind": "TEXT NOT NULL DEFAULT 'STATIC'",
            "rulesJson": "TEXT NOT NULL DEFAULT '{}'",
            "pinned": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `LibraryFacet` (
            `id` TEXT NOT NULL,
            `kind` TEXT NOT NULL,
            `name` TEXT NOT NULL,
            `normalizedName` TEXT NOT NULL,
            `aliases` TEXT NOT NULL DEFAULT '[]',
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`id`),
            UNIQUE (`kind`, `normalizedName`)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `LibraryWorkFacet` (
            `facetId` TEXT NOT NULL,
            `workId` TEXT NOT NULL,
            `sortOrder` INTEGER NOT NULL DEFAULT 0,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`facetId`, `workId`),
            FOREIGN KEY (`facetId`) REFERENCES `LibraryFacet`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `LibraryEditionFacet` (
            `facetId` TEXT NOT NULL,
            `editionId` TEXT NOT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`facetId`, `editionId`),
            FOREIGN KEY (`facetId`) REFERENCES `LibraryFacet`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `LibraryOperation` (
            `id` TEXT NOT NULL,
            `userId` TEXT NULL,
            `action` TEXT NOT NULL,
            `status` TEXT NOT NULL DEFAULT 'COMPLETED',
            `targetType` TEXT NULL,
            `targetId` TEXT NULL,
            `summary` TEXT NOT NULL,
            `payloadJson` TEXT NOT NULL DEFAULT '{}',
            `inverseJson` TEXT NOT NULL DEFAULT '{}',
            `expiresAt` TEXT NULL,
            `undoneAt` TEXT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`id`),
            FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
        )
        """
    )
    if _table_exists(connection, "Shelf"):
        connection.execute("CREATE INDEX IF NOT EXISTS `Shelf_kind_updatedAt_idx` ON `Shelf`(`kind`, `updatedAt`)")
    connection.execute("CREATE INDEX IF NOT EXISTS `LibraryFacet_kind_name_idx` ON `LibraryFacet`(`kind`, `name`)")
    connection.execute("CREATE INDEX IF NOT EXISTS `LibraryWorkFacet_workId_idx` ON `LibraryWorkFacet`(`workId`)")
    connection.execute("CREATE INDEX IF NOT EXISTS `LibraryEditionFacet_editionId_idx` ON `LibraryEditionFacet`(`editionId`)")
    connection.execute("CREATE INDEX IF NOT EXISTS `LibraryOperation_action_createdAt_idx` ON `LibraryOperation`(`action`, `createdAt`)")
    connection.execute("CREATE INDEX IF NOT EXISTS `LibraryOperation_status_expiresAt_idx` ON `LibraryOperation`(`status`, `expiresAt`)")


def _migrate_schema_v10(connection: sqlite3.Connection) -> None:
    """Keep at most one unresolved organize record for each work."""
    if not _table_exists(connection, "OrganizeJob"):
        return
    unresolved = "'LOOKUP_PENDING', 'PENDING', 'QUEUED', 'RUNNING', 'RETRY_WAIT', 'REVIEWING', 'FAILED'"
    connection.execute(
        f"""
        CREATE TEMP TABLE `_OrganizeUnresolvedDuplicates` AS
        SELECT `id`
        FROM (
            SELECT `id`, ROW_NUMBER() OVER (
                PARTITION BY `workId`
                ORDER BY
                    CASE WHEN CAST(`createdAt` AS TEXT) GLOB '*[^0-9]*'
                         THEN julianday(`createdAt`) * 86400000 ELSE CAST(`createdAt` AS INTEGER) END DESC,
                    CASE WHEN CAST(`updatedAt` AS TEXT) GLOB '*[^0-9]*'
                         THEN julianday(`updatedAt`) * 86400000 ELSE CAST(`updatedAt` AS INTEGER) END DESC,
                    `id` DESC
            ) AS `position`
            FROM `OrganizeJob`
            WHERE `status` IN ({unresolved})
        ) ranked
        WHERE `position` > 1
        """
    )
    if _table_exists(connection, "MetadataLookupTask"):
        connection.execute(
            """
            UPDATE `MetadataLookupTask`
            SET `status` = 'CANCELLED', `nextAttemptAt` = NULL,
                `finishedAt` = COALESCE(`finishedAt`, CURRENT_TIMESTAMP),
                `updatedAt` = CURRENT_TIMESTAMP
            WHERE `organizeJobId` IN (SELECT `id` FROM `_OrganizeUnresolvedDuplicates`)
              AND `status` != 'CANCELLED'
            """
        )
    connection.execute(
        """
        UPDATE `OrganizeJob`
        SET `status` = 'CANCELLED', `summary` = '已由较新的未识别记录取代',
            `errorSummary` = NULL, `finishedAt` = COALESCE(`finishedAt`, CURRENT_TIMESTAMP),
            `updatedAt` = CURRENT_TIMESTAMP
        WHERE `id` IN (SELECT `id` FROM `_OrganizeUnresolvedDuplicates`)
        """
    )
    connection.execute("DROP TABLE `_OrganizeUnresolvedDuplicates`")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS `OrganizeJob_unresolved_workId_key`
        ON `OrganizeJob`(`workId`)
        WHERE `status` IN ('LOOKUP_PENDING', 'PENDING', 'QUEUED', 'RUNNING', 'RETRY_WAIT', 'REVIEWING', 'FAILED')
        """
    )


def _migrate_schema_v11(connection: sqlite3.Connection) -> None:
    """Keep lookup tasks terminal when v10 cancelled their duplicate parent job."""
    if not _table_exists(connection, "OrganizeJob") or not _table_exists(connection, "MetadataLookupTask"):
        return
    connection.execute(
        """
        UPDATE `MetadataLookupTask`
        SET `status` = 'CANCELLED', `nextAttemptAt` = NULL,
            `finishedAt` = COALESCE(`finishedAt`, CURRENT_TIMESTAMP),
            `updatedAt` = CURRENT_TIMESTAMP
        WHERE `organizeJobId` IN (
            SELECT `id` FROM `OrganizeJob` WHERE `status` = 'CANCELLED'
        )
          AND `status` != 'CANCELLED'
        """
    )


_LEGACY_LOCAL_TIMESTAMP_TABLES = {
    "BookConversionTask",
    "BookIdentityCache",
    "ImportLog",
    "ImportTask",
    "LibraryEdition",
    "LibraryFile",
    "LibraryMetadata",
    "LibraryReadingUnit",
    "LibraryVolume",
    "LibraryWork",
    "OrganizeJob",
}


def _timestamp_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info(`{table}`)").fetchall()
        if str(row[1]).endswith("At") or str(row[1]).endswith("_at")
    ]


def _migrate_schema_v12(connection: sqlite3.Connection) -> None:
    """Normalize every persisted application datetime to Unix milliseconds."""

    local_timezone = datetime.now().astimezone().tzinfo
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT `name` FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    for table in tables:
        columns = _timestamp_columns(connection, table)
        if not columns:
            continue
        rows = connection.execute(
            f"SELECT rowid, {', '.join(f'`{column}`' for column in columns)} FROM `{table}`"
        ).fetchall()
        naive_timezone = local_timezone if table in _LEGACY_LOCAL_TIMESTAMP_TABLES else timezone.utc
        for row in rows:
            updates: dict[str, int] = {}
            for index, column in enumerate(columns, start=1):
                timestamp = to_timestamp_ms(row[index], naive_timezone=naive_timezone)
                if timestamp is not None and str(row[index]) != str(timestamp):
                    updates[column] = timestamp
            if not updates:
                continue
            assignments = ", ".join(f"`{column}` = :{column}" for column in updates)
            connection.execute(
                f"UPDATE `{table}` SET {assignments} WHERE rowid = :rowid",
                {**updates, "rowid": row[0]},
            )
    if _table_exists(connection, "ImportTask"):
        connection.execute(
            "CREATE INDEX IF NOT EXISTS `ImportTask_createdAt_id_idx` ON `ImportTask`(`createdAt`, `id`)"
        )
    if _table_exists(connection, "LibraryWork"):
        connection.execute(
            "CREATE INDEX IF NOT EXISTS `LibraryWork_createdAt_id_idx` ON `LibraryWork`(`createdAt`, `id`)"
        )


def _migrate_schema_v13(connection: sqlite3.Connection) -> None:
    """Add multi-user authorization, account preferences, shelf ownership, and bookmarks."""

    user_columns = connection.execute("PRAGMA table_info(`User`)").fetchall() if _table_exists(connection, "User") else []
    role_column = next((row for row in user_columns if str(row[1]) == "role"), None)
    role_default = str(role_column[4] or "").strip("'\"").lower() if role_column is not None else ""
    if role_column is not None and role_default != "member":
        # SQLite cannot alter a column default directly. Replacing this
        # non-key column in place preserves the User table identity and all
        # incoming foreign keys while removing the legacy implicit-admin
        # default.
        connection.execute("ALTER TABLE `User` RENAME COLUMN `role` TO `roleV12`")
        connection.execute("ALTER TABLE `User` ADD COLUMN `role` TEXT NOT NULL DEFAULT 'member'")
        connection.execute(
            "UPDATE `User` SET `role` = CASE "
            "WHEN LOWER(COALESCE(`roleV12`, '')) = 'admin' THEN 'admin' ELSE 'member' END"
        )
        connection.execute("ALTER TABLE `User` DROP COLUMN `roleV12`")

    _add_missing_columns(
        connection,
        "User",
        {
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "canManageSystem": "INTEGER NOT NULL DEFAULT 0",
            "canViewManualImports": "INTEGER NOT NULL DEFAULT 0",
            "authzVersion": "INTEGER NOT NULL DEFAULT 1",
        },
    )
    _add_missing_columns(connection, "Shelf", {"ownerUserId": "TEXT NULL"})
    _add_missing_columns(connection, "KindleSendTask", {"userId": "TEXT NULL"})
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `UserMonitorFolderAccess` (
            `userId` TEXT NOT NULL,
            `monitorFolderId` TEXT NOT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`userId`, `monitorFolderId`),
            FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (`monitorFolderId`) REFERENCES `MonitorFolder`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `UserPreference` (
            `userId` TEXT NOT NULL,
            `key` TEXT NOT NULL,
            `value` TEXT NOT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`userId`, `key`),
            FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS `ReaderBookmark` (
            `id` TEXT NOT NULL,
            `userId` TEXT NOT NULL,
            `workId` TEXT NOT NULL,
            `editionId` TEXT NOT NULL,
            `contentFingerprint` TEXT NOT NULL,
            `bookmarkId` TEXT NOT NULL,
            `locationJson` TEXT NOT NULL,
            `label` TEXT NOT NULL,
            `percent` REAL NOT NULL DEFAULT 0,
            `bookmarkCreatedAt` TEXT NOT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`id`),
            FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )

    first_user = connection.execute(
        "SELECT `id` FROM `User` ORDER BY CAST(`createdAt` AS INTEGER) ASC, `id` ASC LIMIT 1"
    ).fetchone() if _table_exists(connection, "User") else None
    if first_user is not None:
        first_user_id = str(first_user[0])
        active_admin = connection.execute(
            "SELECT 1 FROM `User` WHERE `role` = 'admin' AND COALESCE(`status`, 'active') = 'active' LIMIT 1"
        ).fetchone()
        if active_admin is None:
            connection.execute(
                "UPDATE `User` SET `role` = 'admin', `updatedAt` = CURRENT_TIMESTAMP WHERE `id` = ?",
                (first_user_id,),
            )
        if _table_exists(connection, "Shelf"):
            connection.execute(
                "UPDATE `Shelf` SET `ownerUserId` = ? WHERE `ownerUserId` IS NULL",
                (first_user_id,),
            )
        if _table_exists(connection, "KindleSendTask"):
            connection.execute(
                "UPDATE `KindleSendTask` SET `userId` = ? WHERE `userId` IS NULL",
                (first_user_id,),
            )

        language_row = connection.execute(
            "SELECT `value` FROM `SystemSetting` WHERE `key` = 'language' LIMIT 1"
        ).fetchone() if _table_exists(connection, "SystemSetting") else None
        language_value = str(language_row[0]) if language_row is not None else json.dumps(DEFAULT_LOCALE)
        connection.execute(
            """
            INSERT OR IGNORE INTO `UserPreference`
                (`userId`, `key`, `value`, `createdAt`, `updatedAt`)
            SELECT `id`, 'locale', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM `User`
            """,
            (language_value,),
        )

        if _table_exists(connection, "MonitorFolder") and _table_exists(connection, "Shelf"):
            links = connection.execute(
                "SELECT `shelfId`, `id` FROM `MonitorFolder` WHERE `shelfId` IS NOT NULL ORDER BY `id`"
            ).fetchall()
            folders_by_shelf: dict[str, list[str]] = {}
            for shelf_id, folder_id in links:
                folders_by_shelf.setdefault(str(shelf_id), []).append(str(folder_id))
            for shelf_id, folder_ids in folders_by_shelf.items():
                shelf_row = connection.execute(
                    "SELECT `rulesJson` FROM `Shelf` WHERE `id` = ?",
                    (shelf_id,),
                ).fetchone()
                if shelf_row is None:
                    continue
                try:
                    rules = json.loads(str(shelf_row[0] or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    rules = {}
                current_members = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT `workId` FROM `ShelfWork` WHERE `shelfId` = ?",
                        (shelf_id,),
                    ).fetchall()
                ] if _table_exists(connection, "ShelfWork") else []
                included_work_ids: list[str] = []
                for work_id in current_members:
                    source_match = None
                    placeholders = ", ".join("?" for _folder_id in folder_ids)
                    if _table_exists(connection, "LibraryEdition"):
                        source_match = connection.execute(
                            "SELECT 1 FROM `LibraryEdition` WHERE `workId` = ? "
                            f"AND `monitorFolderId` IN ({placeholders}) LIMIT 1",
                            (work_id, *folder_ids),
                        ).fetchone()
                    if source_match is None and _table_exists(connection, "LibraryWork"):
                        source_match = connection.execute(
                            "SELECT 1 FROM `LibraryWork` WHERE `id` = ? "
                            f"AND `monitorFolderId` IN ({placeholders}) LIMIT 1",
                            (work_id, *folder_ids),
                        ).fetchone()
                    if source_match is None:
                        included_work_ids.append(work_id)
                source_conditions = [
                    {"field": "monitorFolder", "operator": "equals", "value": folder_id}
                    for folder_id in folder_ids
                ]
                rules.update(
                    {
                        "combinator": "ANY",
                        "conditions": source_conditions,
                        "includedWorkIds": included_work_ids,
                    }
                )
                connection.execute(
                    "UPDATE `Shelf` SET `kind` = 'SMART', `rulesJson` = ?, `updatedAt` = CURRENT_TIMESTAMP WHERE `id` = ?",
                    (json.dumps(rules, ensure_ascii=False, separators=(",", ":")), shelf_id),
                )
            connection.execute("UPDATE `MonitorFolder` SET `shelfId` = NULL WHERE `shelfId` IS NOT NULL")

    connection.execute(
        "CREATE INDEX IF NOT EXISTS `UserMonitorFolderAccess_folder_idx` "
        "ON `UserMonitorFolderAccess`(`monitorFolderId`)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS `UserPreference_userId_idx` ON `UserPreference`(`userId`)"
    )
    if _table_exists(connection, "Shelf"):
        connection.execute(
            "CREATE INDEX IF NOT EXISTS `Shelf_ownerUserId_updatedAt_idx` "
            "ON `Shelf`(`ownerUserId`, `updatedAt`)"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS `ReaderBookmark_user_edition_idx` "
        "ON `ReaderBookmark`(`userId`, `editionId`)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS `ReaderBookmark_user_edition_fingerprint_bookmark_key` "
        "ON `ReaderBookmark`(`userId`, `editionId`, `contentFingerprint`, `bookmarkId`)"
    )
    if _table_exists(connection, "KindleSendTask"):
        connection.execute(
            "CREATE INDEX IF NOT EXISTS `KindleSendTask_userId_createdAt_idx` "
            "ON `KindleSendTask`(`userId`, `createdAt`)"
        )


def _migrate_schema_v14(connection: sqlite3.Connection) -> None:
    """Add realtime health runs and queue runtime/control state."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS `SystemHealthRun` (
            `id` TEXT NOT NULL, `actorUserId` TEXT NOT NULL,
            `status` TEXT NOT NULL DEFAULT 'running', `version` INTEGER NOT NULL DEFAULT 1,
            `snapshot` TEXT NOT NULL, `startedAt` TEXT NOT NULL, `finishedAt` TEXT NULL,
            `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, `updatedAt` TEXT NOT NULL,
            PRIMARY KEY (`id`)
        );
        CREATE TABLE IF NOT EXISTS `QueueRuntimeState` (
            `queueName` TEXT NOT NULL, `instanceId` TEXT NOT NULL, `status` TEXT NOT NULL,
            `pollIntervalSeconds` REAL NOT NULL, `startedAt` TEXT NOT NULL,
            `heartbeatAt` TEXT NOT NULL, `lastProcessedAt` TEXT NULL, `lastError` TEXT NULL,
            `updatedAt` TEXT NOT NULL, PRIMARY KEY (`queueName`)
        );
        CREATE TABLE IF NOT EXISTS `QueueControlOperation` (
            `id` TEXT NOT NULL, `queueName` TEXT NOT NULL, `action` TEXT NOT NULL,
            `status` TEXT NOT NULL, `actorUserId` TEXT NOT NULL, `messageCode` TEXT NULL,
            `requestedAt` TEXT NOT NULL, `startedAt` TEXT NULL, `finishedAt` TEXT NULL,
            `updatedAt` TEXT NOT NULL, PRIMARY KEY (`id`)
        );
        CREATE INDEX IF NOT EXISTS `QueueControlOperation_queue_status_idx`
            ON `QueueControlOperation`(`queueName`, `status`, `requestedAt`);
        """
    )


def _timestamp_trigger_expression(column: str) -> str:
    value = f"CAST(NEW.`{column}` AS TEXT)"
    numeric = f"TRIM({value}) NOT GLOB '*[^0-9]*' AND LENGTH(TRIM({value})) > 0"
    return (
        "CASE "
        f"WHEN NEW.`{column}` IS NULL THEN NULL "
        f"WHEN {numeric} THEN CASE WHEN LENGTH(TRIM({value})) <= 10 "
        f"THEN CAST(NEW.`{column}` AS INTEGER) * 1000 ELSE CAST(NEW.`{column}` AS INTEGER) END "
        f"ELSE COALESCE(CAST(ROUND((julianday(NEW.`{column}`) - 2440587.5) * 86400000) AS INTEGER), NEW.`{column}`) END"
    )


def _install_timestamp_triggers(connection: sqlite3.Connection) -> None:
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT `name` FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    for table in tables:
        columns = _timestamp_columns(connection, table)
        if not columns:
            continue
        assignments = ", ".join(
            f"`{column}` = {_timestamp_trigger_expression(column)}" for column in columns
        )
        column_list = ", ".join(f"`{column}`" for column in columns)
        connection.execute(f"DROP TRIGGER IF EXISTS `normalize_{table}_timestamps_insert`")
        connection.execute(f"DROP TRIGGER IF EXISTS `normalize_{table}_timestamps_update`")
        connection.execute(
            f"CREATE TRIGGER `normalize_{table}_timestamps_insert` AFTER INSERT ON `{table}` "
            f"BEGIN UPDATE `{table}` SET {assignments} WHERE rowid = NEW.rowid; END"
        )
        connection.execute(
            f"CREATE TRIGGER `normalize_{table}_timestamps_update` AFTER UPDATE OF {column_list} ON `{table}` "
            f"BEGIN UPDATE `{table}` SET {assignments} WHERE rowid = NEW.rowid; END"
        )


SchemaMigration = Callable[[sqlite3.Connection], None]
SCHEMA_MIGRATIONS: dict[int, SchemaMigration] = {
    1: _migrate_schema_v1,
    2: _migrate_schema_v2,
    3: _migrate_schema_v3,
    4: _migrate_schema_v4,
    5: _migrate_schema_v5,
    6: _migrate_schema_v6,
    7: _migrate_schema_v7,
    8: _migrate_schema_v8,
    9: _migrate_schema_v9,
    10: _migrate_schema_v10,
    11: _migrate_schema_v11,
    12: _migrate_schema_v12,
    13: _migrate_schema_v13,
    14: _migrate_schema_v14,
}

REQUIRED_COLUMNS_BY_VERSION: dict[int, dict[str, set[str]]] = {
    1: {
        "User": {"avatarPath"},
        "MonitorFolder": {"shelfId"},
    },
    2: {
        "ImportTask": {"errorCode", "retryable", "attempts", "leaseOwner", "leaseExpiresAt"},
    },
    3: {
        "ReaderBookPreference": {"schemaVersion", "preferences"},
    },
    4: {
        "LibraryEdition": {"mediaKind", "durationMs", "trackCount", "narrator", "abridged"},
        "LibraryVolume": {"durationMs"},
        "LibraryFile": {"durationMs", "codec", "bitrate", "sampleRate", "channels", "discNumber", "trackNumber"},
        "LibraryReadingUnit": {"startMs", "endMs", "durationMs"},
        "ImportTask": {"taskKind", "bundleKey", "assetCount", "processedAssetCount", "requestedTitle", "requestedAuthor"},
    },
    6: {
        "OrganizePolicy": {"scheduleMode", "intervalMinutes", "autoRunOnNew", "rulesJson", "nextRunAt"},
        "OrganizeRun": {"trigger", "scopeJson", "status", "queuedCount"},
        "OrganizeJob": {"runId", "trigger", "reasonCodes", "startedAt", "finishedAt"},
        "MetadataProviderExecution": {"jobId", "lookupTaskId", "providerId", "status"},
    },
    7: {
        "OrganizePolicy": {"overwriteTitleAuthor"},
    },
    8: {
        "MetadataProviderPipeline": {"workType", "providerId", "included", "enabled", "position"},
    },
    9: {
        "Shelf": {"kind", "rulesJson", "pinned"},
        "LibraryFacet": {"kind", "name", "normalizedName", "aliases"},
        "LibraryWorkFacet": {"facetId", "workId", "sortOrder"},
        "LibraryEditionFacet": {"facetId", "editionId"},
        "LibraryOperation": {"action", "status", "payloadJson", "inverseJson", "expiresAt", "undoneAt"},
    },
    10: {},
    11: {},
    12: {},
    13: {
        "User": {"status", "canManageSystem", "canViewManualImports", "authzVersion"},
        "Shelf": {"ownerUserId"},
        "UserMonitorFolderAccess": {"userId", "monitorFolderId"},
        "UserPreference": {"userId", "key", "value"},
        "ReaderBookmark": {"userId", "editionId", "contentFingerprint", "bookmarkId"},
        "KindleSendTask": {"userId"},
    },
}


def _has_application_tables(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone() is not None


def _schema_is_compatible_through(connection: sqlite3.Connection, version: int) -> bool:
    for required_version, tables in REQUIRED_COLUMNS_BY_VERSION.items():
        if required_version > version:
            continue
        for table, required_columns in tables.items():
            existing_columns = _table_columns(connection, table)
            if existing_columns and not required_columns.issubset(existing_columns):
                return False
    if version >= 3 and _table_exists(connection, "ReaderBookPreference"):
        schema_version = next(
            (
                row for row in connection.execute("PRAGMA table_info(`ReaderBookPreference`)").fetchall()
                if row[1] == "schemaVersion"
            ),
            None,
        )
        default = "" if schema_version is None else str(schema_version[4] or "")
        if default.strip().strip("()").strip("'\"") != "3":
            return False
    return True


def _backup_before_migration(connection: sqlite3.Connection, settings: Settings, target_version: int) -> None:
    backup_dir = settings.database_path.parent / "migrations"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"shuku-before-v{target_version}.sqlite3"
    if backup_path.exists():
        return
    backup_connection = sqlite3.connect(backup_path)
    try:
        connection.backup(backup_connection)
    finally:
        backup_connection.close()
    LOGGER.info("database migration backup created path=%s", backup_path)


def _run_schema_migrations(connection: sqlite3.Connection, settings: Settings | None) -> tuple[int, int]:
    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current_version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"数据库版本 {current_version} 高于当前应用支持的版本 {CURRENT_SCHEMA_VERSION}，请升级应用"
        )
    if not _has_application_tables(connection):
        return current_version, current_version
    needs_compatibility_repair = not _schema_is_compatible_through(connection, current_version)
    if current_version == CURRENT_SCHEMA_VERSION and not needs_compatibility_repair:
        return current_version, current_version
    if settings is not None:
        _backup_before_migration(connection, settings, CURRENT_SCHEMA_VERSION)
    original_version = current_version

    if needs_compatibility_repair:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for repair_version in range(1, current_version + 1):
                migration = SCHEMA_MIGRATIONS.get(repair_version)
                if migration is None:
                    raise RuntimeError(f"缺少数据库迁移脚本：v{repair_version}")
                migration(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            LOGGER.exception("database schema compatibility repair failed version=%s", current_version)
            raise
        LOGGER.info("database schema compatibility repaired version=%s", current_version)

    for target_version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        migration = SCHEMA_MIGRATIONS.get(target_version)
        if migration is None:
            raise RuntimeError(f"缺少数据库迁移脚本：v{target_version}")
        try:
            connection.execute("BEGIN IMMEDIATE")
            migration(connection)
            connection.execute(f"PRAGMA user_version = {target_version}")
            connection.commit()
        except Exception:
            connection.rollback()
            LOGGER.exception("database schema migration failed from=%s to=%s", target_version - 1, target_version)
            raise
        LOGGER.info("database schema migrated from=%s to=%s", target_version - 1, target_version)
    return original_version, CURRENT_SCHEMA_VERSION


def _apply_schema_once(engine: Engine, settings: Settings | None = None) -> None:
    ddl = resources.files("app.db").joinpath("schema.sql").read_text(encoding="utf-8")
    raw_connection = engine.raw_connection()
    try:
        driver_connection = raw_connection.driver_connection
        driver_connection.execute("PRAGMA journal_mode = WAL")
        _run_schema_migrations(driver_connection, settings)
        driver_connection.executescript(ddl)
        _install_timestamp_triggers(driver_connection)
        actual_version = int(driver_connection.execute("PRAGMA user_version").fetchone()[0])
        if actual_version != CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库迁移未达到目标版本：当前 {actual_version}，目标 {CURRENT_SCHEMA_VERSION}"
            )
        driver_connection.commit()
    finally:
        raw_connection.close()


def apply_schema(engine: Engine, settings: Settings | None = None) -> None:
    deadline = time.monotonic() + SCHEMA_LOCK_RETRY_SECONDS
    retry_delay = 0.25
    while True:
        try:
            _apply_schema_once(engine, settings)
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                raise
            remaining = max(0.0, deadline - time.monotonic())
            delay = min(retry_delay, remaining)
            LOGGER.warning(
                "database is busy during schema initialization; retrying in %.2fs",
                delay,
            )
            time.sleep(delay)
            retry_delay = min(retry_delay * 2, 2.0)


def seed_baseline_data(db: Session) -> None:
    now = datetime.now()
    seed_reader_progress_cursors(db)
    migrate_global_kindle_email_to_original_admin(db)
    migrate_library_reading_statuses(db)
    backfill_library_consumption_states(db)
    backfill_library_identity_keys(db)
    from app.services.library_management import backfill_library_facets

    facet_backfill_version = db.execute(
        text("SELECT `value` FROM `SystemSetting` WHERE `key` = :key"),
        {"key": LIBRARY_FACET_BACKFILL_SETTING},
    ).scalar()
    if str(facet_backfill_version or "") != LIBRARY_FACET_BACKFILL_VERSION:
        backfill_library_facets(db)
        db.execute(
            text(
                "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
                "VALUES (:key, :value, :now, :now) "
                "ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = excluded.`updatedAt`"
            ),
            {
                "key": LIBRARY_FACET_BACKFILL_SETTING,
                "value": LIBRARY_FACET_BACKFILL_VERSION,
                "now": now,
            },
        )
        db.commit()
    requeue_metadata_no_match_tasks_for_title_aliases(db)
    reconcile_metadata_lookup_organize_statuses(db)

    system_settings = {
        "systemName": DEFAULT_SYSTEM_NAME,
        "language": DEFAULT_LOCALE,
        "workDetail.tabOrder": json.dumps(["EBOOK", "COMIC", "AUDIOBOOK", "STRUCTURE"], ensure_ascii=False),
    }
    for key, value in system_settings.items():
        existing = db.execute(text("SELECT `key`, `value` FROM `SystemSetting` WHERE `key` = :key"), {"key": key}).mappings().first()
        if existing is None:
            db.execute(
                text("INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, :now, :now)"),
                {"key": key, "value": value, "now": now},
            )
        elif key == "systemName":
            existing_name = _decoded_setting_value(existing["value"])
            if isinstance(existing_name, str) and existing_name in LEGACY_DEFAULT_SYSTEM_NAMES:
                db.execute(
                    text("UPDATE `SystemSetting` SET `value` = :value, `updatedAt` = :now WHERE `key` = :key"),
                    {"key": key, "value": DEFAULT_SYSTEM_NAME, "now": now},
                )
    db.commit()
    from app.services.metadata_provider_registry import ensure_metadata_provider_sources

    ensure_metadata_provider_sources(db)
    LOGGER.info("database bootstrap complete")


def migrate_global_kindle_email_to_original_admin(db: Session) -> int:
    """Move the legacy global Kindle recipient to the original administrator once."""

    tables = {
        str(item)
        for item in db.execute(text("SELECT `name` FROM sqlite_master WHERE type = 'table'")).scalars()
    }
    if not {"User", "UserPreference", "SystemSetting"}.issubset(tables):
        return 0
    marker = db.execute(
        text("SELECT `value` FROM `SystemSetting` WHERE `key` = :key"),
        {"key": LEGACY_KINDLE_EMAIL_OWNER_SETTING},
    ).mappings().first()
    if marker is not None:
        return 0
    owner_id = db.execute(
        text(
            "SELECT `id` FROM `User` WHERE `role` = 'admin' "
            "ORDER BY `createdAt` ASC, `id` ASC LIMIT 1"
        )
    ).scalar()
    legacy_email = _decoded_setting_value(
        db.execute(
            text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'kindle.email'")
        ).scalar()
    )
    migrated = 0
    if owner_id and isinstance(legacy_email, str) and legacy_email.strip():
        db.execute(
            text(
                "INSERT INTO `UserPreference` (`userId`, `key`, `value`, `createdAt`, `updatedAt`) "
                "VALUES (:user_id, 'kindle.email', :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT (`userId`, `key`) DO NOTHING"
            ),
            {
                "user_id": str(owner_id),
                "value": json.dumps(legacy_email.strip().lower(), ensure_ascii=False),
            },
        )
        migrated = 1
    db.execute(
        text(
            "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
            "VALUES (:key, :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "key": LEGACY_KINDLE_EMAIL_OWNER_SETTING,
            "value": json.dumps(str(owner_id) if owner_id else None),
        },
    )
    db.commit()
    return migrated


def migrate_library_reading_statuses(db: Session) -> int:
    """Replace the legacy WANT state with the explicit UNREAD lifecycle state."""

    has_library_work = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'LibraryWork'")
    ).scalar() is not None
    if not has_library_work:
        return 0
    result = db.execute(text("UPDATE `LibraryWork` SET `status` = 'UNREAD' WHERE `status` = 'WANT'"))
    return int(result.rowcount or 0)


def backfill_library_consumption_states(db: Session) -> int:
    """Create per-user/media state for rows written before schema v4."""

    table_names = {
        str(item)
        for item in db.execute(text("SELECT `name` FROM sqlite_master WHERE type = 'table'")).scalars()
    }
    required = {"User", "LibraryWork", "LibraryEdition", "LibraryConsumptionState"}
    if not required.issubset(table_names):
        return 0
    users = [
        str(item)
        for item in db.execute(
            text("SELECT `id` FROM `User` ORDER BY `createdAt` ASC, `id` ASC")
        ).scalars()
    ]
    legacy_owner_value = db.execute(
        text("SELECT `value` FROM `SystemSetting` WHERE `key` = :key"),
        {"key": LEGACY_READING_STATUS_OWNER_SETTING},
    ).scalar() if "SystemSetting" in table_names else None
    legacy_owner_id = _decoded_setting_value(legacy_owner_value)
    legacy_owner_id = str(legacy_owner_id) if legacy_owner_id else None
    if legacy_owner_id is None and users and "SystemSetting" in table_names:
        legacy_owner_id = users[0]
        db.execute(
            text(
                "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
                "VALUES (:key, :value, :now, :now)"
            ),
            {
                "key": LEGACY_READING_STATUS_OWNER_SETTING,
                "value": json.dumps(legacy_owner_id),
                "now": datetime.now(),
            },
        )
    works = [dict(item) for item in db.execute(text("SELECT * FROM `LibraryWork`")).mappings()]
    editions = [dict(item) for item in db.execute(text("SELECT * FROM `LibraryEdition` WHERE COALESCE(`hidden`, 0) = 0")).mappings()]
    editions_by_work: dict[str, list[dict[str, object]]] = {}
    edition_kind: dict[str, str] = {}
    for edition in editions:
        fmt = str(edition.get("format") or "").upper()
        kind = str(edition.get("mediaKind") or "").upper()
        if kind not in {"EBOOK", "COMIC", "AUDIOBOOK"}:
            kind = "COMIC" if fmt == "COMIC" else "AUDIOBOOK" if fmt == "AUDIO" else "EBOOK"
        edition_kind[str(edition["id"])] = kind
        editions_by_work.setdefault(str(edition["workId"]), []).append(edition)
    latest_progress: dict[tuple[str, str, str], dict[str, object]] = {}
    if "LibraryReadingProgress" in table_names:
        for progress in db.execute(
            text("SELECT * FROM `LibraryReadingProgress` ORDER BY `updatedAt` DESC, `id` DESC")
        ).mappings():
            edition_id = str(progress.get("editionId") or "")
            kind = edition_kind.get(edition_id)
            if not kind:
                continue
            key = (str(progress["userId"]), str(progress["workId"]), kind)
            latest_progress.setdefault(key, dict(progress))
    existing = {
        (str(row["userId"]), str(row["workId"]), str(row["mediaKind"]))
        for row in db.execute(text("SELECT `userId`, `workId`, `mediaKind` FROM `LibraryConsumptionState`")).mappings()
    }
    now = datetime.now()
    inserted = 0
    for user_id in users:
        for work in works:
            work_id = str(work["id"])
            work_editions = editions_by_work.get(work_id, [])
            primary_id = str(work.get("primaryEditionId") or "")
            primary_kind = edition_kind.get(primary_id)
            if primary_kind is None:
                legacy_primary = next(
                    (item for item in work_editions if bool(item.get("primary"))),
                    work_editions[0] if work_editions else None,
                )
                if legacy_primary is not None:
                    primary_kind = edition_kind.get(str(legacy_primary["id"]))
            for media_kind in sorted({edition_kind[str(item["id"])] for item in work_editions}):
                key = (user_id, work_id, media_kind)
                if key in existing:
                    continue
                progress = latest_progress.get(key)
                if progress:
                    try:
                        percent = float(progress.get("percent") or 0)
                    except (TypeError, ValueError):
                        percent = 0
                    status = "FINISHED" if percent >= 100 else "READING" if percent > 0 else "UNREAD"
                    last_edition_id = str(progress.get("editionId") or "") or None
                    last_volume_id = str(progress.get("volumeId") or "") or None
                    location = _decoded_setting_value(progress.get("locationJson"))
                    extra = _decoded_setting_value(progress.get("extra"))
                    last_unit_id = (
                        str(location.get("chapterId"))
                        if isinstance(location, dict) and location.get("chapterId")
                        else str(extra.get("chapterId"))
                        if isinstance(extra, dict) and extra.get("chapterId")
                        else None
                    )
                else:
                    if user_id != legacy_owner_id:
                        continue
                    status = (
                        str(work.get("status") or "UNREAD").upper().replace("WANT", "UNREAD")
                        if media_kind == primary_kind
                        else "UNREAD"
                    )
                    primary = next(
                        (item for item in work_editions if edition_kind[str(item["id"])] == media_kind and bool(item.get("primary"))),
                        None,
                    ) or next((item for item in work_editions if edition_kind[str(item["id"])] == media_kind), None)
                    last_edition_id = str(primary["id"]) if primary else None
                    last_volume_id = None
                    last_unit_id = None
                identity = sha1(f"{user_id}\0{work_id}\0{media_kind}".encode("utf-8")).hexdigest()
                db.execute(
                    text(
                        "INSERT OR IGNORE INTO `LibraryConsumptionState` "
                        "(`id`, `userId`, `workId`, `mediaKind`, `status`, `lastEditionId`, `lastVolumeId`, `lastUnitId`, `createdAt`, `updatedAt`) "
                        "VALUES (:id, :user_id, :work_id, :media_kind, :status, :edition_id, :volume_id, :unit_id, :now, :now)"
                    ),
                    {
                        "id": f"consume_{identity}",
                        "user_id": user_id,
                        "work_id": work_id,
                        "media_kind": media_kind,
                        "status": status if status in {"UNREAD", "READING", "FINISHED"} else "UNREAD",
                        "edition_id": last_edition_id,
                        "volume_id": last_volume_id,
                        "unit_id": last_unit_id,
                        "now": now,
                    },
                )
                inserted += 1
    return inserted


def requeue_metadata_no_match_tasks_for_title_aliases(db: Session) -> int:
    """Retry legacy NO_MATCH tasks once after provider title aliases become matchable."""

    required_tables = {"SystemSetting", "MetadataLookupTask"}
    table_names = {
        str(item)
        for item in db.execute(text("SELECT `name` FROM sqlite_master WHERE type = 'table'")).scalars()
    }
    if not required_tables.issubset(table_names):
        return 0
    migrated = db.execute(
        text("SELECT `value` FROM `SystemSetting` WHERE `key` = :key"),
        {"key": METADATA_TITLE_MATCH_MIGRATION_SETTING},
    ).scalar()
    if str(_decoded_setting_value(migrated) or "") == METADATA_TITLE_MATCH_MIGRATION_VERSION:
        return 0

    now = datetime.now()
    result = db.execute(
        text(
            "UPDATE `MetadataLookupTask` SET `status` = 'PENDING', `attempts` = 0, "
            "`nextAttemptAt` = :now, `startedAt` = NULL, `finishedAt` = NULL, "
            "`errorSummary` = NULL, `updatedAt` = :now WHERE `status` = 'NO_MATCH'"
        ),
        {"now": now},
    )
    db.execute(
        text(
            "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
            "VALUES (:key, :value, :now, :now) "
            "ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = excluded.`updatedAt`"
        ),
        {
            "key": METADATA_TITLE_MATCH_MIGRATION_SETTING,
            "value": METADATA_TITLE_MATCH_MIGRATION_VERSION,
            "now": now,
        },
    )
    return int(result.rowcount or 0)


def reconcile_metadata_lookup_organize_statuses(db: Session) -> None:
    """Align existing organize records with the durable metadata lookup outcome."""

    required_tables = {"LibraryWork", "OrganizeJob", "MetadataLookupTask"}
    table_names = {
        str(item)
        for item in db.execute(text("SELECT `name` FROM sqlite_master WHERE type = 'table'")).scalars()
    }
    if not required_tables.issubset(table_names):
        return

    # A cancelled organize job is terminal. v10 cancelled older duplicate jobs,
    # but its first implementation only cancelled active lookup tasks. A
    # historical NO_PROVIDER/NO_MATCH/FAILED task could therefore reopen its
    # parent below and collide with the newer unresolved-job unique index.
    # Repair already-migrated databases before reading lookup state.
    now = datetime.now()
    db.execute(
        text(
            "UPDATE `MetadataLookupTask` SET `status` = 'CANCELLED', `nextAttemptAt` = NULL, "
            "`finishedAt` = COALESCE(`finishedAt`, :now), `updatedAt` = :now "
            "WHERE `organizeJobId` IN ("
            "SELECT `id` FROM `OrganizeJob` WHERE `status` = 'CANCELLED'"
            ") AND `status` != 'CANCELLED'"
        ),
        {"now": now},
    )

    tasks = [
        dict(item)
        for item in db.execute(
            text(
                "SELECT `id`, `workId`, `organizeJobId`, `status`, `errorSummary` "
                "FROM `MetadataLookupTask` WHERE `workId` IS NOT NULL"
            )
        ).mappings()
    ]
    if not tasks:
        return

    tasks_by_work: dict[str, list[dict[str, object]]] = {}
    for task in tasks:
        tasks_by_work.setdefault(str(task["workId"]), []).append(task)

    work_states: dict[str, str] = {}
    for work_id, work_tasks in tasks_by_work.items():
        work = db.execute(
            text("SELECT `organized`, `organizeStatus` FROM `LibraryWork` WHERE `id` = :id"),
            {"id": work_id},
        ).mappings().first()
        if not work:
            continue
        task_statuses = {str(task.get("status") or "") for task in work_tasks}
        already_organized = bool(work["organized"]) or work["organizeStatus"] == "APPLIED"
        if already_organized or "COMPLETED" in task_statuses:
            next_status = "APPLIED"
            organized = True
        elif task_statuses & {"PENDING", "RUNNING"}:
            next_status = "LOOKUP_PENDING"
            organized = False
        else:
            next_status = "REVIEWING"
            organized = False
        work_states[work_id] = next_status
        db.execute(
            text(
                "UPDATE `LibraryWork` SET `organized` = :organized, `organizeStatus` = :status, "
                "`updatedAt` = :now WHERE `id` = :id"
            ),
            {"organized": organized, "status": next_status, "now": now, "id": work_id},
        )

    for task in tasks:
        job_id = task.get("organizeJobId")
        work_status = work_states.get(str(task.get("workId") or ""))
        if not job_id or not work_status:
            continue
        task_status = str(task.get("status") or "")
        # Reconcile each queue record from its own lookup outcome. A work may
        # already be organized from embedded metadata or an earlier lookup;
        # that must not turn a later NO_MATCH/FAILED task into a success.
        if task_status == "COMPLETED":
            job_status = "APPLIED"
            summary = "元数据已匹配，整理完成"
            error_summary = None
        elif task_status == "PENDING":
            job_status = "LOOKUP_PENDING"
            summary = "等待元数据匹配"
            error_summary = None
        elif task_status == "RUNNING":
            job_status = "RUNNING"
            summary = "正在调用元数据插件"
            error_summary = None
        elif task_status == "CANCELLED":
            job_status = "CANCELLED"
            summary = "已取消"
            error_summary = None
        else:
            job_status = "FAILED"
            if task_status == "NO_MATCH":
                summary = "未找到唯一确定的精确匹配"
            elif task_status == "NO_PROVIDER":
                summary = "没有启用的适用元数据源"
            else:
                summary = "元数据匹配失败"
            error_summary = task.get("errorSummary") if task_status == "FAILED" else None
        db.execute(
            text(
                "UPDATE `OrganizeJob` SET `status` = :status, `summary` = :summary, "
                "`errorSummary` = :error, `updatedAt` = :now WHERE `id` = :id "
                "AND (`status` != 'CANCELLED' OR :status = 'CANCELLED')"
            ),
            {"status": job_status, "summary": summary, "error": error_summary, "now": now, "id": job_id},
        )


def backfill_library_identity_keys(db: Session) -> None:
    """Migrate work identity keys without silently merging existing records."""

    has_settings = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'SystemSetting'")
    ).scalar() is not None
    if has_settings:
        migrated = db.execute(
            text("SELECT `value` FROM `SystemSetting` WHERE `key` = :key"),
            {"key": IDENTITY_MIGRATION_SETTING},
        ).scalar()
        if str(_decoded_setting_value(migrated) or "") == IDENTITY_MIGRATION_VERSION:
            return

    works = [
        dict(item)
        for item in db.execute(
            text("SELECT `id`, `title`, `author`, `mergeKey`, `hidden`, `createdAt` FROM `LibraryWork` ORDER BY `createdAt` ASC, `id` ASC")
        ).mappings()
    ]
    groups: dict[str, list[dict[str, object]]] = {}
    for work in works:
        key = identity_merge_key(str(work.get("title") or ""), str(work.get("author") or UNKNOWN_AUTHOR))
        groups.setdefault(key, []).append(work)

    now = datetime.now()
    for merge_key, group in groups.items():
        visible = [work for work in group if not bool(work.get("hidden"))]
        canonical = (visible or group)[0]
        normalized_values = {
            "normalized_title": normalize_identity_part(canonical.get("title")),
            "normalized_author": normalize_identity_part(canonical.get("author") or UNKNOWN_AUTHOR),
            "merge_key": merge_key,
            "now": now,
            "canonical_id": canonical["id"],
        }

        holder = next((work for work in works if work.get("mergeKey") == merge_key and work["id"] != canonical["id"]), None)
        if holder:
            db.execute(
                text("UPDATE `LibraryWork` SET `mergeKey` = :legacy_key, `updatedAt` = :now WHERE `id` = :id"),
                {"legacy_key": f"legacy-identity:{holder['id']}:{merge_key}", "now": now, "id": holder["id"]},
            )
            holder["mergeKey"] = f"legacy-identity:{holder['id']}:{merge_key}"

        db.execute(
            text(
                """
                UPDATE `LibraryWork`
                SET `normalizedTitle` = :normalized_title,
                    `normalizedAuthor` = :normalized_author,
                    `mergeKey` = :merge_key,
                    `updatedAt` = :now
                WHERE `id` = :canonical_id
                """
            ),
            normalized_values,
        )
        canonical["mergeKey"] = merge_key

        for duplicate in group:
            if duplicate["id"] == canonical["id"]:
                continue
            db.execute(
                text(
                    """
                    UPDATE `LibraryWork`
                    SET `normalizedTitle` = :normalized_title,
                        `normalizedAuthor` = :normalized_author,
                        `organized` = 0,
                        `organizeStatus` = 'REVIEWING',
                        `updatedAt` = :now
                    WHERE `id` = :id
                    """
                ),
                {
                    "normalized_title": normalize_identity_part(duplicate.get("title")),
                    "normalized_author": normalize_identity_part(duplicate.get("author") or UNKNOWN_AUTHOR),
                    "now": now,
                    "id": duplicate["id"],
                },
            )
            job_key = f"{duplicate['id']}\0{canonical['id']}"
            job_id = f"identity_job_{sha1(job_key.encode('utf-8')).hexdigest()}"
            candidate_id = f"identity_duplicate_{sha1(job_key.encode('utf-8')).hexdigest()}"
            db.execute(
                text(
                    """
                    INSERT INTO `OrganizeJob`
                        (`id`, `workId`, `status`, `issueCodes`, `summary`, `createdAt`, `updatedAt`)
                    VALUES
                        (:id, :work_id, 'REVIEWING', :issues, :summary, :now, :now)
                    ON CONFLICT (`id`) DO UPDATE SET
                        `status` = 'REVIEWING', `summary` = excluded.`summary`, `updatedAt` = excluded.`updatedAt`
                    """
                ),
                {
                    "id": job_id,
                    "work_id": duplicate["id"],
                    "issues": json.dumps(["IDENTITY_CONFLICT"], ensure_ascii=False),
                    "summary": "标题与作者和现有作品重复，等待合并确认",
                    "now": now,
                },
            )
            db.execute(
                text(
                    """
                    INSERT INTO `DuplicateCandidate`
                        (`id`, `jobId`, `targetWorkId`, `reasons`, `confidence`, `suggestedAction`, `status`, `createdAt`, `updatedAt`)
                    VALUES
                        (:id, :job_id, :target_work_id, :reasons, 1.0, 'MERGE_AS_VERSION', 'PENDING', :now, :now)
                    ON CONFLICT (`id`) DO NOTHING
                    """
                ),
                {
                    "id": candidate_id,
                    "job_id": job_id,
                    "target_work_id": canonical["id"],
                    "reasons": json.dumps(["identity_conflict"], ensure_ascii=False),
                    "now": now,
                },
            )
    if has_settings:
        db.execute(
            text(
                """
                INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`)
                VALUES (:key, :value, :now, :now)
                ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = excluded.`updatedAt`
                """
            ),
            {"key": IDENTITY_MIGRATION_SETTING, "value": IDENTITY_MIGRATION_VERSION, "now": now},
        )


def seed_reader_progress_cursors(db: Session) -> None:
    """Backfill durable client watermarks from visible V2 progress projections.

    Older deployments stored the client sequence only on the mutable progress
    row. This recovers every watermark still present at upgrade time; future
    writes advance the independent cursor transactionally.
    """

    rows = db.execute(
        text(
            """
            SELECT `userId`, `workId`, `clientId`, MAX(`clientSequence`) AS `highWater`, MAX(`mutationId`) AS `lastMutationId`
            FROM `LibraryReadingProgress`
            WHERE `clientId` IS NOT NULL AND `clientSequence` IS NOT NULL
            GROUP BY `userId`, `workId`, `clientId`
            """
        )
    ).mappings().all()
    now = datetime.now()
    for item in rows:
        key = f"{item['userId']}\0{item['workId']}\0{item['clientId']}"
        params = {
            "id": f"cursor_{sha1(key.encode('utf-8')).hexdigest()}",
            "user_id": item["userId"],
            "work_id": item["workId"],
            "client_id": item["clientId"],
            "high_water": int(item["highWater"]),
            "last_mutation_id": item["lastMutationId"],
            "now": now,
        }
        db.execute(
            text(
                """
                INSERT INTO `ReaderProgressCursor`
                    (`id`, `userId`, `workId`, `clientId`, `highWater`, `lastMutationId`, `createdAt`, `updatedAt`)
                VALUES
                    (:id, :user_id, :work_id, :client_id, :high_water, :last_mutation_id, :now, :now)
                ON CONFLICT (`userId`, `workId`, `clientId`) DO NOTHING
                """
            ),
            params,
        )
        db.execute(
            text(
                """
                UPDATE `ReaderProgressCursor`
                SET `highWater` = :high_water,
                    `lastMutationId` = :last_mutation_id,
                    `updatedAt` = :now
                WHERE `userId` = :user_id
                  AND `workId` = :work_id
                  AND `clientId` = :client_id
                  AND `highWater` < :high_water
                """
            ),
            params,
        )


def main() -> None:
    from app.core.config import get_settings
    from app.db.session import engine

    bootstrap_database(engine, get_settings())


if __name__ == "__main__":
    main()
