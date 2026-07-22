from __future__ import annotations

import mimetypes
import re
import smtplib
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.email_settings import (
    EmailSettingsError,
    get_email_settings,
    open_smtp_connection,
    smtp_connection_settings,
)
from app.services.system_events import record_system_event


MAX_SEND_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (30, 120)
SUPPORTED_FORMATS = {"EPUB", "PDF"}
SUPPORTED_EXTENSIONS = {".epub", ".pdf"}
TERMINAL_STATUSES = {"sent", "failed", "cancelled", "unknown"}


class KindleSendError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


def has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.get_bind()).get_table_names()
    except Exception:
        return False


def mask_email(value: Any) -> str:
    address = str(value or "")
    local, separator, domain = address.partition("@")
    if not separator:
        return "***"
    if len(local) <= 2:
        masked = local[:1] + "***"
    else:
        masked = local[:1] + "***" + local[-1:]
    return f"{masked}@{domain}"


def safe_error_message(exc: BaseException, secrets: list[str] | None = None) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    for secret in secrets or []:
        if secret:
            message = message.replace(secret, "[已隐藏]")
    message = re.sub(
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        lambda match: mask_email(match.group(0)),
        message,
        flags=re.IGNORECASE,
    )
    message = re.sub(r"/(?:Users|home|var|Volumes|mnt|srv|opt)/[^\s'\"]+", "[本地路径]", message)
    return message[:1000]


def _stored_path(path_value: Any, settings: Settings) -> Path | None:
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.is_absolute():
        path = settings.resolved_storage_root / path
    try:
        resolved = path.expanduser().resolve()
        roots = [settings.resolved_storage_root.resolve()]
        if settings.resolved_monitor_root is not None:
            roots.append(settings.resolved_monitor_root.resolve())
        if any(resolved == root or root in resolved.parents for root in roots):
            return resolved
    except OSError:
        return None
    return None


def _task(db: Session, task_id: str) -> dict[str, Any] | None:
    if not has_table(db, "KindleSendTask"):
        return None
    row = db.execute(text("SELECT * FROM `KindleSendTask` WHERE `id` = :id"), {"id": task_id}).mappings().first()
    return dict(row) if row else None


def next_queued_task(db: Session) -> dict[str, Any] | None:
    try:
        if not has_table(db, "KindleSendTask"):
            return None
        row = db.execute(
            text(
                "SELECT * FROM `KindleSendTask` WHERE `status` = 'queued' "
                "AND (`nextAttemptAt` IS NULL OR datetime(`nextAttemptAt`) <= CURRENT_TIMESTAMP) "
                "ORDER BY `createdAt` ASC LIMIT 1"
            )
        ).mappings().first()
        return dict(row) if row else None
    except SQLAlchemyError:
        return None


def _claim_task(db: Session, task_id: str) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    claimed = db.execute(
        text(
            "UPDATE `KindleSendTask` SET `status` = 'sending', `attemptCount` = `attemptCount` + 1, "
            "`startedAt` = :now, `nextAttemptAt` = NULL, `updatedAt` = :now "
            "WHERE `id` = :id AND `status` = 'queued'"
        ),
        {"id": task_id, "now": now},
    )
    db.commit()
    return _task(db, task_id) if int(claimed.rowcount or 0) == 1 else None


def _file_for_task(db: Session, task: dict[str, Any]) -> dict[str, Any]:
    file_id = task.get("fileId")
    if not file_id or not has_table(db, "LibraryFile"):
        raise KindleSendError("附件记录已不存在")
    row = db.execute(
        text(
            "SELECT f.*, e.`workId`, e.`format` AS `editionFormat` "
            "FROM `LibraryFile` f JOIN `LibraryEdition` e ON e.`id` = f.`editionId` "
            "WHERE f.`id` = :id"
        ),
        {"id": file_id},
    ).mappings().first()
    if not row:
        raise KindleSendError("附件记录已不存在")
    return dict(row)


def _smtp_error(exc: BaseException, config_password: str) -> KindleSendError:
    safe = safe_error_message(exc, [config_password])
    if isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        return KindleSendError(safe)
    if isinstance(exc, smtplib.SMTPResponseException):
        return KindleSendError(safe, transient=int(exc.smtp_code) < 500)
    if isinstance(exc, (TimeoutError, OSError, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return KindleSendError(safe, transient=True)
    if isinstance(exc, (EmailSettingsError, ValueError)):
        return KindleSendError(safe)
    return KindleSendError(safe, transient=False)


def _event(
    db: Session,
    task: dict[str, Any],
    *,
    action: str,
    message: str,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> None:
    record_system_event(
        db,
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
        commit=True,
        prune=True,
    )


def _update_send_snapshot(db: Session, task_id: str, config: Any, message_id: str) -> dict[str, Any]:
    db.execute(
        text(
            "UPDATE `KindleSendTask` SET `senderEmail` = :sender, `smtpHost` = :host, `smtpPort` = :port, "
            "`smtpSecurity` = :security, `smtpUsername` = :username, `messageId` = :message_id, `updatedAt` = :now "
            "WHERE `id` = :id"
        ),
        {
            "id": task_id,
            "sender": config.from_email,
            "host": config.host,
            "port": config.port,
            "security": config.security,
            "username": config.username or None,
            "message_id": message_id,
            "now": datetime.now(timezone.utc),
        },
    )
    db.commit()
    return _task(db, task_id) or {"id": task_id}


def _send_task(db: Session, settings: Settings, task: dict[str, Any]) -> None:
    values = get_email_settings(db, include_password=True)
    config = smtp_connection_settings(values)
    file_row = _file_for_task(db, task)
    path = _stored_path(file_row.get("path"), settings)
    if path is None or not path.is_file():
        raise KindleSendError("附件文件已不存在或不在受管理目录中")
    file_format = str(task.get("format") or file_row.get("editionFormat") or "").upper()
    suffix = path.suffix.lower()
    if file_format not in SUPPORTED_FORMATS or suffix not in SUPPORTED_EXTENSIONS:
        raise KindleSendError("Kindle 邮件发送目前仅支持 EPUB 和 PDF")
    if config.max_attachment_mb is not None and path.stat().st_size > config.max_attachment_mb * 1024 * 1024:
        raise KindleSendError(f"附件超过已配置的 {config.max_attachment_mb:g} MB 大小上限")

    message = EmailMessage()
    message_id = make_msgid()
    message["Message-ID"] = message_id
    message["Subject"] = str(task.get("subject") or task.get("bookTitle") or "发送到 Kindle")
    message["From"] = formataddr((config.from_name, config.from_email))
    message["To"] = str(task.get("recipientEmail") or "")
    message.set_content(f"《{task.get('bookTitle') or '图书'}》已由二毛图书发送至 Kindle。")
    media_type = str(task.get("mimeType") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    maintype, subtype = (media_type.split("/", 1) + ["octet-stream"])[:2]
    attachment_name = Path(str(task.get("fileName") or path.name)).name.replace("\r", "").replace("\n", "")
    message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=attachment_name)
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
    if not queued:
        return False
    task = _claim_task(db, str(queued["id"]))
    if not task:
        return True
    try:
        _send_task(db, settings, task)
    except Exception as exc:
        error = exc if isinstance(exc, KindleSendError) else KindleSendError(safe_error_message(exc))
        attempt_count = int(task.get("attemptCount") or 0)
        if error.transient and attempt_count < MAX_SEND_ATTEMPTS:
            delay = RETRY_DELAYS_SECONDS[min(attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1)]
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            db.execute(
                text(
                    "UPDATE `KindleSendTask` SET `status` = 'queued', `nextAttemptAt` = :retry_at, "
                    "`errorMessage` = :error, `updatedAt` = :now WHERE `id` = :id"
                ),
                {"id": task["id"], "retry_at": retry_at, "error": str(error), "now": datetime.now(timezone.utc)},
            )
            db.commit()
            task = _task(db, str(task["id"])) or task
            _event(db, task, action="send.retry_scheduled", level="warning", message=f"Kindle 发送失败，等待第 {attempt_count + 1} 次尝试：{task.get('bookTitle')}", metadata={"attemptCount": attempt_count, "nextAttemptAt": retry_at, "errorMessage": str(error)})
        else:
            db.execute(
                text("UPDATE `KindleSendTask` SET `status` = 'failed', `errorMessage` = :error, `updatedAt` = :now WHERE `id` = :id"),
                {"id": task["id"], "error": str(error), "now": datetime.now(timezone.utc)},
            )
            db.commit()
            task = _task(db, str(task["id"])) or task
            _event(db, task, action="send.failed", level="error", message=f"Kindle 发送失败：{task.get('bookTitle')}", metadata={"attemptCount": attempt_count, "errorMessage": str(error)})
        return True

    sent_at = datetime.now(timezone.utc)
    db.execute(
        text("UPDATE `KindleSendTask` SET `status` = 'sent', `sentAt` = :sent_at, `errorMessage` = NULL, `updatedAt` = :sent_at WHERE `id` = :id"),
        {"id": task["id"], "sent_at": sent_at},
    )
    db.commit()
    task = _task(db, str(task["id"])) or task
    _event(db, task, action="send.succeeded", message=f"Kindle 邮件已提交：{task.get('bookTitle')}", metadata={"attemptCount": task.get("attemptCount"), "messageId": task.get("messageId")})
    return True


def recover_interrupted_tasks(db: Session) -> int:
    if not has_table(db, "KindleSendTask"):
        return 0
    rows = [dict(row) for row in db.execute(text("SELECT * FROM `KindleSendTask` WHERE `status` = 'sending'")).mappings()]
    now = datetime.now(timezone.utc)
    for task in rows:
        db.execute(
            text("UPDATE `KindleSendTask` SET `status` = 'unknown', `errorMessage` = :error, `updatedAt` = :now WHERE `id` = :id"),
            {"id": task["id"], "error": "服务在发送过程中中断，发送结果未知，请确认后手动重试", "now": now},
        )
    db.commit()
    for task in rows:
        task["status"] = "unknown"
        _event(db, task, action="send.unknown", level="warning", message=f"Kindle 发送结果未知：{task.get('bookTitle')}")
    return len(rows)


class KindleSendQueueWorker:
    def __init__(self, db_factory: Callable[[], Session], settings: Settings) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self._stop_event = threading.Event()
        self._process_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="shuku-kindle-send-queue", daemon=True)

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
            print(f"[kindle-send-queue] task processing failed: {safe_error_message(exc)}", flush=True)
            return False
        finally:
            self._process_lock.release()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self.process_once():
                continue
            self._stop_event.wait(self.settings.kindle_send_queue_interval_seconds)


def start_kindle_send_queue_worker(db_factory: Callable[[], Session], settings: Settings) -> KindleSendQueueWorker | None:
    if not settings.kindle_send_queue_enabled:
        return None
    worker = KindleSendQueueWorker(db_factory, settings)
    worker.start()
    return worker
