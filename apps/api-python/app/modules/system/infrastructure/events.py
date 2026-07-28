"""ORM persistence for SystemEvent storage and pruning."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.settings import SystemEvent
from app.modules.system.domain.events import (
    LAST_PRUNED_AT_SETTING,
    LOG_MAX_BYTES_SETTING,
    PRUNE_LEVEL_ORDER,
    PROTECTED_ERROR_ACTIONS,
    normalize_event_level,
    parse_max_event_bytes,
    prepare_event_metadata,
    truncate_event_message,
    validate_log_max_bytes,
)
from app.modules.system.infrastructure import settings as setting_store


def _column_length(column: Any) -> Any:
    return func.length(func.coalesce(cast(column, String), ""))


def system_event_size_bytes(db: Session) -> int:
    value = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    _column_length(SystemEvent.id)
                    + _column_length(SystemEvent.level)
                    + _column_length(SystemEvent.source)
                    + _column_length(SystemEvent.actor_type)
                    + _column_length(SystemEvent.actor_id)
                    + _column_length(SystemEvent.action)
                    + _column_length(SystemEvent.target_type)
                    + _column_length(SystemEvent.target_id)
                    + _column_length(SystemEvent.message)
                    + _column_length(SystemEvent.metadata_json)
                ),
                0,
            )
        )
    )
    return int(value or 0)


def configured_max_event_bytes(db: Session) -> int:
    return parse_max_event_bytes(setting_store.get_setting_raw(db, LOG_MAX_BYTES_SETTING))


def system_event_storage_view(db: Session) -> dict[str, Any]:
    max_bytes = configured_max_event_bytes(db)
    last_pruned = setting_store.get_setting(db, LAST_PRUNED_AT_SETTING)
    return {"sizeBytes": system_event_size_bytes(db), "maxBytes": max_bytes, "lastPrunedAt": last_pruned}


def set_max_event_bytes(db: Session, max_bytes: int) -> dict[str, Any]:
    size = validate_log_max_bytes(max_bytes)
    setting_store.upsert_setting(db, LOG_MAX_BYTES_SETTING, size)
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
    deleted = 0
    for level in PRUNE_LEVEL_ORDER:
        while system_event_size_bytes(db) > max_bytes:
            statement = select(SystemEvent.id).where(SystemEvent.level == level).order_by(SystemEvent.created_at.asc()).limit(100)
            if level == "error":
                statement = statement.where(SystemEvent.action.notin_(sorted(PROTECTED_ERROR_ACTIONS)))
            ids = list(db.scalars(statement).all())
            if not ids:
                break
            result = db.execute(delete(SystemEvent).where(SystemEvent.id.in_(ids)))
            deleted += int(result.rowcount or 0)

    while system_event_size_bytes(db) > max_bytes:
        ids = list(
            db.scalars(
                select(SystemEvent.id).order_by(SystemEvent.created_at.asc(), SystemEvent.id.asc()).limit(100)
            ).all()
        )
        if not ids:
            break
        result = db.execute(delete(SystemEvent).where(SystemEvent.id.in_(ids)))
        deleted += int(result.rowcount or 0)

    size_bytes = system_event_size_bytes(db)
    if deleted:
        setting_store.upsert_setting(db, LAST_PRUNED_AT_SETTING, datetime.now(timezone.utc).isoformat())
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
    event_id = f"py_{uuid4().hex}"
    db.add(
        SystemEvent(
            id=event_id,
            level=normalize_event_level(level),
            source=source,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            message=truncate_event_message(message),
            metadata_json=prepare_event_metadata(metadata),
            created_at=db_timestamp(),
        )
    )
    db.flush()
    if commit or prune:
        prune_system_events(db)
    if commit:
        db.commit()
    return event_id
