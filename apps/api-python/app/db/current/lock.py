"""Crash-released cross-process lock for current schema initialization."""

from __future__ import annotations

import errno
import fcntl
import time
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self

from app.db.current.engine import canonical_database_path


class SchemaLockTimeout(TimeoutError):
    """Raised when another process holds the current schema lock too long."""


class SchemaLock:
    """Exclusive sidecar lock keyed by a canonical database path."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.database_path = canonical_database_path(database_path)
        self.lock_path = self.database_path.with_name(
            f"{self.database_path.name}.schema.lock"
        )
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._handle: BinaryIO | None = None

    def acquire(self) -> Self:
        """Acquire the exclusive lock, waiting only up to the configured limit."""

        if self._handle is not None:
            raise RuntimeError("schema lock is already acquired")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        deadline = time.monotonic() + self.timeout_seconds
        try:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        raise
                    if time.monotonic() >= deadline:
                        raise SchemaLockTimeout(
                            f"timed out acquiring schema lock: {self.lock_path}"
                        ) from exc
                    time.sleep(self.poll_interval_seconds)
                else:
                    self._handle = handle
                    return self
        except BaseException:
            handle.close()
            raise

    def release(self) -> None:
        """Release the lock and close the sidecar handle."""

        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> Self:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


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
