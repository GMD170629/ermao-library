"""ASGI boundaries that record unhandled HTTP failures at the right layer.

Two instances are installed by the composition root:

* the inner instance converts unhandled route errors into a failure response using the existing HTTP envelope;
* the outer instance additionally covers middleware-layer database and
  permission failures and records before re-raising so existing propagation
  contracts are preserved.

Both track whether the response already started, so a failure during body
streaming is recorded but never followed by a second error response.
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exception_diagnostics import (
    DiagnosticSnapshot,
    capture_exception,
    deferred_exception_persistence,
    exception_message,
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
        pending: list[DiagnosticSnapshot] = []
        try:
            with deferred_exception_persistence(
            ) as pending:
                await self._invoke(scope, receive, send)
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
        except BaseException as error:  # record cancellation without converting it to HTTP 500
            capture_exception(error)
            snapshot = self._prepare(scope, error)
            await run_in_threadpool(
                persist_exception_diagnostic,
                LOGGER,
                snapshot,
                self.session_factory,
            )
            if isinstance(error, Exception) and self.respond_with_json and not response_started:
                await self._send_failure(scope, receive, send, snapshot, error)
                return
            raise

    def _prepare(self, scope: Scope, error: BaseException) -> DiagnosticSnapshot:
        return prepare_exception_diagnostic(
            LOGGER,
            "api.request_failed",
            error,
            source="system",
            action="api.request_failed",
        )

    async def _send_failure(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        snapshot: DiagnosticSnapshot,
        error: BaseException,
    ) -> None:
        response = fail(
            exception_message(error),
            status_code=500,
            details={"exceptionType": type(error).__name__},
            code=type(error).__name__,
        )
        await response(scope, receive, send)


__all__ = ["DiagnosticBoundaryMiddleware"]
