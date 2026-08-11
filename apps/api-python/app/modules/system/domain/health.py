"""Health check status helpers."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from app.core.time import to_timestamp_ms

TERMINAL_CHECK_STATUSES = frozenset({"ok", "warning", "error", "skipped"})


class HealthRunItem(TypedDict):
    id: str
    group: str
    labelCode: str
    kind: str
    options: dict[str, object]
    status: str
    messageCode: str
    messageParams: dict[str, object]
    details: dict[str, object]
    startedAt: int | None
    finishedAt: int | None
    durationMs: int | None


class HealthRunSnapshot(TypedDict):
    runId: str
    status: str
    version: int
    startedAt: int
    finishedAt: int | None
    groups: list[dict[str, str]]
    items: list[HealthRunItem]
    summary: dict[str, int]
    created: NotRequired[bool]


def health_check_item(
    name: str,
    status: str,
    message: str,
) -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def summarize_health_items(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(items),
        "completed": 0,
        "ok": 0,
        "warning": 0,
        "error": 0,
        "skipped": 0,
    }
    for item in items:
        status = str(item.get("status"))
        if status in TERMINAL_CHECK_STATUSES:
            summary["completed"] += 1
            summary[status] += 1
    return summary


def overall_health_status(checks: list[dict[str, Any]]) -> str:
    return "error" if any(check.get("status") == "error" for check in checks) else "ok"


def normalize_health_run_snapshot(snapshot: dict[str, Any]) -> HealthRunSnapshot:
    """Normalize persisted health-run timestamps at the capability boundary."""

    normalized = dict(snapshot)
    started_at = to_timestamp_ms(normalized.get("startedAt"))
    if started_at is None:
        raise ValueError("health-run-started-at-missing")
    normalized["startedAt"] = started_at
    normalized["finishedAt"] = to_timestamp_ms(normalized.get("finishedAt"))
    normalized_items: list[HealthRunItem] = []
    for raw_item in normalized.get("items", []):
        item = dict(raw_item)
        item["startedAt"] = to_timestamp_ms(item.get("startedAt"))
        item["finishedAt"] = to_timestamp_ms(item.get("finishedAt"))
        normalized_items.append(item)
    normalized["items"] = normalized_items
    return normalized
