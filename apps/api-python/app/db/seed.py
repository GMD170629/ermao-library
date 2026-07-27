from __future__ import annotations

from datetime import datetime
from hashlib import sha1
import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.i18n import DEFAULT_LOCALE
from app.services.book_identity import UNKNOWN_AUTHOR, identity_merge_key, normalize_identity_part

LOGGER = logging.getLogger(__name__)

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
