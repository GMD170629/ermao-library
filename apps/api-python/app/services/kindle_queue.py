from __future__ import annotations

import mimetypes
import smtplib
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.bootstrap.kindle import (
    claim_kindle_send_task_command,
    complete_kindle_send_task_command,
    fail_kindle_send_task_command,
    recover_interrupted_kindle_tasks_command,
    schedule_kindle_retry_command,
    update_kindle_send_snapshot_command,
)
from app.bootstrap.system import prepare_system_event
from app.core.config import Settings
from app.core.i18n import configured_locale
from app.core.safe_errors import mask_email, safe_error_message
from app.core.time import now_timestamp_ms
from app.modules.kindle.infrastructure.tasks import (
    get_kindle_send_task,
    get_library_file_for_kindle,
    list_sending_kindle_tasks,
    next_queued_kindle_task,
)
from app.services.email_settings import (
    EmailSettingsError,
    get_email_settings,
    open_smtp_connection,
    smtp_connection_settings,
)
from app.services.queue_runtime import QueueHeartbeatPump

MAX_SEND_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (30, 120)
SUPPORTED_FORMATS = {"EPUB", "PDF"}
SUPPORTED_EXTENSIONS = {".epub", ".pdf"}
TERMINAL_STATUSES = {"sent", "failed", "cancelled", "unknown"}


class KindleSendError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


def _stored_path(path_value: Any, settings: Settings) -> Path | None:
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.is_absolute():
        path = settings.resolved_storage_root / path
    try:
        resolved = path.expanduser().resolve()
        storage_root = settings.resolved_storage_root.resolve()
        if (
            resolved == storage_root
            or storage_root in resolved.parents
            or path.is_absolute()
        ):
            return resolved
    except OSError:
        return None
    return None


def _task(db: Session, task_id: str) -> dict[str, Any] | None:
    return get_kindle_send_task(db, task_id)


def next_queued_task(db: Session) -> dict[str, Any] | None:
    try:
        return next_queued_kindle_task(db, now_timestamp_ms())
    except SQLAlchemyError:
        return None


def _claim_task(db: Session, task_id: str) -> dict[str, Any] | None:
    claimed_at = datetime.now(UTC)
    return claim_kindle_send_task_command(
        db, task_id, timestamp=claimed_at
    )


def _file_for_task(db: Session, task: dict[str, Any]) -> dict[str, Any]:
    file_id = task.get("fileId")
    if not file_id:
        raise KindleSendError("附件记录已不存在")
    row = get_library_file_for_kindle(db, str(file_id))
    if not row:
        raise KindleSendError("附件记录已不存在")
    return row


def _smtp_error(exc: BaseException, config_password: str) -> KindleSendError:
    safe = safe_error_message(exc, [config_password])
    if isinstance(
        exc,
        (
            smtplib.SMTPAuthenticationError,
            smtplib.SMTPNotSupportedError,
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
        ),
    ):
        return KindleSendError(safe)
    if isinstance(exc, smtplib.SMTPResponseException):
        return KindleSendError(safe, transient=int(exc.smtp_code) < 500)
    if isinstance(
        exc,
        (
            TimeoutError,
            OSError,
            smtplib.SMTPServerDisconnected,
            smtplib.SMTPConnectError,
        ),
    ):
        return KindleSendError(safe, transient=True)
    if isinstance(exc, (EmailSettingsError, ValueError)):
        return KindleSendError(safe)
    return KindleSendError(safe, transient=False)


def _prepared_event(
    task: dict[str, Any],
    *,
    action: str,
    message: str,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> Any:
    return prepare_system_event(
        source="kindle",
        action=action,
        message=message,
        level=level,
        actor_type="system",
        target_type="kindleSendTask",
        target_id=str(task.get("id") or ""),
        metadata={
            "workId": task.get("workId"),
            "fileId": task.get("fileId"),
            "fileName": task.get("fileName"),
            "format": task.get("format"),
            "sizeBytes": task.get("sizeBytes"),
            "recipientEmail": mask_email(task.get("recipientEmail")),
            **(metadata or {}),
        },
    )


def _update_send_snapshot(
    db: Session, task_id: str, config: Any, message_id: str
) -> dict[str, Any]:
    now = datetime.now(UTC)
    task = update_kindle_send_snapshot_command(
        db,
        task_id,
        sender_email=config.from_email,
        smtp_host=config.host,
        smtp_port=config.port,
        smtp_security=config.security,
        smtp_username=config.username or None,
        message_id=message_id,
        timestamp=now,
    )
    return task or {"id": task_id}


def _send_task(db: Session, settings: Settings, task: dict[str, Any]) -> None:
    file_id = task.get("fileId")
    if not file_id:
        raise KindleSendError("附件记录已不存在")
    values = get_email_settings(db, include_password=True)
    file_row = get_library_file_for_kindle(db, str(file_id))
    locale = configured_locale(db)
    db.close()
    if not file_row:
        raise KindleSendError("附件记录已不存在")
    config = smtp_connection_settings(values)
    path = _stored_path(file_row.get("path"), settings)
    if path is None or not path.is_file():
        raise KindleSendError("附件文件已不存在或不在受管理目录中")
    file_format = str(task.get("format") or file_row.get("volumeFormat") or "").upper()
    suffix = path.suffix.lower()
    if file_format not in SUPPORTED_FORMATS or suffix not in SUPPORTED_EXTENSIONS:
        raise KindleSendError("Kindle 邮件发送目前仅支持 EPUB 和 PDF")
    if (
        config.max_attachment_mb is not None
        and path.stat().st_size > config.max_attachment_mb * 1024 * 1024
    ):
        raise KindleSendError(
            f"附件超过已配置的 {config.max_attachment_mb:g} MB 大小上限"
        )

    message = EmailMessage()
    message_id = make_msgid()
    message["Message-ID"] = message_id
    fallback_subject = "Send to Kindle" if locale == "en-US" else "发送到 Kindle"
    message["Subject"] = str(
        task.get("subject") or task.get("bookTitle") or fallback_subject
    )
    sender_name = (
        "Ermao Books"
        if locale == "en-US" and config.from_name == "二毛图书"
        else config.from_name
    )
    message["From"] = formataddr((sender_name, config.from_email))
    message["To"] = str(task.get("recipientEmail") or "")
    book_title = str(task.get("bookTitle") or ("Book" if locale == "en-US" else "图书"))
    if locale == "en-US":
        message.set_content(f"“{book_title}” has been sent to Kindle by Ermao Books.")
    else:
        message.set_content(f"《{book_title}》已由二毛图书发送至 Kindle。")
    media_type = str(
        task.get("mimeType")
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )
    maintype, subtype = (media_type.split("/", 1) + ["octet-stream"])[:2]
    attachment_name = (
        Path(str(task.get("fileName") or path.name))
        .name.replace("\r", "")
        .replace("\n", "")
    )
    message.add_attachment(
        path.read_bytes(), maintype=maintype, subtype=subtype, filename=attachment_name
    )
    task = _update_send_snapshot(db, str(task["id"]), config, message_id)

    client: smtplib.SMTP | None = None
    try:
        client = open_smtp_connection(config)
        client.send_message(message)
    except Exception as exc:
        raise _smtp_error(exc, config.password) from exc
    finally:
        if client is not None:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                client.close()


def process_next_kindle_send_task(db: Session, settings: Settings) -> bool:
    queued = next_queued_task(db)
    db.close()
    if not queued:
        return False
    task = _claim_task(db, str(queued["id"]))
    if not task:
        return True
    try:
        _send_task(db, settings, task)
    except Exception as exc:
        error = (
            exc
            if isinstance(exc, KindleSendError)
            else KindleSendError(safe_error_message(exc))
        )
        attempt_count = int(task.get("attemptCount") or 0)
        now = datetime.now(UTC)
        if error.transient and attempt_count < MAX_SEND_ATTEMPTS:
            delay = RETRY_DELAYS_SECONDS[
                min(attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1)
            ]
            retry_at = now + timedelta(seconds=delay)
            prepared_event = _prepared_event(
                task,
                action="send.retry_scheduled",
                level="warning",
                message=f"Kindle 发送失败，等待第 {attempt_count + 1} 次尝试：{task.get('bookTitle')}",
                metadata={
                    "attemptCount": attempt_count,
                    "nextAttemptAt": retry_at,
                    "errorMessage": str(error),
                },
            )
            schedule_kindle_retry_command(
                db,
                str(task["id"]),
                retry_at=retry_at,
                error_message=str(error),
                timestamp=now,
                event=prepared_event,
            )
        else:
            prepared_event = _prepared_event(
                task,
                action="send.failed",
                level="error",
                message=f"Kindle 发送失败：{task.get('bookTitle')}",
                metadata={"attemptCount": attempt_count, "errorMessage": str(error)},
            )
            fail_kindle_send_task_command(
                db,
                str(task["id"]),
                error_message=str(error),
                timestamp=now,
                event=prepared_event,
            )
        return True

    sent_at = datetime.now(UTC)
    prepared_event = _prepared_event(
        task,
        action="send.succeeded",
        message=f"Kindle 邮件已提交：{task.get('bookTitle')}",
        metadata={
            "attemptCount": task.get("attemptCount"),
            "messageId": task.get("messageId"),
        },
    )
    complete_kindle_send_task_command(
        db, str(task["id"]), sent_at=sent_at, event=prepared_event
    )
    return True


def recover_interrupted_tasks(db: Session) -> int:
    rows = list_sending_kindle_tasks(db)
    db.close()
    now = datetime.now(UTC)
    prepared_events = [
        _prepared_event(
            {**task, "status": "unknown"},
            action="send.unknown",
            level="warning",
            message=f"Kindle 发送结果未知：{task.get('bookTitle')}",
        )
        for task in rows
    ]
    task_ids = tuple(str(task["id"]) for task in rows)
    error_message = "服务在发送过程中中断，发送结果未知，请确认后手动重试"
    recover_interrupted_kindle_tasks_command(
        db,
        task_ids=task_ids,
        error_message=error_message,
        timestamp=now,
        events=tuple(prepared_events),
    )
    return len(rows)


class KindleSendQueueWorker:
    def __init__(
        self,
        db_factory: Callable[[], Session],
        settings: Settings,
        heartbeat_db_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self._stop_event = threading.Event()
        self._process_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name="shuku-kindle-send-queue", daemon=True
        )
        self._instance_id = f"kindle-{uuid4().hex}"
        self._heartbeat = QueueHeartbeatPump(
            heartbeat_db_factory or db_factory,
            queue_name="kindle",
            instance_id=self._instance_id,
            poll_interval_seconds=settings.kindle_send_queue_interval_seconds,
        )

    def start(self) -> None:
        with self.db_factory() as db:
            recover_interrupted_tasks(db)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10)

    def process_once(self) -> bool:
        if not self._process_lock.acquire(blocking=False):
            return False
        try:
            with self.db_factory() as db:
                return process_next_kindle_send_task(db, self.settings)
        except Exception as exc:
            print(
                f"[kindle-send-queue] task processing failed: {safe_error_message(exc)}",
                flush=True,
            )
            return False
        finally:
            self._process_lock.release()

    def _run(self) -> None:
        self._heartbeat.start()
        try:
            while not self._stop_event.is_set():
                error = None
                try:
                    processed = self.process_once()
                except Exception as exc:
                    processed = False
                    error = exc
                self._heartbeat.pulse(processed=processed, error=error)
                if processed:
                    continue
                self._stop_event.wait(self.settings.kindle_send_queue_interval_seconds)
        finally:
            self._heartbeat.stop()


def start_kindle_send_queue_worker(
    db_factory: Callable[[], Session],
    settings: Settings,
    heartbeat_db_factory: Callable[[], Session] | None = None,
) -> KindleSendQueueWorker | None:
    if not settings.kindle_send_queue_enabled:
        return None
    worker = KindleSendQueueWorker(db_factory, settings, heartbeat_db_factory)
    worker.start()
    return worker
