"""System event and settings projections used by application use cases."""

from __future__ import annotations

import json
from typing import Any

from app.core.time import timestamp_ms_to_iso


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def serialize_system_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = _parse_json(event.get("metadata"), {})
    created = event.get("createdAt")
    return {
        "id": event.get("id"),
        "level": event.get("level") or "info",
        "source": event.get("source") or "system",
        "actorType": event.get("actorType") or "system",
        "actorId": event.get("actorId"),
        "action": event.get("action") or "",
        "targetType": event.get("targetType"),
        "targetId": event.get("targetId"),
        "message": event.get("message") or "",
        "metadata": metadata if isinstance(metadata, dict) else {},
        "createdAt": timestamp_ms_to_iso(created) or (str(created) if created is not None else None),
    }
