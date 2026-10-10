from __future__ import annotations

import logging
import re
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.feedback import build_feedback_diagnostics
from app.contracts.http import SuccessEnvelope
from app.core.config import Settings, get_settings
from app.core.exception_diagnostics import capture_exception, record_exception
from app.db.session import get_db, release_read_transaction
from app.models.auth import User
from app.schemas.responses import fail, ok

from .application import (
    FeedbackAccessError,
    FeedbackContext,
    FeedbackEventMissing,
    prepare_preview,
)
from .domain import (
    FeedbackDraft,
    FeedbackEnvironment,
    FeedbackPreview,
    FeedbackReceipt,
    FeedbackSubmitRequest,
    FileDescriptor,
)
from .infrastructure import (
    Attachment,
    FeedbackDeliveryError,
    send_to_official_site,
)

router = APIRouter(tags=["feedback"], route_class=TypedContractRoute)
LOGGER = logging.getLogger(__name__)
EXTENSIONS = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf",
    ".txt": "text/plain", ".log": "text/plain", ".zip": "application/zip",
}


def _preview(db: Session, actor: User, settings: Settings, draft: FeedbackDraft) -> FeedbackPreview | Response:
    try:
        context = FeedbackContext(actor.role, actor.can_manage_system, settings.app_version)
        if not draft.event_id:
            release_read_transaction(db)
        return prepare_preview(context, build_feedback_diagnostics(db), draft)
    except FeedbackAccessError as _caught_error:
        capture_exception(_caught_error)
        return fail("需要系统管理权限", 403, code="FEEDBACK_LOG_FORBIDDEN")
    except FeedbackEventMissing as _caught_error:
        capture_exception(_caught_error)
        return fail("日志已不可用", 404, code="FEEDBACK_LOG_NOT_FOUND")
    except ValueError as _caught_error:
        capture_exception(_caught_error)
        return fail("系统环境信息不完整", 400, code="FEEDBACK_ENVIRONMENT_INVALID")


@router.post(
    "/feedback/preview",
    response_model=SuccessEnvelope[FeedbackPreview],
    response_model_exclude_none=True,
)
def preview_feedback(
    draft: FeedbackDraft,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SuccessEnvelope[FeedbackPreview] | Response:
    actor, error = require_user(db, request, settings)
    if error is not None or actor is None:
        return error or fail("UNAUTHORIZED", 401)
    preview = _preview(db, actor, settings, draft)
    return preview if isinstance(preview, Response) else ok(
        preview.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


@router.get("/feedback/environment", response_model=SuccessEnvelope[FeedbackEnvironment])
def feedback_environment(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SuccessEnvelope[FeedbackEnvironment] | Response:
    actor, error = require_user(db, request, settings)
    if error is not None or actor is None:
        return error or fail("UNAUTHORIZED", 401)
    return ok(FeedbackEnvironment(appVersion=settings.app_version))


@router.post("/feedback", response_model=SuccessEnvelope[FeedbackReceipt])
def submit_feedback(
    request: Request,
    draft: Annotated[str, Form()],
    files: Annotated[list[UploadFile] | None, File()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SuccessEnvelope[FeedbackReceipt] | Response:
    actor, error = require_user(db, request, settings)
    if error is not None or actor is None:
        return error or fail("UNAUTHORIZED", 401)
    try:
        submitted = FeedbackSubmitRequest.model_validate_json(draft)
    except ValidationError as _caught_error:
        capture_exception(_caught_error)
        return fail("反馈内容无效", 422, code="FEEDBACK_INVALID")
    received = files or []
    if len(received) > 5:
        return fail("附件数量超限", 413, code="FEEDBACK_FILES_TOO_LARGE")
    release_read_transaction(db)
    attachments: list[Attachment] = []
    total = 0
    for file in received:
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not name or len(name) > 120 or not re.fullmatch(r"[\w.() +-]+", name):
            return fail("文件名无效", 400, code="FEEDBACK_FILE_INVALID")
        media_type = EXTENSIONS.get("." + name.rsplit(".", 1)[-1].lower())
        if media_type is None:
            return fail("不支持的附件格式", 400, code="FEEDBACK_FILE_INVALID")
        content = file.file.read(10 * 1024 * 1024 + 1)
        total += len(content)
        if len(content) > 10 * 1024 * 1024 or total > 15 * 1024 * 1024:
            return fail("附件大小超限", 413, code="FEEDBACK_FILES_TOO_LARGE")
        attachments.append(Attachment(name, media_type, content))
    manifest = [FileDescriptor(name=item.name, size=len(item.content), sha256=sha256(item.content).hexdigest()) for item in attachments]
    if manifest != submitted.files:
        return fail("附件已变化，请重新核对", 409, code="FEEDBACK_PREVIEW_CHANGED")
    base_draft = FeedbackDraft.model_validate(submitted.model_dump(exclude={"submission_key", "preview_hash"}))
    preview = _preview(db, actor, settings, base_draft)
    if isinstance(preview, Response):
        return preview
    if preview.preview_hash != submitted.preview_hash:
        return fail("诊断信息已变化，请重新核对", 409, code="FEEDBACK_PREVIEW_CHANGED")
    payload: dict[str, object] = {
        "submissionKey": str(submitted.submission_key),
        "kind": submitted.kind,
        "markdown": submitted.markdown,
        "contact": submitted.contact.model_dump(by_alias=True),
        "diagnostics": preview.diagnostics.model_dump(mode="json", by_alias=True, exclude_none=True),
    }
    release_read_transaction(db)
    try:
        receipt = send_to_official_site(payload, tuple(attachments))
    except FeedbackDeliveryError as failure:
        capture_exception(failure, persist=False)
        record_exception(
            LOGGER, "feedback.forward_failed", failure,
             source="feedback",
        )
        response = fail("反馈暂时无法发送，请稍后重试", 503, code="FEEDBACK_DELIVERY_FAILED")

        return response
    return ok(receipt)
