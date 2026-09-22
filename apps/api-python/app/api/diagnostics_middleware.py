"""ASGI boundaries that record unhandled HTTP failures at the right layer.

Two instances are installed by the composition root:

* the inner instance converts unhandled route errors into a correlation-id
  response without leaking internals;
* the outer instance additionally covers middleware-layer database and
  permission failures and records before re-raising so existing propagation
  contracts are preserved.

Both track whether the response already started, so a failure during body
streaming is recorded but never followed by a second error response.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exception_diagnostics import (
    DiagnosticSnapshot,
    deferred_exception_persistence,
    persist_exception_diagnostic,
    prepare_exception_diagnostic,
)
from app.schemas.responses import fail

LOGGER = logging.getLogger("ermao.api_diagnostics")


class DiagnosticBoundaryMiddleware:
    """Record unhandled HTTP exceptions and optionally emit a 500 envelope."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        session_factory: Any,
        respond_with_json: bool,
    ) -> None:
        self.app = app
        self.session_factory = session_factory
        self.respond_with_json = respond_with_json

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        if self.respond_with_json:
            await self._invoke(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_id = headers.get("x-request-id") or uuid4().hex

        async def correlated_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (
                            b"x-request-id",
                            request_id.encode("latin-1", errors="replace"),
                        ),
                    ],
                }
            await send(message)

        pending: list[DiagnosticSnapshot] = []
        try:
            with deferred_exception_persistence(
                context={
                    "path": scope.get("path", ""),
                    "method": scope.get("method", ""),
                    "request_id": request_id,
                }
            ) as pending:
                await self._invoke(scope, receive, correlated_send)
        finally:
            # The application has unwound its sessions and transactions before
            # independent diagnostic writes can acquire the database writer.
            for snapshot in pending:
                await run_in_threadpool(
                    persist_exception_diagnostic, LOGGER, snapshot, self.session_factory
                )

    async def _invoke(self, scope: Scope, receive: Receive, send: Send) -> None:
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as error:  # unified HTTP failure boundary
            snapshot = self._prepare(scope, error)
            await run_in_threadpool(
                persist_exception_diagnostic,
                LOGGER,
                snapshot,
                self.session_factory,
            )
            if self.respond_with_json and not response_started:
                await self._send_failure(scope, receive, send, snapshot)
                return
            raise

    def _prepare(self, scope: Scope, error: BaseException) -> DiagnosticSnapshot:
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        return prepare_exception_diagnostic(
            LOGGER,
            "api.request_failed",
            error,
            context={
                "stage": "api_request" if self.respond_with_json else "http_boundary",
                "path": scope.get("path", ""),
                "method": scope.get("method", ""),
                **(
                    {"request_id": headers["x-request-id"]}
                    if headers.get("x-request-id")
                    else {}
                ),
            },
            source="system",
            action="api.request_failed",
        )

    async def _send_failure(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        snapshot: DiagnosticSnapshot,
    ) -> None:
        response = fail(
            "服务器内部错误",
            status_code=500,
            details={"eventId": snapshot.diagnostic_id},
            code="INTERNAL_ERROR",
        )
        response.headers["X-Error-Id"] = snapshot.diagnostic_id
        await response(scope, receive, send)


__all__ = ["DiagnosticBoundaryMiddleware"]
