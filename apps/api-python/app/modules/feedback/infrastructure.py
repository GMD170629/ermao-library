"""Official-site HTTPS transport for feedback submissions."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import release_read_transaction

from .domain import FeedbackReceipt
from .receiver_endpoint import RECEIVER_URL


class FeedbackDeliveryError(Exception):
    pass


@dataclass(frozen=True)
class Attachment:
    name: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class DatabaseFeedbackDiagnostics:
    db: Session
    book_titles_lookup: Callable[[Session, frozenset[str]], dict[str, str]]
    event_bundle_lookup: Callable[[Session, str], list[dict[str, object]]]

    def event_bundle(self, event_id: str) -> list[dict[str, object]]:
        return self.event_bundle_lookup(self.db, event_id)

    def book_titles(self, book_ids: frozenset[str]) -> dict[str, str]:
        titles = self.book_titles_lookup(self.db, book_ids)
        release_read_transaction(self.db)
        return titles


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise FeedbackDeliveryError("Receiver redirected feedback")


def send_to_official_site(payload: dict[str, object], attachments: tuple[Attachment, ...]) -> FeedbackReceipt:
    if not RECEIVER_URL:
        raise FeedbackDeliveryError("Feedback receiver is not configured")
    boundary = f"ermao-{uuid4().hex}"
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload\"\r\n\r\n".encode(),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        b"\r\n",
    ]
    for attachment in attachments:
        safe_name = attachment.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks.extend((
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{safe_name}\"\r\nContent-Type: {attachment.media_type}\r\n\r\n".encode(),
            attachment.content,
            b"\r\n",
        ))
    chunks.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        RECEIVER_URL,
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=35) as response:
            value: object = json.loads(response.read(2048))
        return FeedbackReceipt.model_validate(value)
    except (OSError, urllib.error.URLError, ValueError, ValidationError) as error:
        raise FeedbackDeliveryError("Official feedback delivery failed") from error
