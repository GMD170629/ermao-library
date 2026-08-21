"""ORM persistence for SystemEvent storage and pruning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from typing import cast as typing_cast
from uuid import uuid4

from sqlalchemy import BigInteger, String, case, cast, delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.common import db_timestamp
from app.models.settings import SystemEvent
from app.modules.system.domain.events import (
    LAST_PRUNED_AT_SETTING,
    LOG_MAX_BYTES_SETTING,
    PROTECTED_ERROR_ACTIONS,
    PRUNE_LEVEL_ORDER,
    PreparedSystemEvent,
    normalize_event_level,
    parse_max_event_bytes,
    prepare_event_metadata,
    truncate_event_message,
    validate_log_max_bytes,
)
from app.modules.system.infrastructure import settings as setting_store

EVENT_PRUNE_DELETE_BATCH_SIZE = 1_000


@dataclass(frozen=True, slots=True)
class SystemEventPageSnapshot:
    events: list[dict[str, Any]]
    total: int
    page: int
    sources: list[dict[str, Any]]
    levels: list[dict[str, Any]]
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PreparedSystemEventPrune:
    event_ids: tuple[str, ...]
    max_bytes: int
    current_size_bytes: int
    last_pruned_setting: setting_store.PreparedSettingsWrite | None


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


def _event_created_at_ms_expression() -> Any:
    """Normalize legacy textual timestamps inside the database date filter."""

    return case(
        (
            func.typeof(SystemEvent.created_at) == "text",
            cast(func.strftime("%s", SystemEvent.created_at), BigInteger) * 1000,
        ),
        else_=cast(SystemEvent.created_at, BigInteger),
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
    prepared = prepare_system_event_prune(db, max_bytes)
    return write_prepared_system_event_prune(db, prepared)


def prepare_system_event_prune(
    db: Session,
    max_bytes: int | None = None,
) -> PreparedSystemEventPrune:
    max_bytes = configured_max_event_bytes(db) if max_bytes is None else int(max_bytes)
    current_size_bytes = system_event_size_bytes(db)
    if current_size_bytes <= max_bytes:
        return PreparedSystemEventPrune(
            event_ids=(),
            max_bytes=max_bytes,
            current_size_bytes=current_size_bytes,
            last_pruned_setting=None,
        )

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

    last_pruned_setting = setting_store.prepare_settings_write(
        {LAST_PRUNED_AT_SETTING: datetime.now(UTC).isoformat()}
    )
    return PreparedSystemEventPrune(
        event_ids=tuple(ids_to_delete),
        max_bytes=max_bytes,
        current_size_bytes=current_size_bytes,
        last_pruned_setting=last_pruned_setting,
    )


def write_prepared_system_event_prune(
    db: Session,
    prepared: PreparedSystemEventPrune,
) -> dict[str, int]:
    if not prepared.event_ids:
        return {
            "deleted": 0,
            "sizeBytes": prepared.current_size_bytes,
            "maxBytes": prepared.max_bytes,
        }

    deleted = 0
    for start in range(
        0,
        len(prepared.event_ids),
        EVENT_PRUNE_DELETE_BATCH_SIZE,
    ):
        batch_ids = prepared.event_ids[start : start + EVENT_PRUNE_DELETE_BATCH_SIZE]
        result = typing_cast(
            CursorResult[Any],
            db.execute(delete(SystemEvent).where(SystemEvent.id.in_(batch_ids))),
        )
        deleted += int(result.rowcount or 0)

    size_bytes = system_event_size_bytes(db)
    if deleted and prepared.last_pruned_setting is not None:
        setting_store.write_prepared_settings(db, prepared.last_pruned_setting)
    return {
        "deleted": deleted,
        "sizeBytes": size_bytes,
        "maxBytes": prepared.max_bytes,
    }


def prepare_system_event(
    *,
    event_id: str | None = None,
    created_at: datetime | None = None,
    source: str,
    action: str,
    message: str,
    level: str = "info",
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PreparedSystemEvent:
    return PreparedSystemEvent(
        id=event_id or f"py_{uuid4().hex}",
        level=normalize_event_level(level),
        source=source,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        message=truncate_event_message(message),
        metadata=prepare_event_metadata(metadata),
        created_at=created_at or db_timestamp(),
    )


def write_prepared_system_events(
    db: Session,
    events: list[PreparedSystemEvent] | tuple[PreparedSystemEvent, ...],
) -> list[str]:
    if not events:
        return []
    rows = [
        {
            "id": event.id,
            "level": event.level,
            "source": event.source,
            "actor_type": event.actor_type,
            "actor_id": event.actor_id,
            "action": event.action,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "message": event.message,
            "metadata_json": event.metadata,
            "created_at": event.created_at,
        }
        for event in events
    ]
    for chunk in sqlite_parameter_chunks(rows, parameters_per_row=11):
        db.execute(sqlite_insert(SystemEvent), list(chunk))
    return [event.id for event in events]


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
) -> str:
    prepared = prepare_system_event(
        source=source,
        action=action,
        message=message,
        level=level,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
    write_prepared_system_events(db, [prepared])
    return prepared.id


def list_event_source_facets(db: Session) -> list[dict[str, Any]]:
    return [
        {"source": row._mapping["source"], "count": int(row._mapping["count"] or 0)}
        for row in db.execute(
            select(SystemEvent.source, func.count().label("count"))
            .group_by(SystemEvent.source)
            .order_by(SystemEvent.source.asc())
        ).all()
    ]


def list_event_level_facets(db: Session) -> list[dict[str, Any]]:
    return [
        {"level": row._mapping["level"], "count": int(row._mapping["count"] or 0)}
        for row in db.execute(
            select(SystemEvent.level, func.count().label("count"))
            .group_by(SystemEvent.level)
            .order_by(SystemEvent.level.asc())
        ).all()
    ]


def list_system_events_page(
    db: Session,
    *,
    page: int,
    page_size: int,
    level: str | None = None,
    source: str | None = None,
    target_type: str | None = None,
    search: str | None = None,
    date_from_ms: int | None = None,
    date_to_ms: int | None = None,
) -> SystemEventPageSnapshot:
    aggregate_rows = db.execute(
        select(
            SystemEvent.source,
            SystemEvent.level,
            func.count().label("event_count"),
            func.coalesce(func.sum(_event_size_expression()), 0).label("size_bytes"),
        )
        .group_by(SystemEvent.source, SystemEvent.level)
        .order_by(SystemEvent.source.asc(), SystemEvent.level.asc())
    ).all()
    source_counts: dict[str, int] = {}
    level_counts: dict[str, int] = {}
    size_bytes = 0
    for row in aggregate_rows:
        count = int(row.event_count or 0)
        source_counts[str(row.source)] = source_counts.get(str(row.source), 0) + count
        level_counts[str(row.level)] = level_counts.get(str(row.level), 0) + count
        size_bytes += int(row.size_bytes or 0)

    filters: list[Any] = []
    if level:
        filters.append(SystemEvent.level == ("warning" if level == "warn" else level))
    if source:
        filters.append(SystemEvent.source == source)
    if target_type:
        filters.append(SystemEvent.target_type == target_type)
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            SystemEvent.message.like(term)
            | SystemEvent.action.like(term)
            | func.coalesce(SystemEvent.target_id, "").like(term)
        )
    created_at_ms = _event_created_at_ms_expression()
    if date_from_ms is not None:
        filters.append(created_at_ms >= date_from_ms)
    if date_to_ms is not None:
        filters.append(created_at_ms < date_to_ms)

    total = (
        int(
            db.scalar(select(func.count()).select_from(SystemEvent).where(*filters))
            or 0
        )
        if filters
        else sum(source_counts.values())
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    clamped_page = min(max(1, page), total_pages)
    rows = db.scalars(
        select(SystemEvent)
        .where(*filters)
        .order_by(SystemEvent.created_at.desc(), SystemEvent.id.desc())
        .limit(page_size)
        .offset((clamped_page - 1) * page_size)
    ).all()
    return SystemEventPageSnapshot(
        events=[
            {
                "id": row.id,
                "level": row.level,
                "source": row.source,
                "actorType": row.actor_type,
                "actorId": row.actor_id,
                "action": row.action,
                "targetType": row.target_type,
                "targetId": row.target_id,
                "message": row.message,
                "metadata": row.metadata_json,
                "createdAt": row.created_at,
            }
            for row in rows
        ],
        total=total,
        page=clamped_page,
        sources=[
            {"source": source_name, "count": count}
            for source_name, count in source_counts.items()
        ],
        levels=[
            {"level": level_name, "count": count}
            for level_name, count in sorted(level_counts.items())
        ],
        size_bytes=size_bytes,
    )


def clear_info_warning_events(db: Session) -> int:
    result = typing_cast(
        CursorResult[Any],
        db.execute(
            delete(SystemEvent).where(SystemEvent.level.in_(("info", "warning")))
        ),
    )
    return int(result.rowcount or 0)
