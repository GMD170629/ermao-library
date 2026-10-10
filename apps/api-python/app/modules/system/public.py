"""Public domain contracts for the system capability."""

from app.core.database_errors import is_database_busy_error
from app.modules.system.application.commands import SystemUnitOfWork
from app.modules.system.domain.events import (
    DEFAULT_RETENTION_DAYS,
    LOG_RETENTION_DAYS_SETTING,
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    PreparedSystemEvent,
)
from app.modules.system.domain.health import (
    HealthRunItem,
    HealthRunSnapshot,
    normalize_health_run_snapshot,
)
from app.modules.system.domain.queue import (
    safe_runtime_error,
)
from app.modules.system.domain.settings_policy import (
    RETIRED_SYSTEM_SETTING_KEYS,
    SENSITIVE_SYSTEM_SETTING_KEYS,
    public_system_settings,
)

__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "LOG_RETENTION_DAYS_SETTING",
    "MAX_RETENTION_DAYS",
    "MIN_RETENTION_DAYS",
    "RETIRED_SYSTEM_SETTING_KEYS",
    "SENSITIVE_SYSTEM_SETTING_KEYS",
    "HealthRunItem",
    "HealthRunSnapshot",
    "PreparedSystemEvent",
    "SystemUnitOfWork",
    "is_database_busy_error",
    "normalize_health_run_snapshot",
    "public_system_settings",
    "safe_runtime_error",
]
