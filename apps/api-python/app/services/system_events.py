from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


DEFAULT_MAX_EVENT_BYTES = 5 * 1024 * 1024
MIN_MAX_EVENT_BYTES = 1 * 1024 * 1024
MAX_MAX_EVENT_BYTES = 100 * 1024 * 1024
MAX_EVENT_MESSAGE_CHARS = 4000
MAX_EVENT_METADATA_CHARS = 64 * 1024
LOG_MAX_BYTES_SETTING = "system.logs.maxBytes"
PROTECTED_ERROR_ACTIONS = {"deleted", "restored", "settings.updated", "backup.restored"}


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def system_event_size_bytes(db: Session) -> int:
    if not _has_table(db, "SystemEvent"):
        return 0
    value = db.execute(
        text(
            """
            SELECT COALESCE(SUM(
                LENGTH(CAST(COALESCE(`id`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`level`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`source`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`actorType`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`actorId`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`action`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`targetType`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`targetId`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`message`, '') AS BLOB)) +
                LENGTH(CAST(COALESCE(`metadata`, '') AS BLOB))
            ), 0)
            FROM `SystemEvent`
            """
        )
    ).scalar()
    return int(value or 0)


def configured_max_event_bytes(db: Session) -> int:
    if not _has_table(db, "SystemSetting"):
        return DEFAULT_MAX_EVENT_BYTES
    value = db.execute(
        text("SELECT `value` FROM `SystemSetting` WHERE `key` = :key"),
        {"key": LOG_MAX_BYTES_SETTING},
    ).scalar()
    try:
        parsed = json.loads(str(value)) if value is not None else DEFAULT_MAX_EVENT_BYTES
        size = int(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        size = DEFAULT_MAX_EVENT_BYTES
    return min(MAX_MAX_EVENT_BYTES, max(MIN_MAX_EVENT_BYTES, size))


def system_event_storage_view(db: Session) -> dict[str, Any]:
    max_bytes = configured_max_event_bytes(db)
    last_pruned = None
    if _has_table(db, "SystemSetting"):
        value = db.execute(
            text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'events.lastPrunedAt'")
        ).scalar()
        if value is not None:
            try:
                last_pruned = json.loads(str(value))
            except (TypeError, ValueError, json.JSONDecodeError):
                last_pruned = str(value)
    return {"sizeBytes": system_event_size_bytes(db), "maxBytes": max_bytes, "lastPrunedAt": last_pruned}


def set_max_event_bytes(db: Session, max_bytes: int) -> dict[str, Any]:
    size = int(max_bytes)
    if not MIN_MAX_EVENT_BYTES <= size <= MAX_MAX_EVENT_BYTES:
        raise ValueError("log-size-out-of-range")
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        text(
            "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
            "VALUES (:key, :value, :now, :now) "
            "ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = excluded.`updatedAt`"
        ),
        {"key": LOG_MAX_BYTES_SETTING, "value": json.dumps(size), "now": now},
    )
    db.commit()
    result = prune_system_events(db, size, commit=True)
    return {**result, "lastPrunedAt": system_event_storage_view(db).get("lastPrunedAt")}


def prune_system_events(
    db: Session,
    max_bytes: int | None = None,
    *,
    commit: bool = False,
) -> dict[str, int]:
    max_bytes = configured_max_event_bytes(db) if max_bytes is None else int(max_bytes)
    if not _has_table(db, "SystemEvent"):
        return {"deleted": 0, "sizeBytes": 0, "maxBytes": max_bytes}

    deleted = 0
    protected_actions = ", ".join(f":protected_{index}" for index, _ in enumerate(PROTECTED_ERROR_ACTIONS))
    protected_params = {f"protected_{index}": action for index, action in enumerate(sorted(PROTECTED_ERROR_ACTIONS))}
    for level in ("info", "warning", "warn", "error"):
        while system_event_size_bytes(db) > max_bytes:
            if level == "error":
                rows = db.execute(
                    text(
                        f"""
                        SELECT `id`
                        FROM `SystemEvent`
                        WHERE `level` = :level AND `action` NOT IN ({protected_actions})
                        ORDER BY `createdAt` ASC
                        LIMIT 100
                        """
                    ),
                    {"level": level, **protected_params},
                ).mappings()
            else:
                rows = db.execute(
                    text(
                        """
                        SELECT `id`
                        FROM `SystemEvent`
                        WHERE `level` = :level
                        ORDER BY `createdAt` ASC
                        LIMIT 100
                        """
                    ),
                    {"level": level},
                ).mappings()
            ids = [str(row["id"]) for row in rows]
            if not ids:
                break
            params = {f"id_{index}": event_id for index, event_id in enumerate(ids)}
            placeholders = ", ".join(f":id_{index}" for index in range(len(ids)))
            result = db.execute(text(f"DELETE FROM `SystemEvent` WHERE `id` IN ({placeholders})"), params)
            deleted += int(result.rowcount or 0)

    # Protected audit events are retained preferentially, but the configured
    # value is a hard capacity limit rather than an unbounded retention hint.
    while system_event_size_bytes(db) > max_bytes:
        ids = [
            str(row["id"])
            for row in db.execute(
                text("SELECT `id` FROM `SystemEvent` ORDER BY `createdAt` ASC, `id` ASC LIMIT 100")
            ).mappings()
        ]
        if not ids:
            break
        params = {f"id_{index}": event_id for index, event_id in enumerate(ids)}
        placeholders = ", ".join(f":id_{index}" for index in range(len(ids)))
        result = db.execute(text(f"DELETE FROM `SystemEvent` WHERE `id` IN ({placeholders})"), params)
        deleted += int(result.rowcount or 0)

    size_bytes = system_event_size_bytes(db)
    if deleted and _has_table(db, "SystemSetting"):
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            text(
                """
                INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`)
                VALUES ('events.lastPrunedAt', :value, :now, :now)
                ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = excluded.`updatedAt`
                """
            ),
            {"value": now, "now": now},
        )
    if commit:
        db.commit()
    return {"deleted": deleted, "sizeBytes": size_bytes, "maxBytes": max_bytes}


def record_system_event(
    db: Session,
    *,
    source: str,
    action: str,
    message: str,
    level: str = "info",
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
    prune: bool = False,
) -> str | None:
    if not _has_table(db, "SystemEvent"):
        return None

    safe_level = "warning" if level == "warn" else level
    if safe_level not in {"info", "warning", "error"}:
        safe_level = "info"
    event_id = f"py_{uuid4().hex}"
    safe_message = str(message)[:MAX_EVENT_MESSAGE_CHARS]
    metadata_text = json.dumps(metadata or {}, ensure_ascii=False, default=str)
    if len(metadata_text) > MAX_EVENT_METADATA_CHARS:
        metadata_text = json.dumps(
            {"truncated": True, "preview": metadata_text[: MAX_EVENT_METADATA_CHARS - 80]},
            ensure_ascii=False,
        )
    db.execute(
        text(
            """
            INSERT INTO `SystemEvent`
                (`id`, `level`, `source`, `actorType`, `actorId`, `action`, `targetType`, `targetId`, `message`, `metadata`, `createdAt`)
            VALUES
                (:id, :level, :source, :actor_type, :actor_id, :action, :target_type, :target_id, :message, :metadata, :created_at)
            """
        ),
        {
            "id": event_id,
            "level": safe_level,
            "source": source,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "message": safe_message,
            "metadata": metadata_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    # Enforce the hard limit whenever this write becomes visible. Callers that
    # batch several events request pruning on their final write before commit.
    if commit or prune:
        prune_system_events(db)
    if commit:
        db.commit()
    return event_id
