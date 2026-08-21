from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import Response
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.typed_route import TypedContractRoute
from app.bootstrap.kindle import (
    cancel_kindle_send_task_command,
    create_kindle_send_task_command,
    delete_kindle_send_task_command,
    find_active_kindle_task,
    get_kindle_send_task,
    get_library_asset_details_for_kindle,
    has_table,
    retry_kindle_send_task_command,
    update_email_settings_command,
    update_kindle_recipient_command,
)
from app.bootstrap.kindle import (
    list_kindle_send_tasks as query_kindle_send_tasks,
)
from app.core.auth import get_current_user
from app.core.authorization import (
    can_access_asset,
    read_user_preferences,
)
from app.core.config import Settings, get_settings
from app.core.i18n import configured_locale
from app.db.session import get_db
from app.models.auth import User
from app.modules.kindle.presentation.schemas import (
    CreateKindleTaskRequest,
    DeletedKindleTaskResponse,
    EmailSettingsResponse,
    KindleSettingsResponse,
    KindleTaskResponse,
    KindleTasksResponse,
    SmtpTestResponse,
    UpdateEmailSettingsRequest,
    UpdateKindleSettingsRequest,
)
from app.schemas.responses import fail, ok
from app.services.email_settings import (
    EmailSettingsError,
    candidate_email_settings,
    get_email_settings,
    prepare_email_settings_update,
    public_email_settings,
    smtp_connection_settings,
    test_smtp_connection,
)
from app.services.kindle_queue import (
    SUPPORTED_EXTENSIONS,
    SUPPORTED_FORMATS,
    TERMINAL_STATUSES,
    mask_email,
    safe_error_message,
)
from app.services.system_events import prepare_system_event

router = APIRouter(route_class=TypedContractRoute)
EMAIL_ADAPTER = TypeAdapter(EmailStr)


def _auth(
    db: Session, request: Request, settings: Settings
) -> tuple[User | None, Response | None]:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        return None, fail("UNAUTHORIZED", status_code=401)
    return user, None


def _task(db: Session, task_id: str) -> dict[str, Any] | None:
    return get_kindle_send_task(db, task_id)


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


def _prepared_event(
    user: User,
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
        actor_type="user",
        actor_id=user.id,
        target_type="kindleSendTask",
        target_id=str(task.get("id") or ""),
        metadata={
            "bookId": task.get("bookId"),
            "assetId": task.get("assetId"),
            "fileName": task.get("fileName"),
            "resourceTitle": task.get("resourceTitle"),
            "format": task.get("format"),
            "sizeBytes": task.get("sizeBytes"),
            "recipientEmail": mask_email(task.get("recipientEmail")),
            **(metadata or {}),
        },
    )


@router.get("/email-settings")
def read_email_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EmailSettingsResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        values = public_email_settings(db)
        db.close()
        return ok(values)
    except EmailSettingsError as exc:
        return fail(str(exc), status_code=400)


@router.put("/email-settings")
def update_email_settings(
    request: Request,
    payload: Annotated[UpdateEmailSettingsRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EmailSettingsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    actor_id = user.id
    db.close()
    if payload is None:
        return fail("设置格式不正确", status_code=400)
    values = payload.model_dump(by_alias=True, exclude_unset=True)
    try:
        prepared_settings = prepare_email_settings_update(db, values)
    except EmailSettingsError as exc:
        return fail(str(exc), status_code=400)
    db.close()
    prepared_event = prepare_system_event(
        source="system",
        action="settings.updated",
        message=f"更新邮件与 Kindle 设置 {len(prepared_settings.changed_keys)} 项",
        level="warning",
        actor_type="admin",
        actor_id=actor_id,
        target_type="settings",
        metadata={"keys": prepared_settings.changed_keys},
    )
    update_email_settings_command(db, prepared_settings, event=prepared_event)
    return ok(public_email_settings(db))


@router.post("/email-settings/smtp-test")
def smtp_test(
    request: Request,
    payload: Annotated[UpdateEmailSettingsRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SmtpTestResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    db.close()
    values = (
        payload.model_dump(by_alias=True, exclude_unset=True)
        if payload is not None
        else {}
    )
    candidate: dict[str, Any] = {}
    try:
        candidate = candidate_email_settings(db, values)
        db.close()
        test_smtp_connection(candidate)
    except (EmailSettingsError, OSError, smtplib.SMTPException) as exc:
        return fail(
            safe_error_message(exc, [str(candidate.get("password") or "")]),
            status_code=400,
        )
    return ok({"connected": True, "message": "SMTP 连接、加密与认证均正常"})


@router.get("/kindle-settings")
def read_kindle_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KindleSettingsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        email_values = get_email_settings(db, include_password=False)
    except EmailSettingsError as exc:
        return fail(str(exc), status_code=400, code="INVALID_EMAIL_SETTINGS")
    preferences = read_user_preferences(db, user.id)
    db.close()
    personal_email = str(preferences.get("kindle.email") or "").strip()
    return ok(
        {
            "kindle": {"email": personal_email},
            "smtp": {
                "configured": bool(
                    email_values.get("host") and email_values.get("fromEmail")
                ),
                "fromEmail": email_values.get("fromEmail") or "",
            },
        }
    )


@router.put("/kindle-settings")
def update_kindle_settings(
    request: Request,
    payload: Annotated[UpdateKindleSettingsRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KindleSettingsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    user_id = user.id
    db.close()
    if payload is None:
        return fail("设置格式不正确", status_code=400, code="INVALID_KINDLE_SETTINGS")
    raw_email = str(payload.email or "").strip()
    try:
        email = (
            str(EMAIL_ADAPTER.validate_python(raw_email)).lower() if raw_email else ""
        )
    except ValidationError:
        return fail(
            "Kindle 邮箱格式不正确", status_code=400, code="INVALID_KINDLE_EMAIL"
        )
    update_kindle_recipient_command(db, user_id=user_id, email=email)
    return ok({"kindle": {"email": email}})


@router.get("/kindle-send-tasks")
def list_kindle_send_tasks(
    request: Request,
    status: str | None = None,
    page: int = 1,
    pageSize: int = 100,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KindleTasksResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not has_table(db, "KindleSendTask"):
        return ok(
            {"tasks": [], "total": 0, "page": 1, "pageSize": pageSize, "totalPages": 1}
        )
    page = max(1, page)
    page_size = min(200, max(1, pageSize))
    allowed_statuses = {"queued", "sending", "sent", "failed", "cancelled", "unknown"}
    normalized_status = str(status or "").lower()
    if normalized_status and normalized_status not in allowed_statuses:
        return fail("发送状态不受支持", status_code=400)
    total = query_kindle_send_tasks(
        db,
        user_id=user.id,
        status=normalized_status or None,
        limit=1,
        offset=0,
    )[1]
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows, _total = query_kindle_send_tasks(
        db,
        user_id=user.id,
        status=normalized_status or None,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    db.close()
    return ok(
        {
            "tasks": [_task_view(row) for row in rows],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": total_pages,
        }
    )


@router.post("/kindle-send-tasks")
def create_kindle_send_task(
    request: Request,
    payload: Annotated[CreateKindleTaskRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KindleTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    db.close()
    queue_ready = has_table(db, "KindleSendTask")
    db.close()
    if not queue_ready:
        return fail("Kindle 发送队列尚未初始化", status_code=503)
    if payload is None:
        return fail("发送参数格式不正确", status_code=400)
    asset_id = str(payload.asset_id or "").strip()
    book_id = str(payload.book_id or "").strip()
    if not asset_id:
        return fail("请选择要发送的图书文件", status_code=400)
    if not can_access_asset(db, user, asset_id):
        return fail("选择的图书文件不存在", status_code=404, code="FILE_NOT_FOUND")
    try:
        email_values = get_email_settings(db, include_password=True)
        smtp_config = smtp_connection_settings(email_values)
    except EmailSettingsError as exc:
        return fail(
            str(exc),
            status_code=400,
            details={"settingsHref": "/settings/email?tab=smtp"},
        )
    preferences = read_user_preferences(db, user.id)
    recipient = str(preferences.get("kindle.email") or "").strip()
    if not recipient:
        return fail(
            "请先配置 Kindle 邮箱",
            status_code=400,
            details={"settingsHref": "/settings/email?tab=kindle"},
        )

    file_row = get_library_asset_details_for_kindle(db, asset_id)
    db.close()
    if not file_row or (book_id and str(file_row["bookId"]) != book_id):
        return fail("选择的图书文件不存在", status_code=404)
    file_format = str(file_row.get("resourceFormat") or "").upper()
    file_name = Path(str(file_row.get("sourcePath") or "")).name
    if (
        file_format not in SUPPORTED_FORMATS
        or Path(file_name).suffix.lower() not in SUPPORTED_EXTENSIONS
    ):
        return fail("Kindle 邮件发送目前仅支持 EPUB 和 PDF", status_code=400)
    size_bytes = int(file_row.get("sizeBytes") or 0)
    if (
        smtp_config.max_attachment_mb is not None
        and size_bytes > smtp_config.max_attachment_mb * 1024 * 1024
    ):
        return fail(
            f"附件超过已配置的 {smtp_config.max_attachment_mb:g} MB 大小上限",
            status_code=400,
        )

    existing = find_active_kindle_task(db, asset_id=asset_id, recipient_email=recipient)
    db.close()
    if existing:
        if not _can_access_task(user, existing):
            return fail(
                "同一文件已有等待中或发送中的任务",
                status_code=409,
                code="KINDLE_TASK_ALREADY_ACTIVE",
            )
        return ok({"task": _task_view(existing), "alreadyQueued": True})

    now = datetime.now(UTC)
    task_id = f"kindle_{time_ns()}"
    locale = preferences.get("locale")
    if locale not in {"zh-CN", "en-US"}:
        locale = configured_locale(db)
        db.close()
    fallback_book_title = "Untitled Book" if locale == "en-US" else "未命名图书"
    fallback_subject = "Send to Kindle" if locale == "en-US" else "发送到 Kindle"
    params = {
        "id": task_id,
        "userId": user.id,
        "bookId": file_row["bookId"],
        "resourceId": file_row.get("resourceId"),
        "assetId": asset_id,
        "bookTitle": str(file_row.get("bookTitle") or fallback_book_title),
        "resourceTitle": file_row.get("resourceTitle"),
        "fileName": file_name,
        "format": file_format,
        "mimeType": file_row.get("mimeType")
        or ("application/epub+zip" if file_format == "EPUB" else "application/pdf"),
        "sizeBytes": size_bytes,
        "senderEmail": smtp_config.from_email,
        "recipientEmail": recipient,
        "subject": str(file_row.get("bookTitle") or fallback_subject),
        "smtpHost": smtp_config.host,
        "smtpPort": smtp_config.port,
        "smtpSecurity": smtp_config.security,
        "smtpUsername": smtp_config.username or None,
        "status": "queued",
        "attemptCount": 0,
        "createdAt": now,
        "updatedAt": now,
    }
    prepared_event = _prepared_event(
        user,
        params,
        action="send.queued",
        message=f"加入 Kindle 发送队列：{params.get('bookTitle')}",
        metadata={"status": "queued"},
    )
    try:
        create_kindle_send_task_command(db, params, event=prepared_event)
    except IntegrityError:
        existing = find_active_kindle_task(
            db, asset_id=asset_id, recipient_email=recipient
        )
        db.close()
        if existing:
            if not _can_access_task(user, existing):
                return fail(
                    "同一文件已有等待中或发送中的任务",
                    status_code=409,
                    code="KINDLE_TASK_ALREADY_ACTIVE",
                )
            return ok({"task": _task_view(existing), "alreadyQueued": True})
        raise
    task = params
    return ok({"task": _task_view(task), "alreadyQueued": False}, status_code=201)


@router.post("/kindle-send-tasks/{task_id}/cancel")
def cancel_kindle_send_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KindleTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _task(db, task_id)
    db.close()
    if not task:
        return fail("Kindle 发送任务不存在", status_code=404)
    if not _can_access_task(user, task):
        return fail("Kindle 发送任务不存在", status_code=404)
    if task.get("status") != "queued":
        return fail("只有等待中的任务可以取消", status_code=400)
    cancelled_task = {**task, "status": "cancelled"}
    prepared_event = _prepared_event(
        user,
        cancelled_task,
        action="send.cancelled",
        level="warning",
        message=f"取消 Kindle 发送：{task.get('bookTitle')}",
    )
    cancelled_at = datetime.now(UTC)
    result_count = cancel_kindle_send_task_command(
        db,
        task_id,
        timestamp=cancelled_at,
        event=prepared_event,
    )
    if result_count != 1:
        return fail("任务状态已变化，请刷新后重试", status_code=409)
    return ok({"task": _task_view(cancelled_task)})


@router.post("/kindle-send-tasks/{task_id}/retry")
def retry_kindle_send_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KindleTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _task(db, task_id)
    db.close()
    if not task:
        return fail("Kindle 发送任务不存在", status_code=404)
    if not _can_access_task(user, task):
        return fail("Kindle 发送任务不存在", status_code=404)
    if task.get("status") not in {"failed", "cancelled", "unknown"}:
        return fail("只有失败、已取消或结果未知的任务可以重试", status_code=400)
    active_duplicate = find_active_kindle_task(
        db,
        asset_id=str(task.get("assetId") or ""),
        recipient_email=str(task.get("recipientEmail") or ""),
        exclude_task_id=task_id,
    )
    db.close()
    if active_duplicate:
        return fail("同一文件已有等待中或发送中的任务", status_code=409)
    retried_task = {**task, "status": "queued", "attemptCount": 0}
    prepared_event = _prepared_event(
        user,
        retried_task,
        action="send.retried",
        message=f"重新排队 Kindle 发送：{task.get('bookTitle')}",
    )
    retried_at = datetime.now(UTC)
    retry_kindle_send_task_command(
        db,
        task_id,
        timestamp=retried_at,
        event=prepared_event,
    )
    return ok({"task": _task_view(retried_task)})


@router.delete("/kindle-send-tasks/{task_id}")
def delete_kindle_send_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletedKindleTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _task(db, task_id)
    db.close()
    if not task:
        return fail("Kindle 发送任务不存在", status_code=404)
    if not _can_access_task(user, task):
        return fail("Kindle 发送任务不存在", status_code=404)
    if task.get("status") not in TERMINAL_STATUSES:
        return fail("等待中或发送中的任务不能删除", status_code=400)
    prepared_event = _prepared_event(
        user,
        task,
        action="send.deleted",
        level="warning",
        message=f"删除 Kindle 发送记录：{task.get('bookTitle')}",
        metadata={"status": task.get("status")},
    )
    delete_kindle_send_task_command(db, task_id, event=prepared_event)
    return ok({"deleted": True, "id": task_id})
