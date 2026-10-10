"""System event file persistence, committed audit events, and streaming queries."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import event as orm_event
from sqlalchemy.orm import Session

from app.core.time import timestamp_ms_to_iso, to_timestamp_ms
from app.models.common import db_timestamp
from app.modules.system.domain.events import (
    PreparedSystemEvent,
    normalize_event_level,
    prepare_event_message,
    prepare_event_metadata,
)
from app.modules.system.infrastructure.log_files import (
    append_log_event,
    clear_log_files,
    log_settings,
    log_size_bytes,
    prune_log_files,
    read_log_events,
    save_log_settings,
)


@dataclass(frozen=True, slots=True)
class SystemEventPageSnapshot:
    events: list[dict[str, Any]]
    total: int
    page: int
    sources: list[dict[str, Any]]
    levels: list[dict[str, Any]]
    size_bytes: int


def system_event_size_bytes(db: Session) -> int:
    return log_size_bytes()


def configured_retention_days(db: Session) -> int:
    return int(log_settings()["retentionDays"])


def system_event_storage_view(db: Session) -> dict[str, Any]:
    return {"sizeBytes": log_size_bytes(), **log_settings()}


def set_retention_days(db: Session, days: int) -> dict[str, Any]:
    save_log_settings(days, log_settings()["minimumLevel"])
    return system_event_storage_view(db)


def prune_system_events(db: Session, retention_days: int | None = None) -> dict[str, int]:
    if retention_days is not None:
        deleted = save_log_settings(retention_days, log_settings()["minimumLevel"])
    else:
        deleted = prune_log_files()
    return {"deleted": deleted, "sizeBytes": log_size_bytes(), "retentionDays": configured_retention_days(db)}


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
    metadata: dict[str, Any] | None = None,
) -> PreparedSystemEvent:
    return PreparedSystemEvent(
        id=event_id or f"py_{uuid4().hex}",
        level=normalize_event_level(level),
        source=source,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        message=prepare_event_message(message),
        metadata=prepare_event_metadata(metadata),
        created_at=created_at or db_timestamp(),
    )


def event_record(event: PreparedSystemEvent) -> dict[str, Any]:
    return {
        "id": event.id, "level": event.level, "source": event.source,
        "actorType": event.actor_type, "actorId": event.actor_id,
        "action": event.action, "message": event.message,
        "metadata": event.metadata, "createdAt": timestamp_ms_to_iso(event.created_at),
    }


def write_prepared_system_events(db: Session, events: list[PreparedSystemEvent] | tuple[PreparedSystemEvent, ...]) -> list[str]:
    # Keep audit success tied to the owning transaction. Never INSERT log rows.
    if not events:
        return []
    transaction = db.get_nested_transaction() or db.get_transaction() or db.begin()
    db.info.setdefault("file_log_events", {}).setdefault(transaction, []).extend(events)
    return [event.id for event in events]


@orm_event.listens_for(Session, "after_commit")
def _publish_committed_events(db: Session) -> None:
    transaction = db.get_nested_transaction() or db.get_transaction()
    queues = db.info.get("file_log_events", {})
    events = queues.pop(transaction, [])
    if transaction is not None and transaction.parent is not None:
        queues.setdefault(transaction.parent, []).extend(events)
    else:
        for event in events:
            append_log_event(event_record(event))


@orm_event.listens_for(Session, "after_transaction_end")
def _discard_uncommitted_events(db: Session, transaction: Any) -> None:
    db.info.get("file_log_events", {}).pop(transaction, None)


def record_system_event(
    db: Session,
    *,
    source: str,
    action: str,
    message: str,
    level: str = "info",
    actor_type: str = "system",
    actor_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    prepared = prepare_system_event(
        source=source,
        action=action,
        message=message,
        level=level,
        actor_type=actor_type,
        actor_id=actor_id,
        metadata=metadata,
    )
    write_prepared_system_events(db, [prepared])
    return prepared.id


def get_system_event(db: Session, event_id: str) -> dict[str, Any] | None:
    return next((event for event in read_log_events() if event.get("id") == event_id), None)


def feedback_event_bundle(db: Session, event_id: str) -> list[dict[str, Any]]:
    selected = get_system_event(db, event_id)
    return [selected] if selected is not None else []


def list_event_source_facets(db: Session) -> list[dict[str, Any]]:
    return [{"source": key, "count": count} for key, count in sorted(Counter(event["source"] for event in read_log_events()).items())]


def list_event_level_facets(db: Session) -> list[dict[str, Any]]:
    return [{"level": key, "count": count} for key, count in sorted(Counter(event["level"] for event in read_log_events()).items())]


def list_system_events_page(db: Session, *, page: int, page_size: int,
    level: str | None = None, source: str | None = None, search: str | None = None,
    date_from_ms: int | None = None, date_to_ms: int | None = None,
) -> SystemEventPageSnapshot:
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    sources: Counter[str] = Counter()
    levels: Counter[str] = Counter()
    total = 0
    selected = []
    last_page = []
    for event in read_log_events():
        sources[event["source"]] += 1
        levels[event["level"]] += 1
        if level and event["level"] != normalize_event_level(level):
            continue
        if source and event["source"] != source:
            continue
        if search and search.strip().casefold() not in " ".join(str(event.get(key, "")) for key in ("id", "message", "action")).casefold():
            continue
        created = to_timestamp_ms(event.get("createdAt")) or 0
        if date_from_ms is not None and created < date_from_ms:
            continue
        if date_to_ms is not None and created >= date_to_ms:
            continue
        if total % page_size == 0:
            last_page = []
        last_page.append(event)
        if (page - 1) * page_size <= total < page * page_size:
            selected.append(event)
        total += 1
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page > total_pages:
        selected = last_page
    return SystemEventPageSnapshot(selected, total, min(page, total_pages),
        [{"source": key, "count": count} for key, count in sorted(sources.items())],
        [{"level": key, "count": count} for key, count in sorted(levels.items())], log_size_bytes())


def clear_all_system_events(db: Session) -> int:
    return clear_log_files()
