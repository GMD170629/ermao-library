"""System event retention and serialization policies."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_MAX_EVENT_BYTES = 5 * 1024 * 1024
MIN_MAX_EVENT_BYTES = 1 * 1024 * 1024
MAX_MAX_EVENT_BYTES = 100 * 1024 * 1024
MAX_EVENT_MESSAGE_CHARS = 4000
MAX_EVENT_METADATA_CHARS = 64 * 1024
LOG_MAX_BYTES_SETTING = "system.logs.maxBytes"
LAST_PRUNED_AT_SETTING = "events.lastPrunedAt"
PROTECTED_ERROR_ACTIONS = frozenset({"deleted", "restored", "settings.updated", "backup.restored"})
PRUNE_LEVEL_ORDER = ("info", "warning", "warn", "error")


def clamp_max_event_bytes(value: object) -> int:
    try:
        size = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        size = DEFAULT_MAX_EVENT_BYTES
    return min(MAX_MAX_EVENT_BYTES, max(MIN_MAX_EVENT_BYTES, size))


def parse_max_event_bytes(raw: object | None) -> int:
    if raw is None:
        return DEFAULT_MAX_EVENT_BYTES
    try:
        parsed = json.loads(str(raw)) if not isinstance(raw, (int, float)) else raw
        return clamp_max_event_bytes(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        return DEFAULT_MAX_EVENT_BYTES


def normalize_event_level(level: str) -> str:
    safe = "warning" if level == "warn" else level
    if safe not in {"info", "warning", "error"}:
        return "info"
    return safe


def truncate_event_message(message: object) -> str:
    return str(message)[:MAX_EVENT_MESSAGE_CHARS]


def prepare_event_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = metadata or {}
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    if len(serialized) <= MAX_EVENT_METADATA_CHARS:
        return json.loads(serialized)
    return {
        "truncated": True,
        "preview": serialized[: MAX_EVENT_METADATA_CHARS - 80],
    }


def validate_log_max_bytes(max_bytes: int) -> int:
    size = int(max_bytes)
    if not MIN_MAX_EVENT_BYTES <= size <= MAX_MAX_EVENT_BYTES:
        raise ValueError("log-size-out-of-range")
    return size
