"""Exception handlers for validated public HTTP errors."""

from __future__ import annotations

import re
from typing import cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.contracts.http import ErrorEnvelope, MessageError
from app.contracts.http_errors import HttpContractError
from app.contracts.validation_errors import (
    RequestValidationErrorBody,
    RequestValidationErrorResponse,
    RequestValidationIssue,
    ValidationInputSummary,
)
from app.core.auth import delete_session_cookie
from app.core.config import get_settings

_STABLE_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


async def typed_http_error_handler(
    _request: Request,
    error: HttpContractError[BaseModel],
) -> JSONResponse:
    envelope_type = cast(
        type[ErrorEnvelope[BaseModel]],
        ErrorEnvelope.__class_getitem__(error.body_model),
    )
    envelope = envelope_type(error=error.body)
    response = JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json", by_alias=True),
    )
    if (
        isinstance(error.body, MessageError)
        and error.body.code is not None
        and _STABLE_ERROR_CODE.fullmatch(error.body.code)
    ):
        response.headers["X-Error-Code"] = error.body.code
    if error.clear_session_cookie:
        delete_session_cookie(response, get_settings())
    return response


def _validation_input_summary(value: object) -> ValidationInputSummary:
    if value is None:
        return ValidationInputSummary(kind="null")
    if isinstance(value, bool):
        return ValidationInputSummary(kind="boolean", value=value)
    if isinstance(value, int):
        return ValidationInputSummary(kind="integer", value=value)
    if isinstance(value, float):
        return ValidationInputSummary(kind="number", value=value)
    if isinstance(value, str):
        return ValidationInputSummary(
            kind="string",
            value=value[:200],
            length=len(value),
        )
    if isinstance(value, (list, tuple)):
        return ValidationInputSummary(kind="array", length=len(value))
    if isinstance(value, dict):
        return ValidationInputSummary(
            kind="object",
            length=len(value),
            keys=sorted(str(key)[:100] for key in value)[:20],
        )
    return ValidationInputSummary(kind="object")


async def request_validation_error_handler(
    _request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    issues = [
        RequestValidationIssue(
            loc=list(issue.get("loc") or []),
            message=str(issue.get("msg") or "Invalid request"),
            type=str(issue.get("type") or "validation_error"),
            input=_validation_input_summary(issue.get("input")),
        )
        for issue in error.errors()
    ]
    exact_locator_failure = any(
        issue.get("type") == "reader_locator_not_exact" for issue in error.errors()
    )
    envelope = RequestValidationErrorResponse(
        error=RequestValidationErrorBody(
            code=(
                "READER_LOCATOR_NOT_EXACT"
                if exact_locator_failure
                else "REQUEST_VALIDATION_ERROR"
            ),
            message=(
                "Readium Locator 缺少可验证的精确正文锚点"
                if exact_locator_failure
                else "请求参数校验失败"
            ),
            details=issues,
        )
    )
    return JSONResponse(
        status_code=422,
        content=envelope.model_dump(mode="json", by_alias=True),
    )
