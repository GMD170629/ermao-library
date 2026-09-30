"""ORM persistence for SystemEvent storage and pruning."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from typing import cast as typing_cast
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    String,
    case,
    cast,
    column,
    delete,
    func,
    select,
    table,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.exception_diagnostics import record_exception
from app.core.sql_batches import sqlite_parameter_chunks
from app.models.common import db_timestamp
from app.models.settings import SystemEvent
from app.modules.system.domain.events import (
    DEFAULT_MAX_EVENT_BYTES,
    LAST_PRUNED_AT_SETTING,
    LOG_MAX_BYTES_SETTING,
    PreparedSystemEvent,
    normalize_event_level,
    parse_max_event_bytes,
    prepare_event_metadata,
    truncate_event_message,
    validate_log_max_bytes,
)
from app.modules.system.infrastructure import settings as setting_store

EVENT_PRUNE_DELETE_BATCH_SIZE = 1_000
_DBSTAT = table(
    "dbstat",
    column("name", String),
    column("pgsize", BigInteger),
    column("aggregate", BigInteger),
)


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
    """Return SQLite pages allocated to SystemEvent's table B-tree, excluding indexes."""
    value = db.scalar(
        select(_DBSTAT.c.pgsize).where(
            _DBSTAT.c.name == SystemEvent.__tablename__,
            _DBSTAT.c.aggregate == 1,
        )
    )
    return int(value or 0)


def configured_max_event_bytes(db: Session) -> int:
    try:
        return parse_max_event_bytes(
            setting_store.get_setting_raw(db, LOG_MAX_BYTES_SETTING)
        )
    except (TypeError, ValueError) as error:
        record_exception(
            logging.getLogger(__name__),
            "system.log_capacity_parse_failed",
            error,
            context={
                "stage": "parse_log_capacity",
                "resource_id": LOG_MAX_BYTES_SETTING,
            },
        )
        return DEFAULT_MAX_EVENT_BYTES


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
    if current_size_bytes < max_bytes:
        return PreparedSystemEventPrune(
            event_ids=(),
            max_bytes=max_bytes,
            current_size_bytes=current_size_bytes,
            last_pruned_setting=None,
        )

    event_count = int(db.scalar(select(func.count()).select_from(SystemEvent)) or 0)
    if event_count == 0:
        return PreparedSystemEventPrune(
            event_ids=(),
            max_bytes=max_bytes,
            current_size_bytes=current_size_bytes,
            last_pruned_setting=None,
        )

    ids_to_delete = db.scalars(
        select(SystemEvent.id).order_by(
            SystemEvent.created_at.asc(),
            SystemEvent.id.asc(),
        ).limit((event_count + 1) // 2)
    ).all()

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


def normalize_stored_event_metadata(value: object, *, event_id: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
        if not isinstance(parsed, dict):
            raise TypeError("SystemEvent metadata must be a JSON object")
        return parsed
    except (TypeError, ValueError) as error:
        diagnostic_id = record_exception(
            logging.getLogger(__name__),
            "system.event_metadata_parse_failed",
            error,
            context={"stage": "parse_event_metadata", "resource_id": event_id},
        )
        return {
            "diagnosticStatus": "HISTORICAL_INFORMATION_UNAVAILABLE",
            "metadataReadDiagnosticId": diagnostic_id,
        }


def get_system_event(db: Session, event_id: str) -> dict[str, Any] | None:
    row = db.get(SystemEvent, event_id)
    if row is None:
        return None
    return _event_dict(row)


def _event_dict(row: SystemEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "level": row.level,
        "source": row.source,
        "actorType": row.actor_type,
        "actorId": row.actor_id,
        "action": row.action,
        "targetType": row.target_type,
        "targetId": row.target_id,
        "message": row.message,
        "metadata": normalize_stored_event_metadata(row.metadata_json, event_id=row.id),
        "createdAt": row.created_at,
    }


def feedback_event_bundle(db: Session, event_id: str) -> list[dict[str, Any]]:
    """Return one event and a bounded set sharing its strongest correlation ID."""

    selected = get_system_event(db, event_id)
    if selected is None:
        return []
    metadata = selected["metadata"]
    correlation = next(
        (
            (key, value)
            for key in ("taskId", "operationId", "requestId")
            if isinstance(metadata.get(key), str)
            and 0 < len(value := metadata[key]) <= 191
        ),
        None,
    )
    if correlation is None:
        return [selected]
    key, value = correlation
    rows = db.scalars(
        select(SystemEvent)
        .where(SystemEvent.metadata_json[key].as_string() == value)
        .order_by(SystemEvent.created_at.asc(), SystemEvent.id.asc())
        .limit(20)
    ).all()
    found = [_event_dict(row) for row in rows]
    if all(event["id"] != event_id for event in found):
        found.insert(0, selected)
    return found[:20]


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


def system_event_search_filter(search: str) -> Any:
    """Search facts and explicit correlation IDs, never arbitrary stored payloads."""
    term = f"%{search.strip()}%"
    expression = (
        SystemEvent.id.like(term)
        | SystemEvent.message.like(term)
        | SystemEvent.action.like(term)
        | func.coalesce(SystemEvent.target_id, "").like(term)
    )
    for key in (
        "requestId",
        "taskId",
        "operationId",
        "planId",
        "uploadId",
        "nodeId",
        "parentDiagnosticId",
    ):
        expression |= func.coalesce(
            SystemEvent.metadata_json[key].as_string(), ""
        ).like(term)
    expression |= func.coalesce(
        SystemEvent.metadata_json["diagnostics"]["id"].as_string(), ""
    ).like(term)
    return expression


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
        )
        .group_by(SystemEvent.source, SystemEvent.level)
        .order_by(SystemEvent.source.asc(), SystemEvent.level.asc())
    ).all()
    source_counts: dict[str, int] = {}
    level_counts: dict[str, int] = {}
    for row in aggregate_rows:
        count = int(row.event_count or 0)
        source_counts[str(row.source)] = source_counts.get(str(row.source), 0) + count
        level_counts[str(row.level)] = level_counts.get(str(row.level), 0) + count

    filters: list[Any] = []
    if level:
        filters.append(SystemEvent.level == ("warning" if level == "warn" else level))
    if source:
        filters.append(SystemEvent.source == source)
    if target_type:
        filters.append(SystemEvent.target_type == target_type)
    if search:
        filters.append(system_event_search_filter(search))
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
                "metadata": normalize_stored_event_metadata(
                    row.metadata_json, event_id=row.id
                ),
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
        size_bytes=system_event_size_bytes(db),
    )


def clear_info_warning_events(db: Session) -> int:
    result = typing_cast(
        CursorResult[Any],
        db.execute(
            delete(SystemEvent).where(SystemEvent.level.in_(("info", "warning")))
        ),
    )
    return int(result.rowcount or 0)
