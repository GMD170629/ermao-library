from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from receiver.app import create_app
from receiver.config import Settings
from receiver.contracts import Submission
from receiver.delivery import send_feedback
from receiver.models import FeedbackRecord
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _payload(key: str | None = None) -> dict[str, object]:
    return {
        "submissionKey": key or str(uuid4()),
        "kind": "issue",
        "markdown": "The reader closed unexpectedly",
        "contact": {"qq": "123456", "groupName": "Reader", "email": ""},
        "diagnostics": {"environment": {"appVersion": "1.5.1"}},
    }


def _post(client: TestClient, payload: dict[str, object], files=()):
    return client.post("/api/feedback", data={"payload": json.dumps(payload)}, files=files)


def _records(root: Path) -> list[FeedbackRecord]:
    engine = create_engine(f"sqlite:///{(root / 'feedback.sqlite3').as_posix()}")
    with Session(engine) as db:
        return list(db.scalars(select(FeedbackRecord)).all())


def test_delivery_persists_record_then_discards_files(tmp_path: Path, monkeypatch) -> None:
    delivered = []

    def fake_send(settings, receipt_id, submission, files):
        delivered.append((receipt_id, submission.markdown, [(name, path.read_bytes()) for name, _, path in files]))

    monkeypatch.setattr("receiver.app.send_feedback", fake_send)
    with TestClient(create_app(Settings(data_root=tmp_path))) as client:
        payload = _payload()
        files = [("files", ("capture.png", b"\x89PNG\r\n\x1a\nimage", "image/png"))]
        response = _post(client, payload, files)
        assert response.status_code == 200
        receipt = response.json()["id"]
        assert delivered == [(receipt, payload["markdown"], [("capture.png", b"\x89PNG\r\n\x1a\nimage")])]
        assert _post(client, payload, files).json()["id"] == receipt
        assert len(delivered) == 1
    record = _records(tmp_path)[0]
    assert record.status == "sent" and record.attempts == 1
    assert record.markdown == payload["markdown"]
    assert not list((tmp_path / "temporary-files").iterdir())


def test_failed_delivery_can_retry_with_same_key_and_cleans_files(tmp_path: Path, monkeypatch, caplog) -> None:
    calls = 0

    def flaky_send(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("SMTP unavailable")

    monkeypatch.setattr("receiver.app.send_feedback", flaky_send)
    with TestClient(create_app(Settings(data_root=tmp_path))) as client:
        payload = _payload()
        files = [("files", ("note.txt", b"some diagnostic text", "text/plain"))]
        assert _post(client, payload, files).status_code == 503
        assert _records(tmp_path)[0].status == "failed"
        assert not list((tmp_path / "temporary-files").iterdir())
        assert _post(client, payload, files).status_code == 200
    assert calls == 2
    assert _records(tmp_path)[0].attempts == 2
    assert "The reader closed unexpectedly" not in caplog.text
    assert "secret" not in caplog.text


def test_rejects_invalid_or_oversize_files_and_changed_retry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("receiver.app.send_feedback", lambda *args: None)
    with TestClient(create_app(Settings(data_root=tmp_path))) as client:
        bad = _post(client, _payload(), [("files", ("note.pdf", b"fake pdf", "application/pdf"))])
        assert bad.status_code == 400
        huge = _post(client, _payload(), [("files", ("note.txt", b"a" * (10 * 1024 * 1024 + 1), "text/plain"))])
        assert huge.status_code == 413
        assert not list((tmp_path / "temporary-files").iterdir())
        original = _payload()
        assert _post(client, original).status_code == 200
        changed = {**original, "markdown": "Changed text"}
        assert _post(client, changed).status_code == 409


def test_email_contains_reviewed_text_diagnostics_and_attachment(tmp_path: Path, monkeypatch) -> None:
    sent = []

    class SMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.example.test", 587, 25)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self, context):
            assert context is not None

        def login(self, username, password):
            assert (username, password) == ("sender", "secret")

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("receiver.delivery.smtplib.SMTP", SMTP)
    attachment = tmp_path / "note.txt"
    attachment.write_text("attachment content", encoding="utf-8")
    settings = Settings(
        data_root=tmp_path, smtp_host="smtp.example.test", smtp_username="sender",
        smtp_password="secret", smtp_from="sender@example.test", smtp_to="owner@gmail.com",
    )
    send_feedback(settings, "FB-TEST", Submission.model_validate(_payload()), [("note.txt", "text/plain", attachment)])
    assert len(sent) == 1
    message = sent[0]
    assert message["To"] == "owner@gmail.com"
    assert "FB-TEST" in message["Subject"]
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "The reader closed unexpectedly" in body
    assert "appVersion" in body
    assert "123456" in body
    assert message.iter_attachments().__next__().get_payload(decode=True) == b"attachment content"


def test_startup_removes_interrupted_temporary_upload(tmp_path: Path) -> None:
    orphan = tmp_path / "temporary-files" / "submission-interrupted"
    orphan.mkdir(parents=True)
    (orphan / "partial").write_bytes(b"private attachment")
    create_app(Settings(data_root=tmp_path))
    assert not orphan.exists()


def test_receiver_limits_repeated_requests(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("receiver.app.send_feedback", lambda *args: None)
    with TestClient(create_app(Settings(data_root=tmp_path))) as client:
        payload = _payload()
        for _ in range(10):
            assert _post(client, payload).status_code == 200
        assert _post(client, payload).status_code == 429
