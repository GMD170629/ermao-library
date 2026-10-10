"""System event retention and serialization policies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

DEFAULT_RETENTION_DAYS = 3
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365
LOG_RETENTION_DAYS_SETTING = "system.logs.retentionDays"
LOG_LEVELS = ("debug", "info", "warning", "error")


@dataclass(frozen=True, slots=True)
class PreparedSystemEvent:
    id: str
    level: str
    source: str
    actor_type: str
    actor_id: str | None
    action: str
    message: str
    metadata: dict[str, Any]
    created_at: datetime


def normalize_event_level(level: str) -> str:
    safe = "warning" if level == "warn" else level
    if safe not in LOG_LEVELS:
        return "info"
    return safe


def prepare_event_message(message: object) -> str:
    return str(message)


def prepare_event_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = json.loads(json.dumps(metadata or {}, ensure_ascii=False, default=str))
    # Log-only decorations; never traverse exception strings or SQL parameters.
    for key in (
        "requestId",
        "request_id",
        "taskId",
        "task_id",
        "taskKind",
        "task_kind",
        "operationId",
        "operation_id",
        "planId",
        "plan_id",
        "uploadId",
        "upload_id",
        "nodeId",
        "node_id",
        "parentDiagnosticId",
        "parent_diagnostic_id",
        "libraryId",
        "library_id",
        "resourceId",
        "resource_id",
        "sourceNodeId",
        "source_node_id",
        "bookId",
        "book_id",
        "bookIds",
        "importTaskId",
        "import_task_id",
        "correlation",
        "correlationId",
        "correlation_id",
        "targetId",
        "target_id",
        "targetType",
        "target_type",
        "targetOrdinal",
        "target_ordinal",
        "diagnosticId",
        "diagnostic_id",
        "relatedIds",
    ):
        payload.pop(key, None)
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, dict):
        diagnostics.pop("id", None)
        diagnostics.pop("relatedIds", None)
    # Historical SQL traces also used generated correlation identifiers. Visit
    # only diagnostic structure, never arbitrary SQL parameter values or text.
    pending = [payload]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            for key in ("transaction_id", "statement_id", "slowest_statement_id"):
                item.pop(key, None)
            for key in (
                "diagnostics",
                "chain",
                "members",
                "directException",
                "directCause",
                "rootCause",
                "contexts",
                "databaseOperations",
                "databaseTrace",
                "statements",
                "transaction_statements",
                "timing",
            ):
                if key in item:
                    pending.append(item[key])
    return payload


def validate_log_retention_days(days: int) -> int:
    if isinstance(days, bool) or not isinstance(days, int) or not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
        raise ValueError("log-retention-days-out-of-range")
    return days
