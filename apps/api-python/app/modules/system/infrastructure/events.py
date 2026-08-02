"""ORM persistence for SystemEvent storage and pruning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import String, case, cast, delete, func, select
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.settings import SystemEvent
from app.modules.system.domain.events import (
    LAST_PRUNED_AT_SETTING,
    LOG_MAX_BYTES_SETTING,
    PROTECTED_ERROR_ACTIONS,
    PRUNE_LEVEL_ORDER,
    normalize_event_level,
    parse_max_event_bytes,
    prepare_event_metadata,
    truncate_event_message,
    validate_log_max_bytes,
)
from app.modules.system.infrastructure import settings as setting_store

EVENT_PRUNE_DELETE_BATCH_SIZE = 1_000


def _column_length(column: Any) -> Any:
    return func.length(func.coalesce(cast(column, String), ""))


def _event_size_expression() -> Any:
    return (
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
    )


def system_event_size_bytes(db: Session) -> int:
    value = db.scalar(select(func.coalesce(func.sum(_event_size_expression()), 0)))
    return int(value or 0)


def configured_max_event_bytes(db: Session) -> int:
    return parse_max_event_bytes(
        setting_store.get_setting_raw(db, LOG_MAX_BYTES_SETTING)
    )


def system_event_storage_view(db: Session) -> dict[str, Any]:
    max_bytes = configured_max_event_bytes(db)
    last_pruned = setting_store.get_setting(db, LAST_PRUNED_AT_SETTING)
    return {
        "sizeBytes": system_event_size_bytes(db),
        "maxBytes": max_bytes,
        "lastPrunedAt": last_pruned,
    }


def set_max_event_bytes(db: Session, max_bytes: int) -> dict[str, Any]:
    size = validate_log_max_bytes(max_bytes)
    setting_store.upsert_setting(db, LOG_MAX_BYTES_SETTING, size)
    return system_event_storage_view(db)


def prune_system_events(
    db: Session,
    max_bytes: int | None = None,
) -> dict[str, int]:
    max_bytes = configured_max_event_bytes(db) if max_bytes is None else int(max_bytes)
    current_size_bytes = system_event_size_bytes(db)
    if current_size_bytes <= max_bytes:
        return {
            "deleted": 0,
            "sizeBytes": current_size_bytes,
            "maxBytes": max_bytes,
        }

    target_size_bytes = max_bytes // 2
    bytes_to_reclaim = current_size_bytes - target_size_bytes
    retention_priority = case(
        (SystemEvent.level == PRUNE_LEVEL_ORDER[0], 0),
        (SystemEvent.level.in_(PRUNE_LEVEL_ORDER[1:3]), 1),
        (
            (
                (SystemEvent.level == "error")
                & SystemEvent.action.notin_(sorted(PROTECTED_ERROR_ACTIONS))
            ),
            2,
        ),
        else_=3,
    )
    candidates = db.execute(
        select(
            SystemEvent.id,
            _event_size_expression().label("size_bytes"),
        ).order_by(
            retention_priority.asc(),
            SystemEvent.created_at.asc(),
            SystemEvent.id.asc(),
        )
    ).all()
    reclaimed_bytes = 0
    ids_to_delete: list[str] = []
    for event_id, size_bytes in candidates:
        ids_to_delete.append(str(event_id))
        reclaimed_bytes += int(size_bytes or 0)
        if reclaimed_bytes >= bytes_to_reclaim:
            break

    deleted = 0
    for start in range(0, len(ids_to_delete), EVENT_PRUNE_DELETE_BATCH_SIZE):
        batch_ids = ids_to_delete[start : start + EVENT_PRUNE_DELETE_BATCH_SIZE]
        result = db.execute(delete(SystemEvent).where(SystemEvent.id.in_(batch_ids)))
        deleted += int(result.rowcount or 0)

    size_bytes = system_event_size_bytes(db)
    if deleted:
        setting_store.upsert_setting(
            db, LAST_PRUNED_AT_SETTING, datetime.now(UTC).isoformat()
        )
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
) -> str | None:
    event_id = f"py_{uuid4().hex}"
    created_at = db_timestamp()
    latest_created_at = db.scalar(
        select(SystemEvent.created_at).order_by(SystemEvent.created_at.desc()).limit(1)
    )
    if latest_created_at is not None and created_at <= latest_created_at:
        created_at = latest_created_at + timedelta(milliseconds=1)
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
            created_at=created_at,
        )
    )
    db.flush()
    return event_id


def list_event_source_facets(db: Session) -> list[dict[str, Any]]:
    return [
        {"source": row.source, "count": int(row.count or 0)}
        for row in db.execute(
            select(SystemEvent.source, func.count().label("count"))
            .group_by(SystemEvent.source)
            .order_by(SystemEvent.source.asc())
        ).all()
    ]


def list_event_level_facets(db: Session) -> list[dict[str, Any]]:
    return [
        {"level": row.level, "count": int(row.count or 0)}
        for row in db.execute(
            select(SystemEvent.level, func.count().label("count"))
            .group_by(SystemEvent.level)
            .order_by(SystemEvent.level.asc())
        ).all()
    ]
