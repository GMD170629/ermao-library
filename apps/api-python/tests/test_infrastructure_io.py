# ruff: noqa: S106

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from appv2.modules.accounts.infrastructure.password_reset import LocalPasswordResetNotice
from appv2.modules.delivery.contracts import DeliverableFile, SmtpConfiguration
from appv2.modules.delivery.infrastructure.smtp import SmtpAdapter
from appv2.modules.discovery.contracts import SearchResultView, SourceView
from appv2.modules.discovery.infrastructure.adapters import (
    HttpDownloadAdapter,
    JsonHttpSourceSearch,
)
from appv2.modules.operations.contracts import BackupView, RestoreRequest
from appv2.modules.operations.infrastructure.backup import (
    FileRestoreControl,
    PgBackupExecutor,
)
from appv2.modules.operations.infrastructure.restore import (
    FileRestoreInbox,
    PgRestoreExecutor,
)


def backup_view(
    root: Path,
    *,
    archive_name: str = "backup.dump",
    checksum: str | None = None,
) -> BackupView:
    del root
    now = datetime.now(UTC)
    return BackupView(
        id=uuid.uuid4(),
        status="ready" if checksum else "queued",
        archive_name=archive_name,
        app_version="0.4.0",
        postgres_major=18,
        alembic_revision="0001_appv2_initial",
        checksum=checksum,
        size_bytes=None,
        error_detail=None,
        created_at=now,
        updated_at=now,
    )


def test_local_password_reset_notice_is_atomic_localized_and_private(tmp_path: Path) -> None:
    notice = LocalPasswordResetNotice(tmp_path / "control")
    path = notice.write(
        reset_url="https://books.example/reset-password#token=one&value=two",
        locale="en-US",
    )
    document = path.read_text(encoding="utf-8")
    assert "Reset password" in document
    assert "one&amp;value=two" in document
    assert path.stat().st_mode & 0o777 == 0o600
    notice.write(
        reset_url="https://books.example/reset-password#token=three",
        locale="zh-CN",
    )
    assert "重置密码" in path.read_text(encoding="utf-8")
    notice.clear()
    assert not path.exists()
    notice.clear()


def test_pg_backup_executor_create_open_delete_and_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "backups"
    executor = PgBackupExecutor(
        database_url="postgresql+psycopg://app:secret@postgres/app",
        backups_root=root,
    )
    backup = backup_view(root)
    monkeypatch.setattr(
        "appv2.modules.operations.infrastructure.backup.shutil.which",
        lambda _name: None,
    )
    with pytest.raises(RuntimeError, match="pg_dump"):
        executor.create(backup)

    monkeypatch.setattr(
        "appv2.modules.operations.infrastructure.backup.shutil.which",
        lambda _name: "/usr/bin/pg_dump",
    )

    def fake_run(command: list[str], **_kwargs: object) -> None:
        output = next(value.split("=", 1)[1] for value in command if value.startswith("--file="))
        Path(output).write_bytes(b"postgres-custom-backup")

    monkeypatch.setattr(
        "appv2.modules.operations.infrastructure.backup.subprocess.run",
        fake_run,
    )
    checksum, size = executor.create(backup)
    assert checksum == hashlib.sha256(b"postgres-custom-backup").hexdigest()
    assert size == len(b"postgres-custom-backup")
    manifest = json.loads((root / "backup.dump.json").read_text(encoding="utf-8"))
    assert manifest["postgres_major"] == 18

    ready = backup_view(root, checksum=checksum)
    archive = executor.open(ready)
    assert b"".join(archive.body) == b"postgres-custom-backup"
    executor.delete(ready)
    assert not (root / "backup.dump").exists()
    with pytest.raises(FileNotFoundError):
        executor.open(ready)
    with pytest.raises(ValueError, match="escapes"):
        executor.open(backup_view(root, archive_name="../outside.dump", checksum=checksum))


def test_restore_control_inbox_and_executor_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backups = tmp_path / "backups"
    control = tmp_path / "control"
    backups.mkdir()
    backup = backup_view(backups, checksum="checksum")
    restore_control = FileRestoreControl(control_root=control, backups_root=backups)
    with pytest.raises(ValueError, match="does not exist"):
        restore_control.request(backup, uuid.uuid4())

    archive = backups / backup.archive_name
    archive.write_bytes(b"archive")
    request_id = restore_control.request(backup, uuid.uuid4())
    inbox = FileRestoreInbox(control)
    request = inbox.next_request()
    assert request is not None
    assert request.request_id == request_id
    inbox.fail(request, "restore failed")
    result = json.loads((control / f"restore-{request_id}.result.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert inbox.next_request() is None

    request_id = restore_control.request(backup, uuid.uuid4())
    request = inbox.next_request()
    assert request is not None
    inbox.complete(request)
    result = json.loads((control / f"restore-{request_id}.result.json").read_text(encoding="utf-8"))
    assert result["status"] == "completed"

    checksum = hashlib.sha256(b"archive").hexdigest()
    executor = PgRestoreExecutor(
        database_url="postgresql+psycopg://app:secret@postgres/app",
        backups_root=backups,
        backend_root=tmp_path,
        expected_version="0.4.0",
    )

    def restore_request(**overrides: object) -> RestoreRequest:
        values: dict[str, object] = {
            "request_id": "request",
            "backup_id": backup.id,
            "archive": str(archive),
            "checksum": checksum,
            "app_version": "0.4.0",
            "postgres_major": 18,
            "alembic_revision": "0001_appv2_initial",
        }
        values.update(overrides)
        return RestoreRequest(**values)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="outside"):
        executor.execute(restore_request(archive=str(tmp_path / "outside.dump")))
    with pytest.raises(ValueError, match="PostgreSQL 18"):
        executor.execute(restore_request(postgres_major=17))
    with pytest.raises(ValueError, match="version"):
        executor.execute(restore_request(app_version="0.3.0"))
    with pytest.raises(ValueError, match="checksum"):
        executor.execute(restore_request(checksum="wrong"))
    monkeypatch.setattr(
        "appv2.modules.operations.infrastructure.restore.shutil.which",
        lambda _name: None,
    )
    with pytest.raises(RuntimeError, match="pg_restore"):
        executor.execute(restore_request())

    run = MagicMock()
    upgrade = MagicMock()
    monkeypatch.setattr(
        "appv2.modules.operations.infrastructure.restore.shutil.which",
        lambda _name: "/usr/bin/pg_restore",
    )
    monkeypatch.setattr(
        "appv2.modules.operations.infrastructure.restore.subprocess.run",
        run,
    )
    monkeypatch.setattr(
        "appv2.modules.operations.infrastructure.restore.command.upgrade",
        upgrade,
    )
    executor.execute(restore_request())
    run.assert_called_once()
    upgrade.assert_called_once()


def test_json_http_search_and_download_adapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    source = SourceView(
        id=uuid.uuid4(),
        name="Source",
        kind="json-http",
        base_url="https://source.example/api",
        enabled=True,
        config={
            "searchPath": "/search?language=zh",
            "queryParam": "keyword",
            "resultsPath": "payload.books",
        },
        created_at=now,
        updated_at=now,
    )
    response = MagicMock()
    response.content = json.dumps(
        {
            "payload": {
                "books": [
                    {
                        "id": "book-1",
                        "title": " Book One ",
                        "author": "Author",
                        "downloadUrl": "https://source.example/files/book.epub",
                    },
                    {"id": "empty-title"},
                    "invalid",
                ]
            }
        }
    ).encode()
    monkeypatch.setattr(
        "appv2.modules.discovery.infrastructure.adapters.httpx.get",
        lambda *_args, **_kwargs: response,
    )
    results = JsonHttpSourceSearch(10).search(source, "architecture")
    assert len(results) == 1
    assert results[0].title == "Book One"
    response.raise_for_status.assert_called_once()
    response.content = json.dumps({"payload": {"books": {}}}).encode()
    with pytest.raises(ValueError, match="result list"):
        JsonHttpSourceSearch(10).search(source, "architecture")

    result = SearchResultView(
        id=uuid.uuid4(),
        source_id=source.id,
        external_id="book-1",
        title="Book One",
        author="Author",
        download_url=None,
        info_url=None,
        payload={},
        state="available",
        created_at=now,
    )
    downloader = HttpDownloadAdapter(tmp_path, 10)
    with pytest.raises(ValueError, match="no download URL"):
        downloader.download(result)
    invalid = SimpleNamespace(
        id=result.id,
        download_url="file:///tmp/book.epub",
    )
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        downloader.download(invalid)

    downloadable = SimpleNamespace(
        **{
            "id": result.id,
            "download_url": "https://source.example/files/book.epub",
        }
    )
    stream_response = MagicMock()
    stream_response.__enter__.return_value = stream_response
    stream_response.__exit__.return_value = None
    stream_response.iter_bytes.return_value = [b"epub-", b"content"]
    monkeypatch.setattr(
        "appv2.modules.discovery.infrastructure.adapters.httpx.stream",
        lambda *_args, **_kwargs: stream_response,
    )
    destination = Path(downloader.download(downloadable))
    assert destination.read_bytes() == b"epub-content"
    stream_response.raise_for_status.assert_called_once()


def test_smtp_adapter_builds_test_and_attachment_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp_client = MagicMock()
    smtp_context = MagicMock()
    smtp_context.__enter__.return_value = smtp_client
    smtp_context.__exit__.return_value = None
    smtp_factory = MagicMock(return_value=smtp_context)
    monkeypatch.setattr(
        "appv2.modules.delivery.infrastructure.smtp.smtplib.SMTP",
        smtp_factory,
    )
    configuration = SmtpConfiguration(
        host="smtp.example.com",
        port=587,
        username="mailer",
        password="secret",
        sender="sender@example.com",
        use_tls=True,
    )
    adapter = SmtpAdapter(15)
    adapter.test(configuration, "recipient@example.com")
    smtp_client.starttls.assert_called_once()
    smtp_client.login.assert_called_once_with("mailer", "secret")
    smtp_client.send_message.assert_called_once()

    attachment = tmp_path / "book.epub"
    attachment.write_bytes(b"epub")
    deliverable = DeliverableFile(
        file_id=uuid.uuid4(),
        name="book.epub",
        media_type="application/epub+zip",
        size_bytes=4,
        path=str(attachment),
        checksum="a" * 64,
    )
    adapter.send(
        SmtpConfiguration(
            host="smtp.example.com",
            port=25,
            username=None,
            password=None,
            sender="sender@example.com",
            use_tls=False,
        ),
        recipient="reader@example.com",
        subject="Book",
        file=deliverable,
    )
    sent_message = smtp_client.send_message.call_args_list[-1].args[0]
    assert sent_message.get_filename() is None
    assert list(sent_message.iter_attachments())[0].get_filename() == "book.epub"
