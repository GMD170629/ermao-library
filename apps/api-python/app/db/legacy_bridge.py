from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sqlite3
from typing import Callable

from app.core.config import Settings
from app.core.i18n import DEFAULT_LOCALE
from app.core.time import to_timestamp_ms

LOGGER = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 14

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


def _legacy_timestamp_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info(`{table}`)").fetchall()
        if str(row[1]).endswith("At") or str(row[1]).endswith("_at")
    ]


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
        columns = _legacy_timestamp_columns(connection, table)
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


def upgrade_user_version_to_current(connection: sqlite3.Connection, settings: Settings | None) -> tuple[int, int]:
    """Run frozen user_version migrations up to CURRENT_SCHEMA_VERSION (14). Returns (from, to)."""
    return _run_schema_migrations(connection, settings)
