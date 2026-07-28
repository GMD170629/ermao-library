"""Exception handlers for validated public HTTP errors."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.contracts.http import ErrorEnvelope
from app.contracts.http_errors import HttpContractError
from app.contracts.validation_errors import (
    RequestValidationErrorBody,
    RequestValidationErrorResponse,
    RequestValidationIssue,
    ValidationInputSummary,
)
from app.core.auth import delete_session_cookie
from app.core.config import get_settings


async def typed_http_error_handler(
    _request: Request,
    error: HttpContractError,
) -> JSONResponse:
    envelope_type = ErrorEnvelope[error.body_model]
    envelope = envelope_type(error=error.body)
    response = JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json", by_alias=True),
    )
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
    envelope = RequestValidationErrorResponse(
        error=RequestValidationErrorBody(
            message="请求参数校验失败",
            details=issues,
        )
    )
    return JSONResponse(
        status_code=422,
        content=envelope.model_dump(mode="json", by_alias=True),
    )
