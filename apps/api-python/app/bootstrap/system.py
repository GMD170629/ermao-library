"""System capability composition root."""

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.modules.library.infrastructure.dashboard import (
    management_card_counts,
    recent_system_events,
)
from app.modules.system.application.commands import SystemWriteTransaction
from app.modules.system.domain.events import (
    LOG_MAX_BYTES_SETTING,
    PreparedSystemEvent,
    validate_log_max_bytes,
)
from app.modules.system.domain.health import HealthRunSnapshot
from app.modules.system.domain.queue import prepare_queue_heartbeat
from app.modules.system.infrastructure.events import (
    clear_info_warning_events,
    configured_max_event_bytes,
    list_event_level_facets,
    list_event_source_facets,
    list_system_events_page,
    prepare_system_event,
    prepare_system_event_prune,
    system_event_size_bytes,
    system_event_storage_view,
    write_prepared_system_event_prune,
    write_prepared_system_events,
)
from app.modules.system.infrastructure.events import (
    prune_system_events as _prune_system_events,
)
from app.modules.system.infrastructure.health import (
    probe_database,
    run_system_health_checks,
)
from app.modules.system.infrastructure.health_runs import (
    health_run_snapshot,
    prepare_abandoned_health_runs,
    prepare_health_run_creation,
    prepare_old_health_runs_prune,
    start_health_run,
    write_prepared_abandoned_health_runs,
    write_prepared_health_run_creation,
    write_prepared_old_health_runs_prune,
)
from app.modules.system.infrastructure.import_status import (
    library_import_dashboard_snapshot,
)
from app.modules.system.infrastructure.queue_runtime import (
    QueueHeartbeatPump,
    prepare_queue_heartbeat_write,
    prepare_queue_stopped_write,
    write_prepared_queue_runtime,
)
from app.modules.system.infrastructure.settings import (
    PreparedSettingsWrite,
    delete_setting,
    delete_settings,
    existing_setting_keys,
    get_setting,
    get_setting_raw,
    list_settings,
    parse_setting_value,
    prepare_settings_write,
    upsert_setting,
    upsert_settings,
    write_prepared_settings,
)


def management_overview_snapshot(
    db: Session,
    settings: Settings,
) -> dict[str, object]:
    health = run_system_health_checks(db, settings)
    raw_checks = health.get("checks")
    check_items = raw_checks if isinstance(raw_checks, list) else []
    checks = {
        str(item.get("name") or "unknown"): {
            "status": str(item.get("status") or "unknown"),
            "message": str(item.get("message") or ""),
        }
        for item in check_items
        if isinstance(item, dict)
    }
    storage = system_event_storage_view(db)
    cards = {
        **management_card_counts(db),
        "eventLogSizeBytes": int(storage["sizeBytes"]),
        "eventLogMaxBytes": int(storage["maxBytes"]),
    }
    return {
        "cards": cards,
        "checks": checks,
        "recentEvents": recent_system_events(db, limit=8),
    }


def prune_system_events(
    db: Session,
    max_bytes: int | None = None,
) -> dict[str, int]:
    return _prune_system_events(db, max_bytes)


def maintain_system_events(
    db: Session,
    max_bytes: int | None = None,
) -> dict[str, int]:
    prepared = prepare_system_event_prune(db, max_bytes)
    if not prepared.event_ids:
        return {
            "deleted": 0,
            "sizeBytes": prepared.current_size_bytes,
            "maxBytes": prepared.max_bytes,
        }
    with SystemWriteTransaction(db):
        result = write_prepared_system_event_prune(db, prepared)
    return result


def set_max_event_bytes(db: Session, max_bytes: int) -> dict[str, Any]:
    prepared_max_bytes = validate_log_max_bytes(max_bytes)
    prepared_settings = prepare_settings_write(
        {LOG_MAX_BYTES_SETTING: prepared_max_bytes}
    )
    with SystemWriteTransaction(db):
        write_prepared_settings(db, prepared_settings)
    return system_event_storage_view(db)


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
    prepared_event = prepare_system_event(
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
    return write_prepared_system_events(db, [prepared_event])[0]


def persist_system_events(
    db: Session,
    events: tuple[PreparedSystemEvent, ...],
) -> None:
    """Persist already prepared system events in one named short transaction."""

    with SystemWriteTransaction(db):
        write_prepared_system_events(db, events)


def prepare_system_setting_values(
    setting_values: dict[str, object],
) -> PreparedSettingsWrite:
    """Serialize setting rows before opening their short write transaction."""

    return prepare_settings_write(setting_values)


def persist_system_setting_values(
    db: Session,
    prepared: PreparedSettingsWrite,
) -> None:
    """Persist already prepared setting rows in one SQL-only transaction."""

    with SystemWriteTransaction(db):
        write_prepared_settings(db, prepared)


def persist_log_settings_update(
    db: Session,
    *,
    max_bytes: int,
    event: PreparedSystemEvent,
) -> None:
    prepared_settings = prepare_settings_write({LOG_MAX_BYTES_SETTING: max_bytes})
    with SystemWriteTransaction(db):
        write_prepared_settings(db, prepared_settings)
        write_prepared_system_events(db, (event,))


def persist_opds_settings_update(
    db: Session,
    *,
    setting_values: dict[str, object],
    event: PreparedSystemEvent,
) -> None:
    prepared_settings = prepare_settings_write(setting_values)
    with SystemWriteTransaction(db):
        write_prepared_settings(db, prepared_settings)
        write_prepared_system_events(db, (event,))


def persist_system_settings_update(
    db: Session,
    *,
    setting_values: dict[str, object],
    clear_keys: tuple[str, ...],
    event: PreparedSystemEvent,
) -> None:
    prepared_settings = prepare_settings_write(setting_values)
    with SystemWriteTransaction(db):
        write_prepared_settings(db, prepared_settings)
        if clear_keys:
            delete_settings(db, clear_keys)
        write_prepared_system_events(db, (event,))


def clear_system_events_with_audit(
    db: Session,
    *,
    event: PreparedSystemEvent,
) -> int:
    with SystemWriteTransaction(db):
        deleted = clear_info_warning_events(db)
        write_prepared_system_events(db, (event,))
    return deleted


def create_or_reuse_health_run(
    db: Session,
    settings: Settings,
    actor_user_id: str,
) -> tuple[HealthRunSnapshot, bool]:
    prepared = prepare_health_run_creation(db, settings, actor_user_id)
    if not prepared.created:
        return prepared.snapshot, False
    with SystemWriteTransaction(db):
        write_prepared_health_run_creation(db, prepared)
    return prepared.snapshot, True


def fail_abandoned_health_runs(db: Session) -> int:
    prepared = prepare_abandoned_health_runs(db)
    if not prepared.rows:
        return 0
    with SystemWriteTransaction(db):
        changed = write_prepared_abandoned_health_runs(db, prepared)
    return changed


def prune_old_health_runs(db: Session, max_age_hours: int = 24) -> int:
    statement = prepare_old_health_runs_prune(max_age_hours)
    with SystemWriteTransaction(db):
        deleted = write_prepared_old_health_runs_prune(db, statement)
    return deleted


def record_queue_heartbeat(
    db: Session,
    queue_name: str,
    instance_id: str,
    poll_interval_seconds: float,
    *,
    status: str = "running",
    processed: bool = False,
    error: BaseException | str | None = None,
) -> None:
    prepared = prepare_queue_heartbeat(
        queue_name=queue_name,
        instance_id=instance_id,
        poll_interval_seconds=poll_interval_seconds,
        recorded_at=now_timestamp_ms(),
        status=status,
        processed=processed,
        error=error,
    )
    prepared_write = prepare_queue_heartbeat_write(prepared)
    with SystemWriteTransaction(db):
        write_prepared_queue_runtime(db, prepared_write)


def mark_queue_stopped(db: Session, queue_name: str, instance_id: str) -> None:
    prepared = prepare_queue_stopped_write(
        queue_name,
        instance_id,
        now=now_timestamp_ms(),
    )
    with SystemWriteTransaction(db):
        write_prepared_queue_runtime(db, prepared)


__all__ = [
    "QueueHeartbeatPump",
    "clear_info_warning_events",
    "clear_system_events_with_audit",
    "configured_max_event_bytes",
    "create_or_reuse_health_run",
    "delete_setting",
    "delete_settings",
    "existing_setting_keys",
    "fail_abandoned_health_runs",
    "get_setting",
    "get_setting_raw",
    "health_run_snapshot",
    "library_import_dashboard_snapshot",
    "list_event_level_facets",
    "list_event_source_facets",
    "list_settings",
    "list_system_events_page",
    "maintain_system_events",
    "mark_queue_stopped",
    "parse_setting_value",
    "persist_log_settings_update",
    "persist_opds_settings_update",
    "persist_system_events",
    "persist_system_setting_values",
    "persist_system_settings_update",
    "prepare_system_event",
    "prepare_system_setting_values",
    "probe_database",
    "prune_old_health_runs",
    "prune_system_events",
    "record_queue_heartbeat",
    "record_system_event",
    "run_system_health_checks",
    "set_max_event_bytes",
    "start_health_run",
    "system_event_size_bytes",
    "system_event_storage_view",
    "upsert_setting",
    "upsert_settings",
    "write_prepared_system_events",
]
