from __future__ import annotations

import json
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.settings import SystemEvent
from app.modules.feedback.domain import FeedbackReceipt
from app.modules.feedback.infrastructure import FeedbackDeliveryError


def _login(client: TestClient, db: Session, *, manager: bool) -> None:
    email = "feedback-manager@example.com" if manager else "feedback-reader@example.com"
    db.add(User(
        email=email, name="Feedback tester", password_hash=hash_password("FeedbackTester123!"),
        role="admin" if manager else "member", can_manage_system=manager,
    ))
    db.commit()
    assert client.post("/api/auth/login", json={"email": email, "password": "FeedbackTester123!"}).status_code == 200


def _draft(event_id: str | None = None) -> dict[str, object]:
    return {
        "kind": "issue", "markdown": "### 遇到的现象\n阅读器无法打开图书",
        "contact": {"qq": "123456", "groupName": "Reader", "email": ""},
        "includeEnvironment": True,
        "installationMethod": "manual",
        "clientEnvironment": {
            "client": "web", "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/130.0",
            "platform": "Win32", "languages": ["zh-CN", "en-US"],
            "locale": "zh-CN", "timeZone": "Asia/Shanghai", "viewport": "1280 × 720",
            "screen": "1920 × 1080", "devicePixelRatio": 1.25, "colorDepth": 24,
            "page": "/settings/about",
        },
        "eventId": event_id, "files": [],
    }


def test_feedback_preview_requires_login_and_log_requires_manager(client: TestClient, db_session: Session) -> None:
    event = SystemEvent(level="error", source="reader", action="open", message="Could not open", metadata_json={"taskId": "task-a"})
    db_session.add(event)
    db_session.commit()
    draft = _draft(event.id)
    assert client.post("/api/feedback/preview", json=draft).status_code == 401
    _login(client, db_session, manager=False)
    assert client.post("/api/feedback/preview", json=draft).status_code == 403
    draft["eventId"] = None
    response = client.post("/api/feedback/preview", json=draft)
    assert response.status_code == 200
    assert "log" not in response.json()["data"]["diagnostics"]


def test_feedback_preview_is_bounded_and_submission_matches_review(client: TestClient, db_session: Session, monkeypatch) -> None:
    _login(client, db_session, manager=True)
    selected = SystemEvent(level="error", source="reader", action="open", message="Read failed at 192.168.1.3", target_type="book", target_id="book-a", metadata_json={"taskId": "task-a", "secret": "do-not-send", "diagnostics": {"message": "Read failed"}})
    related = SystemEvent(level="warning", source="reader", action="decode", message="Decode failed", metadata_json={"taskId": "task-a"})
    unrelated = SystemEvent(level="error", source="reader", action="other", message="Unrelated", metadata_json={"taskId": "task-b"})
    db_session.add_all([selected, related, unrelated])
    db_session.commit()
    draft = _draft(selected.id)
    response = client.post("/api/feedback/preview", json=draft)
    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    events = preview["diagnostics"]["log"]["events"]
    assert {row["id"] for row in events} == {selected.id, related.id}
    assert "do-not-send" not in json.dumps(preview)
    assert "192.168.1.3" not in json.dumps(preview)
    assert preview["diagnostics"]["environment"]["appVersion"]
    assert preview["diagnostics"]["environment"]["installationMethod"] == "手动安装"
    assert preview["diagnostics"]["environment"]["userAgent"] == "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/130.0"
    assert preview["diagnostics"]["environment"]["screen"] == "1920 × 1080"

    forwarded = []
    monkeypatch.setattr("app.modules.feedback.presentation.send_to_official_site", lambda payload, attachments: (forwarded.append((payload, attachments)), FeedbackReceipt(id="FB-TEST"))[1])
    submission = {**draft, "previewHash": preview["previewHash"], "submissionKey": str(uuid4())}
    sent = client.post("/api/feedback", data={"draft": json.dumps(submission)})
    assert sent.status_code == 200, sent.text
    assert sent.json()["data"]["id"] == "FB-TEST"
    assert forwarded[0][0]["diagnostics"] == preview["diagnostics"]

    submission["markdown"] = "Changed after review"
    changed = client.post("/api/feedback", data={"draft": json.dumps(submission)})
    assert changed.status_code == 409
    assert len(forwarded) == 1


def test_feedback_environment_requires_a_manual_installation_choice(client: TestClient, db_session: Session) -> None:
    _login(client, db_session, manager=False)
    draft = _draft()
    draft["installationMethod"] = None
    assert client.post("/api/feedback/preview", json=draft).status_code == 400
    draft["installationMethod"] = "app-store"
    preview = client.post("/api/feedback/preview", json=draft)
    assert preview.status_code == 200
    assert preview.json()["data"]["diagnostics"]["environment"]["installationMethod"] == "应用商店安装"


def test_feedback_attachment_bytes_must_match_review(client: TestClient, db_session: Session, monkeypatch) -> None:
    _login(client, db_session, manager=False)
    draft = _draft()
    original = b"expected text"
    draft["files"] = [{"name": "details.txt", "size": len(original), "sha256": sha256(original).hexdigest()}]
    preview = client.post("/api/feedback/preview", json=draft).json()["data"]
    payload = {**draft, "previewHash": preview["previewHash"], "submissionKey": str(uuid4())}
    monkeypatch.setattr("app.modules.feedback.presentation.send_to_official_site", lambda *args: (_ for _ in ()).throw(AssertionError("must not forward")))
    changed = client.post(
        "/api/feedback", data={"draft": json.dumps(payload)},
        files=[("files", ("details.txt", b"unexpected txt", "text/plain"))],
    )
    assert changed.status_code == 409


def test_official_site_failure_is_diagnosed_without_exposing_feedback(client: TestClient, db_session: Session, monkeypatch) -> None:
    _login(client, db_session, manager=False)
    draft = _draft()
    draft["markdown"] = "Private feedback body"
    preview = client.post("/api/feedback/preview", json=draft).json()["data"]

    def broken_transport(*args):
        try:
            raise OSError(111, "connection refused")
        except OSError as error:
            raise FeedbackDeliveryError("Official feedback delivery failed") from error

    monkeypatch.setattr("app.modules.feedback.presentation.send_to_official_site", broken_transport)
    response = client.post("/api/feedback", data={"draft": json.dumps({**draft, "previewHash": preview["previewHash"], "submissionKey": str(uuid4())})})
    assert response.status_code == 503
    assert response.headers.get("X-Error-Id")
    assert "Private feedback body" not in response.text
    db_session.expire_all()
    logged = db_session.scalars(select(SystemEvent).where(SystemEvent.action == "feedback.forward_failed")).all()
    assert logged
    assert "connection refused" in json.dumps(logged[-1].metadata_json)
    assert "Private feedback body" not in json.dumps(logged[-1].metadata_json)
