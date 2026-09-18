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


_DIAGNOSTIC_LIST_OMITTED_KEYS = frozenset({"traceback", "chain", "members"})


def summarize_diagnostic_metadata(metadata: Any) -> Any:
    """Keep the small diagnostic summary and omit bulk payload from lists."""

    if not isinstance(metadata, dict):
        return metadata
    diagnostics = metadata.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return metadata
    summary = {key: value for key, value in metadata.items() if key != "diagnostics"}
    summary["diagnostics"] = {
        key: value
        for key, value in diagnostics.items()
        if key not in _DIAGNOSTIC_LIST_OMITTED_KEYS
    }
    return summary


def serialize_system_event(
    event: dict[str, Any],
    *,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    metadata = _parse_json(event.get("metadata"), {})
    if not include_diagnostics:
        metadata = summarize_diagnostic_metadata(metadata)
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
        "createdAt": timestamp_ms_to_iso(created)
        or (str(created) if created is not None else None),
    }
