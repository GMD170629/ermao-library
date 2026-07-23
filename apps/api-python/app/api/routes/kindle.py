from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.authorization import can_access_file, read_user_preferences, write_user_preference
from app.core.config import Settings, get_settings
from app.core.i18n import configured_locale
from app.db.session import get_db
from app.models.auth import User
from app.schemas.responses import fail, ok
from app.services.email_settings import (
    EmailSettingsError,
    candidate_email_settings,
    get_email_settings,
    public_email_settings,
    save_email_settings,
    smtp_connection_settings,
    test_smtp_connection,
)
from app.services.kindle_queue import SUPPORTED_EXTENSIONS, SUPPORTED_FORMATS, TERMINAL_STATUSES, mask_email, safe_error_message
from app.services.system_events import record_system_event


router = APIRouter()
EMAIL_ADAPTER = TypeAdapter(EmailStr)


def _auth(db: Session, request: Request, settings: Settings) -> tuple[User | None, Response | None]:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        return None, fail("UNAUTHORIZED", status_code=401)
    return user, None


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.get_bind()).get_table_names()
    except Exception:
        return False


def _task(db: Session, task_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "KindleSendTask"):
        return None
    row = db.execute(text("SELECT * FROM `KindleSendTask` WHERE `id` = :id"), {"id": task_id}).mappings().first()
    return dict(row) if row else None


def _can_access_task(user: User, task: dict[str, Any]) -> bool:
    return str(task.get("userId") or "") == user.id


def _task_view(task: dict[str, Any]) -> dict[str, Any]:
    status = str(task.get("status") or "queued")
    return {
        **task,
        "canCancel": status == "queued",
        "canRetry": status in {"failed", "cancelled", "unknown"},
        "canDelete": status in TERMINAL_STATUSES,
    }


def _event(
    db: Session,
    user: User,
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
        actor_type="user",
        actor_id=user.id,
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


@router.get("/email-settings")
def read_email_settings(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        return ok(public_email_settings(db))
    except EmailSettingsError as exc:
        return fail(str(exc), status_code=400)


@router.put("/email-settings")
async def update_email_settings(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        payload = await request.json()
    except Exception:
        return fail("设置格式不正确", status_code=400)
    if not isinstance(payload, dict):
        return fail("设置格式不正确", status_code=400)
    try:
        public, changed_keys = save_email_settings(db, payload)
    except EmailSettingsError as exc:
        return fail(str(exc), status_code=400)
    record_system_event(
        db,
        source="system",
        action="settings.updated",
        message=f"更新邮件与 Kindle 设置 {len(changed_keys)} 项",
        level="warning",
        actor_type="admin",
        actor_id=user.id,
        target_type="settings",
        metadata={"keys": changed_keys},
        commit=True,
        prune=True,
    )
    return ok(public)


@router.post("/email-settings/smtp-test")
async def smtp_test(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return fail("设置格式不正确", status_code=400)
    candidate: dict[str, Any] = {}
    try:
        candidate = candidate_email_settings(db, payload)
        test_smtp_connection(candidate)
    except (EmailSettingsError, OSError, smtplib.SMTPException) as exc:
        return fail(safe_error_message(exc, [str(candidate.get("password") or "")]), status_code=400)
    return ok({"connected": True, "message": "SMTP 连接、加密与认证均正常"})


@router.get("/kindle-settings")
def read_kindle_settings(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        email_values = get_email_settings(db, include_password=False)
    except EmailSettingsError as exc:
        return fail(str(exc), status_code=400, code="INVALID_EMAIL_SETTINGS")
    preferences = read_user_preferences(db, user.id)
    personal_email = str(preferences.get("kindle.email") or "").strip()
    return ok({
        "kindle": {"email": personal_email},
        "smtp": {
            "configured": bool(email_values.get("host") and email_values.get("fromEmail")),
            "fromEmail": email_values.get("fromEmail") or "",
        },
    })


@router.put("/kindle-settings")
async def update_kindle_settings(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        payload = await request.json()
    except Exception:
        return fail("设置格式不正确", status_code=400, code="INVALID_KINDLE_SETTINGS")
    raw_email = str((payload or {}).get("email") or "").strip() if isinstance(payload, dict) else ""
    try:
        email = str(EMAIL_ADAPTER.validate_python(raw_email)).lower() if raw_email else ""
    except ValidationError:
        return fail("Kindle 邮箱格式不正确", status_code=400, code="INVALID_KINDLE_EMAIL")
    write_user_preference(db, user.id, "kindle.email", email)
    db.commit()
    return ok({"kindle": {"email": email}})


@router.get("/kindle-send-tasks")
def list_kindle_send_tasks(
    request: Request,
    status: str | None = None,
    page: int = 1,
    pageSize: int = 100,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "KindleSendTask"):
        return ok({"tasks": [], "total": 0, "page": 1, "pageSize": pageSize, "totalPages": 1})
    page = max(1, page)
    page_size = min(200, max(1, pageSize))
    allowed_statuses = {"queued", "sending", "sent", "failed", "cancelled", "unknown"}
    normalized_status = str(status or "").lower()
    if normalized_status and normalized_status not in allowed_statuses:
        return fail("发送状态不受支持", status_code=400)
    clauses: list[str] = ["`userId` = :user_id"]
    params: dict[str, Any] = {"user_id": user.id}
    if normalized_status:
        clauses.append("`status` = :status")
        params["status"] = normalized_status
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    total = int(db.execute(text(f"SELECT COUNT(*) FROM `KindleSendTask`{where}"), params).scalar() or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows = db.execute(
        text(f"SELECT * FROM `KindleSendTask`{where} ORDER BY `createdAt` DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings()
    return ok({"tasks": [_task_view(dict(row)) for row in rows], "total": total, "page": page, "pageSize": page_size, "totalPages": total_pages})


@router.post("/kindle-send-tasks")
async def create_kindle_send_task(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "KindleSendTask"):
        return fail("Kindle 发送队列尚未初始化", status_code=503)
    try:
        payload = await request.json()
    except Exception:
        return fail("发送参数格式不正确", status_code=400)
    if not isinstance(payload, dict):
        return fail("发送参数格式不正确", status_code=400)
    file_id = str(payload.get("fileId") or "").strip()
    work_id = str(payload.get("workId") or "").strip()
    if not file_id:
        return fail("请选择要发送的图书文件", status_code=400)
    if not can_access_file(db, user, file_id):
        return fail("选择的图书文件不存在", status_code=404, code="FILE_NOT_FOUND")
    try:
        email_values = get_email_settings(db, include_password=True)
        smtp_config = smtp_connection_settings(email_values)
    except EmailSettingsError as exc:
        return fail(str(exc), status_code=400, details={"settingsHref": "/settings/email?tab=smtp"})
    preferences = read_user_preferences(db, user.id)
    recipient = str(preferences.get("kindle.email") or "").strip()
    if not recipient:
        return fail("请先配置 Kindle 邮箱", status_code=400, details={"settingsHref": "/settings/email?tab=kindle"})

    row = db.execute(
        text(
            "SELECT f.*, e.`workId`, e.`format` AS `editionFormat`, e.`versionName`, "
            "w.`title` AS `bookTitle`, v.`title` AS `volumeTitle` "
            "FROM `LibraryFile` f "
            "JOIN `LibraryEdition` e ON e.`id` = f.`editionId` "
            "JOIN `LibraryWork` w ON w.`id` = e.`workId` "
            "LEFT JOIN `LibraryVolume` v ON v.`id` = f.`volumeId` "
            "WHERE f.`id` = :file_id"
        ),
        {"file_id": file_id},
    ).mappings().first()
    if not row or (work_id and str(row["workId"]) != work_id):
        return fail("选择的图书文件不存在", status_code=404)
    file_row = dict(row)
    file_format = str(file_row.get("editionFormat") or "").upper()
    file_name = Path(str(file_row.get("path") or "")).name
    if file_format not in SUPPORTED_FORMATS or Path(file_name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        return fail("Kindle 邮件发送目前仅支持 EPUB 和 PDF", status_code=400)
    size_bytes = int(file_row.get("sizeBytes") or 0)
    if smtp_config.max_attachment_mb is not None and size_bytes > smtp_config.max_attachment_mb * 1024 * 1024:
        return fail(f"附件超过已配置的 {smtp_config.max_attachment_mb:g} MB 大小上限", status_code=400)

    existing = db.execute(
        text(
            "SELECT * FROM `KindleSendTask` WHERE `fileId` = :file_id AND `recipientEmail` = :recipient "
            "AND `status` IN ('queued', 'sending') ORDER BY `createdAt` DESC LIMIT 1"
        ),
        {"file_id": file_id, "recipient": recipient},
    ).mappings().first()
    if existing:
        if not _can_access_task(user, dict(existing)):
            return fail("同一文件已有等待中或发送中的任务", status_code=409, code="KINDLE_TASK_ALREADY_ACTIVE")
        return ok({"task": _task_view(dict(existing)), "alreadyQueued": True})

    now = datetime.now(timezone.utc)
    task_id = f"kindle_{time_ns()}"
    locale = read_user_preferences(db, user.id).get("locale")
    if locale not in {"zh-CN", "en-US"}:
        locale = configured_locale(db)
    fallback_book_title = "Untitled Book" if locale == "en-US" else "未命名图书"
    fallback_subject = "Send to Kindle" if locale == "en-US" else "发送到 Kindle"
    params = {
        "id": task_id,
        "user_id": user.id,
        "work_id": file_row["workId"],
        "edition_id": file_row["editionId"],
        "volume_id": file_row.get("volumeId"),
        "file_id": file_id,
        "book_title": str(file_row.get("bookTitle") or fallback_book_title),
        "edition_name": file_row.get("versionName"),
        "volume_title": file_row.get("volumeTitle"),
        "file_name": file_name,
        "format": file_format,
        "mime_type": file_row.get("mimeType") or ("application/epub+zip" if file_format == "EPUB" else "application/pdf"),
        "size_bytes": size_bytes,
        "sender_email": smtp_config.from_email,
        "recipient_email": recipient,
        "subject": str(file_row.get("bookTitle") or fallback_subject),
        "smtp_host": smtp_config.host,
        "smtp_port": smtp_config.port,
        "smtp_security": smtp_config.security,
        "smtp_username": smtp_config.username or None,
        "now": now,
    }
    try:
        db.execute(
            text(
                "INSERT INTO `KindleSendTask` (`id`, `userId`, `workId`, `editionId`, `volumeId`, `fileId`, `bookTitle`, "
                "`editionName`, `volumeTitle`, `fileName`, `format`, `mimeType`, `sizeBytes`, `senderEmail`, "
                "`recipientEmail`, `subject`, `smtpHost`, `smtpPort`, `smtpSecurity`, `smtpUsername`, `status`, "
                "`attemptCount`, `createdAt`, `updatedAt`) VALUES (:id, :user_id, :work_id, :edition_id, :volume_id, :file_id, "
                ":book_title, :edition_name, :volume_title, :file_name, :format, :mime_type, :size_bytes, :sender_email, "
                ":recipient_email, :subject, :smtp_host, :smtp_port, :smtp_security, :smtp_username, 'queued', 0, :now, :now)"
            ),
            params,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.execute(
            text("SELECT * FROM `KindleSendTask` WHERE `fileId` = :file_id AND `recipientEmail` = :recipient AND `status` IN ('queued', 'sending') LIMIT 1"),
            {"file_id": file_id, "recipient": recipient},
        ).mappings().first()
        if existing:
            if not _can_access_task(user, dict(existing)):
                return fail("同一文件已有等待中或发送中的任务", status_code=409, code="KINDLE_TASK_ALREADY_ACTIVE")
            return ok({"task": _task_view(dict(existing)), "alreadyQueued": True})
        raise
    task = _task(db, task_id) or params
    _event(db, user, task, action="send.queued", message=f"加入 Kindle 发送队列：{task.get('bookTitle')}", metadata={"status": "queued"})
    return ok({"task": _task_view(task), "alreadyQueued": False}, status_code=201)


@router.post("/kindle-send-tasks/{task_id}/cancel")
def cancel_kindle_send_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _task(db, task_id)
    if not task:
        return fail("Kindle 发送任务不存在", status_code=404)
    if not _can_access_task(user, task):
        return fail("Kindle 发送任务不存在", status_code=404)
    if task.get("status") != "queued":
        return fail("只有等待中的任务可以取消", status_code=400)
    result = db.execute(
        text("UPDATE `KindleSendTask` SET `status` = 'cancelled', `nextAttemptAt` = NULL, `updatedAt` = :now WHERE `id` = :id AND `status` = 'queued'"),
        {"id": task_id, "now": datetime.now(timezone.utc)},
    )
    db.commit()
    if int(result.rowcount or 0) != 1:
        return fail("任务状态已变化，请刷新后重试", status_code=409)
    task = _task(db, task_id) or task
    _event(db, user, task, action="send.cancelled", level="warning", message=f"取消 Kindle 发送：{task.get('bookTitle')}")
    return ok({"task": _task_view(task)})


@router.post("/kindle-send-tasks/{task_id}/retry")
def retry_kindle_send_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _task(db, task_id)
    if not task:
        return fail("Kindle 发送任务不存在", status_code=404)
    if not _can_access_task(user, task):
        return fail("Kindle 发送任务不存在", status_code=404)
    if task.get("status") not in {"failed", "cancelled", "unknown"}:
        return fail("只有失败、已取消或结果未知的任务可以重试", status_code=400)
    active_duplicate = db.execute(
        text(
            "SELECT `id` FROM `KindleSendTask` WHERE `id` != :id AND `fileId` = :file_id "
            "AND `recipientEmail` = :recipient AND `status` IN ('queued', 'sending') LIMIT 1"
        ),
        {"id": task_id, "file_id": task.get("fileId"), "recipient": task.get("recipientEmail")},
    ).first()
    if active_duplicate:
        return fail("同一文件已有等待中或发送中的任务", status_code=409)
    db.execute(
        text(
            "UPDATE `KindleSendTask` SET `status` = 'queued', `attemptCount` = 0, `nextAttemptAt` = NULL, "
            "`errorMessage` = NULL, `startedAt` = NULL, `sentAt` = NULL, `messageId` = NULL, `updatedAt` = :now WHERE `id` = :id"
        ),
        {"id": task_id, "now": datetime.now(timezone.utc)},
    )
    db.commit()
    task = _task(db, task_id) or task
    _event(db, user, task, action="send.retried", message=f"重新排队 Kindle 发送：{task.get('bookTitle')}")
    return ok({"task": _task_view(task)})


@router.delete("/kindle-send-tasks/{task_id}")
def delete_kindle_send_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _task(db, task_id)
    if not task:
        return fail("Kindle 发送任务不存在", status_code=404)
    if not _can_access_task(user, task):
        return fail("Kindle 发送任务不存在", status_code=404)
    if task.get("status") not in TERMINAL_STATUSES:
        return fail("等待中或发送中的任务不能删除", status_code=400)
    db.execute(text("DELETE FROM `KindleSendTask` WHERE `id` = :id"), {"id": task_id})
    db.commit()
    _event(db, user, task, action="send.deleted", level="warning", message=f"删除 Kindle 发送记录：{task.get('bookTitle')}", metadata={"status": task.get("status")})
    return ok({"deleted": True, "id": task_id})
