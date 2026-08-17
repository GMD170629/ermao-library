"""SQLite concurrency error classification at the SQLAlchemy boundary."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.exc import OperationalError

_SQLITE_BUSY = 5
_SQLITE_LOCKED = 6
_SQLITE_PRIMARY_CODE_MASK = 0xFF
_BUSY_MESSAGES = frozenset({"database is busy", "database is locked"})


@runtime_checkable
class _SqliteErrorCode(Protocol):
    sqlite_errorcode: int


def is_sqlite_busy_or_locked(error: OperationalError) -> bool:
    """Return whether a DBAPI OperationalError is SQLite BUSY/LOCKED."""

    original = error.orig
    if isinstance(original, _SqliteErrorCode):
        primary_code = original.sqlite_errorcode & _SQLITE_PRIMARY_CODE_MASK
        return primary_code in {_SQLITE_BUSY, _SQLITE_LOCKED}
    return str(original).strip().casefold() in _BUSY_MESSAGES


__all__ = ["is_sqlite_busy_or_locked"]
