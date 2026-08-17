"""Small crash-released lock primitive keyed by a database sidecar path."""

from __future__ import annotations

import errno
import fcntl
import time
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self

from app.db.current.engine import canonical_database_path


class DatabaseSidecarLockTimeout(TimeoutError):
    """Raised when a database sidecar lock cannot be acquired in time."""


class DatabaseSidecarLock:
    """Exclusive process lock with OS-managed crash release."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        lock_suffix: str,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.05,
        timeout_error_type: type[TimeoutError] = DatabaseSidecarLockTimeout,
        lock_label: str = "database sidecar",
    ) -> None:
        if not lock_suffix.startswith(".") or "/" in lock_suffix or "\\" in lock_suffix:
            raise ValueError("lock_suffix must be a filename suffix")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.database_path = canonical_database_path(database_path)
        self.lock_path = self.database_path.with_name(
            f"{self.database_path.name}{lock_suffix}"
        )
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._timeout_error_type = timeout_error_type
        self._lock_label = lock_label
        self._handle: BinaryIO | None = None

    def acquire(self) -> Self:
        """Acquire the lock, waiting only up to the configured limit."""

        if self._handle is not None:
            raise RuntimeError(f"{self._lock_label} lock is already acquired")
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
                        raise self._timeout_error_type(
                            f"timed out acquiring {self._lock_label} lock: "
                            f"{self.lock_path}"
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


__all__ = ["DatabaseSidecarLock", "DatabaseSidecarLockTimeout"]
