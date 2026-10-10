from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.exception_diagnostics import diagnostic_text
from app.core.time import timestamp_ms_to_iso

from .domain import FeedbackDiagnostics, FeedbackDraft, FeedbackPreview, preview_hash


class FeedbackAccessError(Exception):
    pass


class FeedbackEventMissing(Exception):
    pass


@dataclass(frozen=True)
class FeedbackContext:
    role: str
    can_manage_system: bool
    app_version: str


class FeedbackDiagnosticsPort(Protocol):
    def event_bundle(self, event_id: str) -> list[dict[str, object]]: ...



def _safe(value: object, limit: int = 500) -> str:
    if value is None:
        return ""
    sanitized = diagnostic_text(value)
    sanitized = re.sub(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", "[ip-redacted]", sanitized)
    sanitized = re.sub(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F]{0,4}(?![\w:])", "[ip-redacted]", sanitized)
    return sanitized[:limit]




def prepare_preview(context: FeedbackContext, diagnostics_reader: FeedbackDiagnosticsPort, draft: FeedbackDraft) -> FeedbackPreview:
    diagnostics: dict[str, object] = {}
    if draft.include_environment:
        client = draft.client_environment
        if client is None or draft.installation_method is None:
            raise ValueError("client environment required")
        installation_labels = {
            "app-store": ("应用商店安装", "App store installation"),
            "manual": ("手动安装", "Manual installation"),
            "docker": ("Docker 安装", "Docker installation"),
        }
        diagnostics["environment"] = {
            "appVersion": context.app_version,
            "installationMethod": installation_labels[draft.installation_method][0 if client.locale == "zh-CN" else 1],
            **client.model_dump(mode="json", by_alias=True),
            "userAgent": _safe(client.user_agent, 2048),
            "platform": _safe(client.platform, 200),
        }
    if draft.event_id:
        if draft.kind != "issue" or not (context.role == "admin" or context.can_manage_system):
            raise FeedbackAccessError()
        events = diagnostics_reader.event_bundle(draft.event_id)
        if not events:
            raise FeedbackEventMissing()
        log_events: list[dict[str, object]] = []
        for event in events:
            metadata = event.get("metadata")
            details = metadata.get("diagnostics") if isinstance(metadata, dict) else None
            detail = details if isinstance(details, dict) else {}
            created_at = event.get("createdAt")
            log_events.append({
                "id": str(event["id"]),
                "level": str(event.get("level") or ""),
                "source": str(event.get("source") or ""),
                "message": str(event.get("message") or ""),
                "createdAt": timestamp_ms_to_iso(created_at) if isinstance(created_at, datetime) else _safe(created_at, 40),
                "exceptionType": str(detail.get("exceptionType") or ""),
                "diagnosticMessage": str(detail.get("message") or ""),
                "traceback": str(detail.get("traceback") or "") if event["id"] == draft.event_id else "",
            })
        diagnostics["log"] = {
            "selectedEventId": draft.event_id,
            "events": log_events,
        }
    return FeedbackPreview(
        diagnostics=FeedbackDiagnostics.model_validate(diagnostics),
        previewHash=preview_hash(draft, diagnostics),
    )
