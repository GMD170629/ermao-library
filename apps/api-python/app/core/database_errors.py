"""Framework-neutral classification for shared database failure policies."""

from __future__ import annotations

DATABASE_BUSY_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database is busy",
)
DATABASE_OPERATION_TIMEOUT_MESSAGES = ("interrupted",)


def is_database_busy_error(error: BaseException) -> bool:
    """Return whether an error represents transient database lock contention."""

    original = getattr(error, "orig", None)
    message = str(original or error).lower()
    return any(fragment in message for fragment in DATABASE_BUSY_MESSAGES)


def is_database_operation_timeout(error: BaseException) -> bool:
    """Return whether SQLite interrupted an explicitly budgeted operation."""

    original = getattr(error, "orig", None)
    message = str(original or error).lower()
    return any(fragment in message for fragment in DATABASE_OPERATION_TIMEOUT_MESSAGES)
