from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


DEFAULT_MAX_EVENT_BYTES = 5 * 1024 * 1024
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
                LENGTH(COALESCE(`id`, '')) +
                LENGTH(COALESCE(`level`, '')) +
                LENGTH(COALESCE(`source`, '')) +
                LENGTH(COALESCE(`actorType`, '')) +
                LENGTH(COALESCE(`actorId`, '')) +
                LENGTH(COALESCE(`action`, '')) +
                LENGTH(COALESCE(`targetType`, '')) +
                LENGTH(COALESCE(`targetId`, '')) +
                LENGTH(COALESCE(`message`, '')) +
                LENGTH(COALESCE(`metadata`, ''))
            ), 0)
            FROM `SystemEvent`
            """
        )
    ).scalar()
    return int(value or 0)


def prune_system_events(
    db: Session,
    max_bytes: int = DEFAULT_MAX_EVENT_BYTES,
    *,
    commit: bool = False,
) -> dict[str, int]:
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
            "message": message,
            "metadata": json.dumps(metadata or {}, ensure_ascii=False, default=str),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if prune:
        prune_system_events(db)
    if commit:
        db.commit()
    return event_id
