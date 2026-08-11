"""Cross-process coordination for exceptional live database maintenance."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import OperationalError as SQLiteOperationalError
from time import monotonic, sleep
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.settings import SystemSetting

DATABASE_MAINTENANCE_SETTING_KEY = "databaseMaintenanceMode"
DATABASE_MAINTENANCE_RESTORE_VALUE = "RESTORE"


class DatabaseMaintenanceLockTimeout(OperationalError):
    """Raised when a writer cannot enter while maintenance owns the barrier."""

    def __init__(self) -> None:
        super().__init__(
            statement=None,
            params=None,
            orig=SQLiteOperationalError(
                "database is busy: database maintenance lock is active"
            ),
        )


def database_maintenance_lock_path(database_path: Path) -> Path:
    """Return the sidecar lock shared by every process using one database."""

    return database_path.with_name(f"{database_path.name}.maintenance.lock")


def _acquire_lock(
    database_path: Path,
    *,
    exclusive: bool,
    timeout_seconds: float,
) -> BinaryIO:
    lock_path = database_maintenance_lock_path(database_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    operation = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
    deadline = monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            fcntl.flock(handle.fileno(), operation)
            return handle
        except BlockingIOError:
            if monotonic() >= deadline:
                handle.close()
                raise DatabaseMaintenanceLockTimeout() from None
            sleep(min(0.01, max(0.0, deadline - monotonic())))


def acquire_database_writer_lease(
    database_path: Path, *, timeout_seconds: float
) -> BinaryIO:
    """Acquire the shared barrier lease held for one normal write transaction."""

    return _acquire_lock(
        database_path,
        exclusive=False,
        timeout_seconds=timeout_seconds,
    )


def release_database_maintenance_lock(handle: BinaryIO | None) -> None:
    """Release and close a previously acquired maintenance lock handle."""

    if handle is None or handle.closed:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def database_restore_barrier(
    database_path: Path, *, timeout_seconds: float = 30.0
) -> Iterator[None]:
    """Wait for existing writers and exclusively block new write transactions."""

    handle = _acquire_lock(
        database_path,
        exclusive=True,
        timeout_seconds=timeout_seconds,
    )
    try:
        yield
    finally:
        release_database_maintenance_lock(handle)


@contextmanager
def database_restore_connection(connection: Connection) -> Iterator[None]:
    """Mark the connection already protected by the exclusive restore barrier."""

    connection_info = connection.info
    previous = bool(connection_info.get("database_restore_owner", False))
    connection_info["database_restore_owner"] = True
    try:
        yield
    finally:
        if previous:
            connection_info["database_restore_owner"] = True
        else:
            connection_info.pop("database_restore_owner", None)


def database_maintenance_is_active(db: Session) -> bool:
    """Read the persistent maintenance state without performing any DML."""

    value = db.scalar(
        select(SystemSetting.value).where(
            SystemSetting.key == DATABASE_MAINTENANCE_SETTING_KEY
        )
    )
    return value == DATABASE_MAINTENANCE_RESTORE_VALUE
