"""Small, bounded atomic filesystem publication primitives."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from time import sleep
from uuid import uuid4

from app.core.exception_diagnostics import record_exception

_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS = (0.005, 0.01, 0.02)


def _is_windows_replace_lock(error: PermissionError) -> bool:
    """Recognize Windows sharing errors without treating POSIX errno as winerror."""

    return getattr(error, "winerror", None) in {5, 32}


def write_atomic_bytes(path: Path, data: bytes) -> None:
    """Publish bytes atomically, with bounded recovery for Windows sharing locks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    primary_id = None
    try:
        temporary.write_bytes(data)
        for attempt in range(len(_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS) + 1):
            try:
                os.replace(temporary, path)
                return
            except PermissionError as exc:
                primary_id = record_exception(
                    logging.getLogger(__name__),
                    "atomic_file.replace_failed",
                    exc,
                    context={"step": "atomic_replace", "attempt": attempt + 1},
                )
                if not _is_windows_replace_lock(exc):
                    raise
                if attempt == len(_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS):
                    raise
                sleep(_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS[attempt])
    except Exception as error:
        primary_id = record_exception(
            logging.getLogger(__name__),
            "atomic_file.publish_failed",
            error,
            context={"step": "atomic_publish"},
        )
        raise
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as error:
            record_exception(
                logging.getLogger(__name__),
                "atomic_file.cleanup_failed",
                error,
                context={
                    "step": "remove_temporary",
                    "parent_diagnostic_id": primary_id,
                },
            )
            raise


__all__ = ["write_atomic_bytes"]
