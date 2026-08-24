"""Presentation mappers for the target LibraryImportTask contract."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from app.core.time import timestamp_ms_to_iso


def _datetime_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return timestamp_ms_to_iso(value) or value.isoformat()
    return str(value)


def import_task_view(task: Mapping[str, object]) -> dict[str, object]:
    """Map one ORM projection without exposing database naming details."""

    return {
        "id": str(task.get("id") or ""),
        "kind": str(task.get("kind") or ""),
        "libraryId": task.get("libraryId"),
        "libraryName": task.get("libraryName"),
        "resourceId": task.get("resourceId"),
        "resourceTitle": task.get("resourceTitle"),
        "sourceNodeId": task.get("sourceNodeId"),
        "sourceName": task.get("sourceName"),
        "sourceRelativePath": task.get("sourceRelativePath"),
        "bookTitle": task.get("bookTitle"),
        "role": task.get("role"),
        "state": str(task.get("state") or ""),
        "errorSummary": task.get("errorSummary"),
        "createdAt": _datetime_value(task.get("createdAt")),
        "startedAt": _datetime_value(task.get("startedAt")),
        "finishedAt": _datetime_value(task.get("finishedAt")),
    }


__all__ = ["import_task_view"]
