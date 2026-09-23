"""Framework-neutral classification for shared database failure policies."""

from __future__ import annotations

import sqlite3

DATABASE_BUSY_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database is busy",
)


def is_database_busy_error(error: BaseException) -> bool:
    """Return whether an error represents transient database lock contention."""

    original = getattr(error, "orig", None)
    message = str(original or error).lower()
    return any(fragment in message for fragment in DATABASE_BUSY_MESSAGES)


def is_database_operation_timeout(error: BaseException) -> bool:
    """Return whether SQLite interrupted an explicitly budgeted operation."""

    original = getattr(error, "orig", None)
    return getattr(original or error, "time_budget_exceeded", False) is True


def is_retryable_sqlite_operation_error(error: BaseException) -> bool:
    """Accept only SQLite lock contention or an explicitly marked budget expiry."""
    original = getattr(error, "orig", error)
    if is_database_operation_timeout(error):
        return isinstance(original, sqlite3.OperationalError)
    if not isinstance(original, sqlite3.OperationalError):
        return False
    code = getattr(original, "sqlite_errorcode", None)
    if code is not None:
        return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    # Synthetic DB-API failures may lack sqlite_errorcode. Only SQLite's exact
    # lock messages qualify; an arbitrary message containing those words does not.
    return str(original).strip().lower() in DATABASE_BUSY_MESSAGES
