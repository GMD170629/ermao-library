"""Queue runtime view and error sanitization policies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.database_errors import (
    DATABASE_BUSY_MESSAGES,
    is_database_busy_error,
)

ACTIVE_OPERATION_STATUSES = ("requested", "waiting", "running")
TERMINAL_OPERATION_STATUSES = ("completed", "failed")
HEARTBEAT_BUSY_TIMEOUT_MS = 1_000
DEFAULT_BUSY_TIMEOUT_MS = 10_000


@dataclass(frozen=True, slots=True)
class PreparedQueueHeartbeat:
    queue_name: str
    instance_id: str
    status: str
    poll_interval_seconds: float
    recorded_at: int
    processed_at: int | None
    error_text: str | None


def safe_runtime_error(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    value = (
        (str(error).strip() or error.__class__.__name__)
        if isinstance(error, BaseException)
        else str(error).strip()
    )
    if isinstance(error, BaseException) and is_database_busy_error(error):
        return "database-is-busy"
    if any(fragment in value.lower() for fragment in DATABASE_BUSY_MESSAGES):
        return "database-is-busy"
    value = re.sub(
        r"/(?:Users|home|var|Volumes|volume\d+|mnt|srv|opt)/[^\s'\"]+",
        "[local-path]",
        value,
    )
    value = re.sub(r"[A-Z]:\\[^\s'\"]+", "[local-path]", value, flags=re.IGNORECASE)
    value = re.sub(
        r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*\S+", r"\1=[redacted]", value
    )
    return value[:1000]


def prepare_queue_heartbeat(
    *,
    queue_name: str,
    instance_id: str,
    poll_interval_seconds: float,
    recorded_at: int,
    status: str = "running",
    processed: bool = False,
    error: BaseException | str | None = None,
) -> PreparedQueueHeartbeat:
    return PreparedQueueHeartbeat(
        queue_name=queue_name,
        instance_id=instance_id,
        status=status,
        poll_interval_seconds=float(poll_interval_seconds),
        recorded_at=recorded_at,
        processed_at=recorded_at if processed else None,
        error_text=safe_runtime_error(error),
    )


def enrich_queue_runtime_view(
    row: dict[str, Any],
    *,
    now_ms: int,
    heartbeat_ms: int | None,
) -> dict[str, Any]:
    result = dict(row)
    poll = float(result.get("pollIntervalSeconds") or 0)
    stale_after_ms = int(max(30.0, poll * 3.0) * 1000)
    result["heartbeatAgeMs"] = (
        max(0, now_ms - heartbeat_ms) if heartbeat_ms is not None else None
    )
    result["staleAfterMs"] = stale_after_ms
    result["stale"] = heartbeat_ms is None or now_ms - heartbeat_ms > stale_after_ms
    return result
