"""Crash-released cross-process lock for current schema initialization."""

from __future__ import annotations

from pathlib import Path

from app.db.current.sidecar_lock import DatabaseSidecarLock


class SchemaLockTimeout(TimeoutError):
    """Raised when another process holds the current schema lock too long."""


class SchemaLock(DatabaseSidecarLock):
    """Exclusive sidecar lock keyed by a canonical database path."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        super().__init__(
            database_path,
            lock_suffix=".schema.lock",
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            timeout_error_type=SchemaLockTimeout,
            lock_label="schema",
        )


def schema_lock(
    database_path: str | Path,
    *,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.05,
) -> SchemaLock:
    """Construct a current schema lock context manager."""

    return SchemaLock(
        database_path,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
