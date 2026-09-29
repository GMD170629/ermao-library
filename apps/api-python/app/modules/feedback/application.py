from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.exception_diagnostics import sanitize_diagnostic_text

from .domain import FeedbackDraft, FeedbackPreview, preview_hash


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

    def book_titles(self, book_ids: frozenset[str]) -> dict[str, str]: ...


def _safe(value: object, limit: int = 500) -> str:
    if value is None:
        return ""
    sanitized = sanitize_diagnostic_text(value)
    sanitized = re.sub(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", "[ip-redacted]", sanitized)
    sanitized = re.sub(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F]{0,4}(?![\w:])", "[ip-redacted]", sanitized)
    return sanitized[:limit]


def _book_ids(event: dict[str, object]) -> frozenset[str]:
    found: set[str] = set()
    if event.get("targetType") == "book" and isinstance(event.get("targetId"), str):
        found.add(str(event["targetId"]))
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        book_id = metadata.get("bookId")
        if isinstance(book_id, str):
            found.add(book_id)
        book_ids = metadata.get("bookIds")
        if isinstance(book_ids, list):
            found.update(value for value in book_ids[:20] if isinstance(value, str))
    return frozenset(value for value in found if 0 < len(value) <= 191)


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
        book_ids = frozenset().union(*(_book_ids(event) for event in events))
        book_titles = diagnostics_reader.book_titles(book_ids)
        safe_events: list[dict[str, object]] = []
        for event in events:
            metadata = event.get("metadata")
            details = metadata.get("diagnostics") if isinstance(metadata, dict) else None
            detail = details if isinstance(details, dict) else {}
            created_at = event.get("createdAt")
            safe_events.append({
                "id": str(event["id"]),
                "level": _safe(event.get("level"), 20),
                "source": _safe(event.get("source"), 40),
                "action": _safe(event.get("action"), 100),
                "message": _safe(event.get("message")),
                "createdAt": created_at.isoformat() if isinstance(created_at, datetime) else _safe(created_at, 40),
                "stage": _safe(metadata.get("stage") or metadata.get("step"), 100) if isinstance(metadata, dict) else "",
                "exceptionType": _safe(detail.get("exceptionType"), 100),
                "diagnosticMessage": _safe(detail.get("message")),
                "traceback": _safe(detail.get("traceback"), 1500) if event["id"] == draft.event_id else "",
            })
        diagnostics["log"] = {
            "selectedEventId": draft.event_id,
            "events": safe_events,
            "relatedBooks": [
                {"id": book_id, "title": _safe(title, 200)}
                for book_id, title in sorted(book_titles.items())
            ],
        }
    return FeedbackPreview(diagnostics=diagnostics, previewHash=preview_hash(draft, diagnostics))
