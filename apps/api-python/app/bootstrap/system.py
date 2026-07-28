"""System capability composition root."""

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.system.application.commands import execute_system_transaction
from app.modules.system.domain.health import HealthRunSnapshot
from app.modules.system.infrastructure.events import (
    configured_max_event_bytes,
    list_event_level_facets,
    list_event_source_facets,
    prune_system_events as _prune_system_events,
    record_system_event as _record_system_event,
    set_max_event_bytes as _set_max_event_bytes,
    system_event_size_bytes,
    system_event_storage_view,
)
from app.modules.system.infrastructure.health import probe_database, run_system_health_checks
from app.modules.system.infrastructure.health_runs import (
    active_health_run_id,
    create_or_reuse_health_run as _create_or_reuse_health_run,
    fail_abandoned_health_runs as _fail_abandoned_health_runs,
    health_run_snapshot,
    prune_old_health_runs as _prune_old_health_runs,
    start_health_run,
)
from app.modules.system.infrastructure.queue_runtime import (
    QueueHeartbeatPump,
    active_restart_operation,
    create_restart_operation as _create_restart_operation,
    mark_queue_stopped as _mark_queue_stopped,
    queue_operation_view,
    queue_runtime_view,
    record_queue_heartbeat as _record_queue_heartbeat,
    update_restart_operation as _update_restart_operation,
)
from app.modules.system.infrastructure.settings import (
    delete_setting,
    delete_settings,
    existing_setting_keys,
    get_setting,
    get_setting_raw,
    list_settings,
    parse_setting_value,
    upsert_setting,
    upsert_settings,
)


def prune_system_events(
    db: Session,
    max_bytes: int | None = None,
    *,
    commit: bool = False,
) -> dict[str, int]:
    operation = lambda: _prune_system_events(db, max_bytes)
    return execute_system_transaction(db, operation) if commit else operation()


def set_max_event_bytes(db: Session, max_bytes: int) -> dict[str, Any]:
    return execute_system_transaction(
        db,
        lambda: _set_max_event_bytes(db, max_bytes),
    )


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
    operation = lambda: _record_system_event(
        db,
        source=source,
        action=action,
        message=message,
        level=level,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
        prune=prune,
    )
    return execute_system_transaction(db, operation) if commit else operation()


def create_or_reuse_health_run(
    db: Session,
    settings: Settings,
    actor_user_id: str,
) -> tuple[HealthRunSnapshot, bool]:
    return execute_system_transaction(
        db,
        lambda: _create_or_reuse_health_run(db, settings, actor_user_id),
    )


def fail_abandoned_health_runs(db: Session) -> int:
    return execute_system_transaction(
        db,
        lambda: _fail_abandoned_health_runs(db),
    )


def prune_old_health_runs(db: Session, max_age_hours: int = 24) -> int:
    return execute_system_transaction(
        db,
        lambda: _prune_old_health_runs(db, max_age_hours),
    )


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
    execute_system_transaction(
        db,
        lambda: _record_queue_heartbeat(
            db,
            queue_name,
            instance_id,
            poll_interval_seconds,
            status=status,
            processed=processed,
            error=error,
        ),
    )


def mark_queue_stopped(db: Session, queue_name: str, instance_id: str) -> None:
    execute_system_transaction(
        db,
        lambda: _mark_queue_stopped(db, queue_name, instance_id),
    )


def create_restart_operation(
    db: Session,
    actor_user_id: str,
) -> tuple[dict[str, Any], bool]:
    return execute_system_transaction(
        db,
        lambda: _create_restart_operation(db, actor_user_id),
    )


def update_restart_operation(
    db: Session,
    operation_id: str,
    status: str,
    message_code: str,
) -> None:
    execute_system_transaction(
        db,
        lambda: _update_restart_operation(
            db,
            operation_id,
            status,
            message_code,
        ),
    )

__all__ = [
    "QueueHeartbeatPump",
    "active_health_run_id",
    "active_restart_operation",
    "configured_max_event_bytes",
    "create_or_reuse_health_run",
    "create_restart_operation",
    "delete_setting",
    "delete_settings",
    "existing_setting_keys",
    "fail_abandoned_health_runs",
    "get_setting",
    "get_setting_raw",
    "health_run_snapshot",
    "list_event_level_facets",
    "list_event_source_facets",
    "list_settings",
    "mark_queue_stopped",
    "parse_setting_value",
    "probe_database",
    "prune_old_health_runs",
    "prune_system_events",
    "queue_operation_view",
    "queue_runtime_view",
    "record_queue_heartbeat",
    "record_system_event",
    "run_system_health_checks",
    "set_max_event_bytes",
    "start_health_run",
    "system_event_size_bytes",
    "system_event_storage_view",
    "update_restart_operation",
    "upsert_setting",
    "upsert_settings",
]
