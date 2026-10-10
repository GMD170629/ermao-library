"""Stable service facade for system event storage (owned by modules.system)."""

from app.bootstrap.system import (
    configured_retention_days,
    prepare_system_event,
    prune_system_events,
    record_system_event,
    set_retention_days,
    system_event_size_bytes,
    system_event_storage_view,
    write_prepared_system_events,
)
from app.modules.system.domain.events import (
    DEFAULT_RETENTION_DAYS,
    LOG_RETENTION_DAYS_SETTING,
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
)

__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "LOG_RETENTION_DAYS_SETTING",
    "MAX_RETENTION_DAYS",
    "MIN_RETENTION_DAYS",
    "configured_retention_days",
    "prepare_system_event",
    "prune_system_events",
    "record_system_event",
    "set_retention_days",
    "system_event_size_bytes",
    "system_event_storage_view",
    "write_prepared_system_events",
]
