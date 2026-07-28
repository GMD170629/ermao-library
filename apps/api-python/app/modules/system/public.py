"""Public domain contracts for the system capability."""

from app.modules.system.domain.events import (
    DEFAULT_MAX_EVENT_BYTES,
    LOG_MAX_BYTES_SETTING,
    MAX_MAX_EVENT_BYTES,
    MIN_MAX_EVENT_BYTES,
)
from app.modules.system.domain.queue import (
    ACTIVE_OPERATION_STATUSES,
    DEFAULT_BUSY_TIMEOUT_MS,
    HEARTBEAT_BUSY_TIMEOUT_MS,
    TERMINAL_OPERATION_STATUSES,
    safe_runtime_error,
)
from app.modules.system.domain.health import (
    HealthRunItem,
    HealthRunSnapshot,
    normalize_health_run_snapshot,
)
from app.modules.system.application.commands import (
    SystemUnitOfWork,
    execute_system_transaction,
)

__all__ = [
    "ACTIVE_OPERATION_STATUSES",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "DEFAULT_MAX_EVENT_BYTES",
    "HEARTBEAT_BUSY_TIMEOUT_MS",
    "LOG_MAX_BYTES_SETTING",
    "MAX_MAX_EVENT_BYTES",
    "MIN_MAX_EVENT_BYTES",
    "TERMINAL_OPERATION_STATUSES",
    "HealthRunItem",
    "HealthRunSnapshot",
    "SystemUnitOfWork",
    "execute_system_transaction",
    "normalize_health_run_snapshot",
    "safe_runtime_error",
]
