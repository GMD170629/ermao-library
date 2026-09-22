"""One MCP failure boundary, including SDK argument validation and dispatch."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.contracts.automation_upload import UploadError
from app.core.exception_diagnostics import (
    DiagnosticSnapshot,
    deferred_exception_persistence,
    persist_exception_diagnostic,
    record_exception,
)
from app.modules.automation.domain.access import AutomationAccessError
from app.modules.library.public import (
    FileMoveError,
    MetadataPatchError,
    SourceAccessError,
)
from app.modules.metadata.public import StandardMetadataError

LOGGER = logging.getLogger("ermao.automation_diagnostics")
_REJECTED = (
    AutomationAccessError,
    UploadError,
    FileMoveError,
    MetadataPatchError,
    SourceAccessError,
    StandardMetadataError,
)
_CORRELATION_KEYS = (
    "request_id",
    "operation_id",
    "plan_id",
    "upload_id",
    "library_id",
    "source_node_id",
    "node_id",
)


def record_mcp_failure(error: BaseException, *, stage: str) -> str:
    return record_exception(
        LOGGER,
        "automation.request_failed",
        error,
        level="warning"
        if isinstance(error, (*_REJECTED, ValidationError))
        or isinstance(error, ToolError)
        and not isinstance(error, UnexpectedToolError)
        else "error",
        context={"stage": stage},
        source="automation",
    )


class DiagnosticMcpServer(MCPServer):
    """Intercept the public SDK call before it redacts/terminates exceptions."""

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context
    ) -> Any:
        pending: list[DiagnosticSnapshot] = []
        try:
            with deferred_exception_persistence(
                context={
                    "step": name,
                    **{
                        key: value
                        for key in _CORRELATION_KEYS
                        if isinstance(value := arguments.get(key), str)
                    },
                }
            ) as pending:
                try:
                    return await super().call_tool(name, arguments, context)
                except Exception as error:
                    diagnostic_id = record_mcp_failure(error, stage="mcp_tool")
                    cause = error
                    while isinstance(cause, ToolError) and cause.__cause__ is not None:
                        cause = cause.__cause__
                    if isinstance(cause, _REJECTED):
                        code = str(cause)
                    elif isinstance(cause, ValidationError):
                        code = "INVALID_ARGUMENT"
                    elif isinstance(error, ToolError) and str(error).startswith(
                        "Unknown tool:"
                    ):
                        code = "UNKNOWN_TOOL"
                    else:
                        code = "INTERNAL_ERROR"
                    # The SDK renders only this safe text, while retaining the
                    # original exception for diagnostics and in-process callers.
                    raise ToolError(
                        f"{code}: 操作失败 / Operation failed (diagnostic_id={diagnostic_id})"
                    ) from error
        finally:
            for snapshot in pending:
                await run_in_threadpool(persist_exception_diagnostic, LOGGER, snapshot)
