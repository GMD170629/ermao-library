"""Stable service facade for system event storage (owned by modules.system)."""

from app.bootstrap.system import (
    configured_max_event_bytes,
    prepare_system_event,
    prune_system_events,
    record_system_event,
    set_max_event_bytes,
    system_event_size_bytes,
    system_event_storage_view,
    write_prepared_system_events,
)
from app.modules.system.domain.events import (
    DEFAULT_MAX_EVENT_BYTES,
    LOG_MAX_BYTES_SETTING,
    MAX_EVENT_MESSAGE_CHARS,
    MAX_EVENT_METADATA_CHARS,
    MAX_MAX_EVENT_BYTES,
    MIN_MAX_EVENT_BYTES,
    PROTECTED_ERROR_ACTIONS,
)

__all__ = [
    "DEFAULT_MAX_EVENT_BYTES",
    "LOG_MAX_BYTES_SETTING",
    "MAX_EVENT_MESSAGE_CHARS",
    "MAX_EVENT_METADATA_CHARS",
    "MAX_MAX_EVENT_BYTES",
    "MIN_MAX_EVENT_BYTES",
    "PROTECTED_ERROR_ACTIONS",
    "configured_max_event_bytes",
    "prepare_system_event",
    "prune_system_events",
    "record_system_event",
    "set_max_event_bytes",
    "system_event_size_bytes",
    "system_event_storage_view",
    "write_prepared_system_events",
]
