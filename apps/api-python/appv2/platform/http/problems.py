from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.exceptions import HTTPException

from appv2.platform.http.models import CamelModel
from appv2.platform.i18n import Locale, translate

logger = logging.getLogger(__name__)


class ProblemDetails(CamelModel):
    type: str
    title: str
    status: int
    code: str
    detail: str
    params: dict[str, Any] = Field(default_factory=dict)
    trace_id: str


class AppProblem(Exception):
    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        message_key: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.message_key = message_key
        self.params = params or {}


def request_locale(request: Request) -> Locale:
    value = request.headers.get("accept-language", "").lower()
    return "en-US" if value.startswith("en") else "zh-CN"


def trace_id_for(request: Request) -> str:
    return str(getattr(request.state, "trace_id", uuid.uuid4().hex))


def response_for(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    message_key: str,
    params: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ProblemDetails(
        type=f"https://shuku.app/problems/{code.lower().replace('_', '-')}",
        title=title,
        status=status,
        code=code,
        detail=translate(message_key, request_locale(request)),
        params=params or {},
        trace_id=trace_id_for(request),
    )
    return JSONResponse(
        body.model_dump(by_alias=True),
        status_code=status,
        media_type="application/problem+json",
    )


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppProblem)
    async def handle_app_problem(request: Request, error: AppProblem) -> JSONResponse:
        return response_for(
            request,
            status=error.status,
            code=error.code,
            title=error.title,
            message_key=error.message_key,
            params=error.params,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, error: RequestValidationError) -> JSONResponse:
        return response_for(
            request,
            status=422,
            code="INVALID_REQUEST",
            title="Validation failed",
            message_key="invalid_request",
            params={"errors": error.errors()},
        )

    @app.exception_handler(HTTPException)
    async def handle_http(request: Request, error: HTTPException) -> JSONResponse:
        mapping = {
            401: ("AUTHENTICATION_REQUIRED", "Authentication required", "authentication_required"),
            403: ("PERMISSION_DENIED", "Permission denied", "permission_denied"),
            404: ("NOT_FOUND", "Resource not found", "not_found"),
            409: ("CONFLICT", "Conflict", "conflict"),
        }
        code, title, key = mapping.get(
            error.status_code, ("HTTP_ERROR", "HTTP error", "invalid_request")
        )
        return response_for(
            request,
            status=error.status_code,
            code=code,
            title=title,
            message_key=key,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled appv2 request error", exc_info=error)
        return response_for(
            request,
            status=500,
            code="INTERNAL_ERROR",
            title="Internal server error",
            message_key="internal_error",
        )
