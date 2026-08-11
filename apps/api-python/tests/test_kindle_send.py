from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from pathlib import Path

from app.bootstrap.kindle import recover_interrupted_kindle_tasks_command
from app.bootstrap.system import prepare_system_event
from app.core.auth import hash_password
from app.db.base import Base
from app.db.bootstrap import apply_schema
from app.models.auth import User
from app.models.import_pipeline import KindleSendTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.services import email_settings, kindle_queue
from app.services.kindle_queue import (
    process_next_kindle_send_task,
    recover_interrupted_tasks,
)
from sqlalchemy import select, text
from tests.support.sqlalchemy import StatementRecorder


def _apply_full_schema(db_session) -> None:
    db_session.rollback()
    Base.metadata.create_all(db_session.get_bind())
    apply_schema(db_session.get_bind())


def _login(client, db_session) -> None:
    user = User(
        email="kindle-admin@example.com",
        name="管理员",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login", json={"email": user.email, "password": "starshipnas"}
    )
    assert response.status_code == 200


def _prepare(
    client, db_session, test_settings, *, max_attachment_mb: float | None = None
) -> Path:
    _apply_full_schema(db_session)
    _login(client, db_session)
    smtp = {
        "host": "smtp.example.com",
        "port": 587,
        "security": "starttls",
        "username": "sender@example.com",
        "password": "smtp-secret",
        "fromEmail": "sender@example.com",
        "fromName": "二毛图书",
        "maxAttachmentMb": max_attachment_mb,
    }
    saved = client.put(
        "/api/email-settings",
        json={"smtp": smtp, "kindle": {"email": "reader_123@kindle.com"}},
    )
    assert saved.status_code == 200
    personal = client.put(
        "/api/kindle-settings", json={"email": "reader_123@kindle.com"}
    )
    assert personal.status_code == 200
    path = (
        test_settings.resolved_storage_root
        / "books"
        / "work-kindle"
        / "volume-kindle"
        / "book.epub"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"epub fixture")
    work = LibraryWork(
        id="work-kindle",
        title="Kindle Test Book",
        normalized_title="kindle test book",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    media_version = LibraryMediaVersion(
        id="media-kindle",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volume = LibraryVolume(
        id="volume-kindle",
        media_version_id=media_version.id,
        title="EPUB",
        sort_order=0,
        format="EPUB",
        resource_key="epub-main",
        import_status="COMPLETED",
        size_bytes=path.stat().st_size,
    )
    file = LibraryFile(
        id="file-kindle",
        volume_id=volume.id,
        path=str(path.relative_to(test_settings.resolved_storage_root)),
        hash_status="COMPLETED",
        mtime_ms=1,
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=path.stat().st_size,
        sort_order=0,
    )
    db_session.add_all([work, media_version, volume, file])
    db_session.commit()
    return path


def _enqueue(client):
    response = client.post(
        "/api/kindle-send-tasks",
        json={"workId": "work-kindle", "fileId": "file-kindle"},
    )
    assert response.status_code == 201
    return response.json()["data"]["task"]


def test_recover_interrupted_kindle_tasks_uses_set_based_dml(db_session) -> None:
    _apply_full_schema(db_session)
    task_ids = tuple(f"bulk-kindle-{index}" for index in range(25))
    db_session.add_all(
        [
            KindleSendTask(
                id=task_id,
                book_title=f"Book {index}",
                file_name=f"book-{index}.epub",
                format="EPUB",
                mime_type="application/epub+zip",
                size_bytes=1,
                recipient_email="reader@example.test",
                subject=f"Book {index}",
                status="sending",
            )
            for index, task_id in enumerate(task_ids)
        ]
    )
    db_session.commit()
    timestamp = datetime.now(UTC)
    events = tuple(
        prepare_system_event(
            source="kindle",
            action="send.unknown",
            target_type="kindleSendTask",
            target_id=task_id,
            message="Kindle send outcome unknown",
        )
        for task_id in task_ids
    )

    with StatementRecorder(db_session.get_bind()) as recorder:
        recorder.reset_after_warmup()
        recover_interrupted_kindle_tasks_command(
            db_session,
            task_ids=task_ids,
            error_message="interrupted",
            timestamp=timestamp,
            events=events,
        )

    assert recorder.dml_count == 2
    assert set(
        db_session.scalars(
            select(KindleSendTask.id).where(KindleSendTask.status == "unknown")
        )
    ) == set(task_ids)


class FakeSmtp:
    def __init__(self, *, send_error: BaseException | None = None) -> None:
        self.send_error = send_error
        self.messages = []
        self.noop_called = False

    def noop(self):
        self.noop_called = True
        return 250, b"ok"

    def send_message(self, message):
        if self.send_error:
            raise self.send_error
        self.messages.append(message)
        return {}

    def quit(self):
        return 221, b"bye"

    def close(self):
        return None


def test_email_settings_mask_password_test_connection_and_clear(
    client, db_session, monkeypatch
):
    _apply_full_schema(db_session)
    _login(client, db_session)
    saved = client.put(
        "/api/email-settings",
        json={
            "smtp": {
                "host": "smtp.example.com",
                "port": 465,
                "security": "ssl",
                "username": "sender@example.com",
                "password": "smtp-secret",
                "fromEmail": "sender@example.com",
                "fromName": "二毛图书",
            },
            "kindle": {"email": "reader_123@kindle.com"},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["smtp"]["passwordConfigured"] is True
    assert "smtp-secret" not in saved.text

    fake = FakeSmtp()
    monkeypatch.setattr(
        email_settings, "open_smtp_connection", lambda _config, timeout=30: fake
    )
    tested = client.post("/api/email-settings/smtp-test", json={})
    assert tested.status_code == 200
    assert fake.noop_called is True

    loaded = client.get("/api/email-settings")
    assert loaded.json()["data"]["kindle"]["email"] == "reader_123@kindle.com"
    assert "smtp-secret" not in loaded.text
    cleared = client.put("/api/email-settings", json={"clearSmtpPassword": True})
    assert cleared.json()["data"]["smtp"]["passwordConfigured"] is False
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM `SystemSetting` WHERE `key` = 'email.smtp.password'"
            )
        ).scalar()
        == 0
    )
    events = "\n".join(
        str(row[0])
        for row in db_session.execute(text("SELECT `metadata` FROM `SystemEvent`"))
    )
    assert "smtp-secret" not in events


def test_enqueue_deduplicates_and_rejects_unsupported_files(
    client, db_session, test_settings
):
    _prepare(client, db_session, test_settings)
    created = _enqueue(client)
    assert created["status"] == "queued"
    assert created["recipientEmail"] == "reader_123@kindle.com"
    duplicate = client.post(
        "/api/kindle-send-tasks",
        json={"workId": "work-kindle", "fileId": "file-kindle"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["alreadyQueued"] is True
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM `KindleSendTask`")).scalar() == 1
    )

    comic_path = (
        test_settings.resolved_storage_root
        / "books"
        / "work-kindle"
        / "volume-kindle"
        / "comic.cbz"
    )
    comic_path.write_bytes(b"comic")
    db_session.add(
        LibraryFile(
            id="file-comic",
            volume_id="volume-kindle",
            path=str(comic_path.relative_to(test_settings.resolved_storage_root)),
            hash_status="COMPLETED",
            mtime_ms=1,
            kind="COMIC",
            mime_type="application/zip",
            size_bytes=5,
            sort_order=1,
        )
    )
    db_session.commit()
    unsupported = client.post(
        "/api/kindle-send-tasks", json={"workId": "work-kindle", "fileId": "file-comic"}
    )
    assert unsupported.status_code == 400
    assert "EPUB 和 PDF" in unsupported.json()["error"]["message"]


def test_kindle_email_and_send_queue_are_personal_while_smtp_remains_system_managed(
    client,
    db_session,
    test_settings,
):
    _prepare(client, db_session, test_settings)
    member = User(
        email="kindle-member@example.com",
        name="普通用户",
        password_hash=hash_password("starshipnas"),
        role="member",
        can_view_manual_imports=True,
    )
    db_session.add(member)
    db_session.commit()
    assert client.post("/api/auth/logout").status_code == 200
    assert (
        client.post(
            "/api/auth/login",
            json={"email": member.email, "password": "starshipnas"},
        ).status_code
        == 200
    )

    assert client.get("/api/email-settings").status_code == 403
    saved = client.put("/api/kindle-settings", json={"email": "member_456@kindle.com"})
    assert saved.status_code == 200
    assert saved.json()["data"]["kindle"]["email"] == "member_456@kindle.com"
    created = _enqueue(client)
    assert created["userId"] == member.id
    assert created["recipientEmail"] == "member_456@kindle.com"
    assert client.get("/api/kindle-send-tasks").json()["data"]["total"] == 1

    assert client.post("/api/auth/logout").status_code == 200
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "kindle-admin@example.com", "password": "starshipnas"},
        ).status_code
        == 200
    )
    assert client.get("/api/kindle-send-tasks").json()["data"]["total"] == 0
    assert (
        client.post(f"/api/kindle-send-tasks/{created['id']}/cancel").status_code == 404
    )


def test_enqueue_rejects_attachment_above_configured_limit(
    client, db_session, test_settings
):
    path = _prepare(client, db_session, test_settings, max_attachment_mb=1)
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    db_session.execute(
        text("UPDATE `LibraryFile` SET `sizeBytes` = :size WHERE `id` = 'file-kindle'"),
        {"size": path.stat().st_size},
    )
    db_session.commit()
    rejected = client.post(
        "/api/kindle-send-tasks",
        json={"workId": "work-kindle", "fileId": "file-kindle"},
    )
    assert rejected.status_code == 400
    assert "1 MB" in rejected.json()["error"]["message"]


def test_worker_submits_mime_message_and_logs_masked_recipient(
    client, db_session, test_settings, monkeypatch
):
    _prepare(client, db_session, test_settings)
    db_session.execute(
        text(
            "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
            "VALUES ('language', 'en-US', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = excluded.`updatedAt`"
        )
    )
    db_session.commit()
    task = _enqueue(client)
    fake = FakeSmtp()
    monkeypatch.setattr(kindle_queue, "open_smtp_connection", lambda _config: fake)
    assert process_next_kindle_send_task(db_session, test_settings) is True
    stored = (
        db_session.execute(
            text("SELECT * FROM `KindleSendTask` WHERE `id` = :id"), {"id": task["id"]}
        )
        .mappings()
        .one()
    )
    assert stored["status"] == "sent"
    assert stored["attemptCount"] == 1
    assert stored["messageId"]
    assert len(fake.messages) == 1
    message = fake.messages[0]
    assert message["To"] == "reader_123@kindle.com"
    assert message["Subject"] == "Kindle Test Book"
    assert "Ermao Books" in message["From"]
    assert message.get_content_maintype() == "multipart"
    assert (
        "has been sent to Kindle by Ermao Books"
        in message.get_body(preferencelist=("plain",)).get_content()
    )
    assert message.get_payload()[-1].get_filename() == "book.epub"
    events = "\n".join(
        str(row[0])
        for row in db_session.execute(
            text("SELECT `metadata` FROM `SystemEvent` WHERE `source` = 'kindle'")
        )
    )
    assert "reader_123@kindle.com" not in events
    assert "r***3@kindle.com" in events


def test_worker_does_not_retry_permanent_authentication_failure(
    client, db_session, test_settings, monkeypatch
):
    _prepare(client, db_session, test_settings)
    task = _enqueue(client)
    failing = FakeSmtp(
        send_error=smtplib.SMTPAuthenticationError(535, b"bad credentials")
    )
    monkeypatch.setattr(kindle_queue, "open_smtp_connection", lambda _config: failing)
    assert process_next_kindle_send_task(db_session, test_settings) is True
    stored = (
        db_session.execute(
            text(
                "SELECT `status`, `attemptCount`, `nextAttemptAt` FROM `KindleSendTask` WHERE `id` = :id"
            ),
            {"id": task["id"]},
        )
        .mappings()
        .one()
    )
    assert stored["status"] == "failed"
    assert stored["attemptCount"] == 1
    assert stored["nextAttemptAt"] is None


def test_worker_retries_transient_failure_and_recovers_interrupted_send(
    client, db_session, test_settings, monkeypatch
):
    _prepare(client, db_session, test_settings)
    task = _enqueue(client)
    failing = FakeSmtp(send_error=smtplib.SMTPServerDisconnected("temporary outage"))
    monkeypatch.setattr(kindle_queue, "open_smtp_connection", lambda _config: failing)
    assert process_next_kindle_send_task(db_session, test_settings) is True
    stored = (
        db_session.execute(
            text(
                "SELECT `status`, `attemptCount`, `nextAttemptAt`, `errorMessage` FROM `KindleSendTask` WHERE `id` = :id"
            ),
            {"id": task["id"]},
        )
        .mappings()
        .one()
    )
    assert stored["status"] == "queued"
    assert stored["attemptCount"] == 1
    assert stored["nextAttemptAt"] is not None
    assert "temporary outage" in stored["errorMessage"]

    for expected_attempt in (2, 3):
        db_session.execute(
            text("UPDATE `KindleSendTask` SET `nextAttemptAt` = NULL WHERE `id` = :id"),
            {"id": task["id"]},
        )
        db_session.commit()
        assert process_next_kindle_send_task(db_session, test_settings) is True
        stored = (
            db_session.execute(
                text(
                    "SELECT `status`, `attemptCount` FROM `KindleSendTask` WHERE `id` = :id"
                ),
                {"id": task["id"]},
            )
            .mappings()
            .one()
        )
        assert stored["attemptCount"] == expected_attempt
    assert stored["status"] == "failed"

    db_session.execute(
        text("UPDATE `KindleSendTask` SET `status` = 'sending' WHERE `id` = :id"),
        {"id": task["id"]},
    )
    db_session.commit()
    assert recover_interrupted_tasks(db_session) == 1
    recovered = (
        db_session.execute(
            text(
                "SELECT `status`, `errorMessage` FROM `KindleSendTask` WHERE `id` = :id"
            ),
            {"id": task["id"]},
        )
        .mappings()
        .one()
    )
    assert recovered["status"] == "unknown"
    assert "结果未知" in recovered["errorMessage"]

    retried = client.post(f"/api/kindle-send-tasks/{task['id']}/retry")
    assert retried.status_code == 200
    cancelled = client.post(f"/api/kindle-send-tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200
    deleted = client.delete(f"/api/kindle-send-tasks/{task['id']}")
    assert deleted.status_code == 200
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM `KindleSendTask` WHERE `id` = :id"),
            {"id": task["id"]},
        ).scalar()
        == 0
    )
