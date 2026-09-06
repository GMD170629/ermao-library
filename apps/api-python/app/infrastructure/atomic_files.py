"""Small, bounded atomic filesystem publication primitives."""

from __future__ import annotations

import os
from pathlib import Path
from time import sleep
from uuid import uuid4

_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS = (0.005, 0.01, 0.02)


def _is_windows_replace_lock(error: PermissionError) -> bool:
    """Recognize Windows sharing errors without treating POSIX errno as winerror."""

    return getattr(error, "winerror", None) in {5, 32}


def write_atomic_bytes(path: Path, data: bytes) -> None:
    """Publish bytes atomically, with bounded recovery for Windows sharing locks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        for attempt in range(len(_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS) + 1):
            try:
                os.replace(temporary, path)
                return
            except PermissionError as exc:
                if not _is_windows_replace_lock(exc):
                    raise
                if attempt == len(_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS):
                    raise
                sleep(_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS[attempt])
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["write_atomic_bytes"]
