"""Raw process logging; no redaction, correlation decoration or truncation."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from types import MethodType
from uuid import uuid4

from app.core.exception_diagnostics import (
    diagnostic_text,
    emergency_diagnostic,
    format_exception_diagnostics,
)

LOGGER_NAME = "ermao.diagnostics"

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_configured = False


class DailyFileHandler(logging.Handler):
    """Adapt ordinary runtime messages to the same daily JSONL outlet."""

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "unified_diagnostic", False):
            return
        try:
            from app.modules.system.infrastructure.log_files import append_log_event

            level = "error" if record.levelno >= logging.ERROR else "warning" if record.levelno >= logging.WARNING else "info" if record.levelno >= logging.INFO else "debug"
            metadata = {}
            if record.exc_info and record.exc_info[1] is not None:
                metadata["diagnostics"] = format_exception_diagnostics(record.exc_info[1])
            append_log_event({
                "id": f"log_{uuid4().hex}", "level": level, "source": record.name,
                "actorType": "system", "actorId": None, "action": "runtime.message",
                "message": record.getMessage(), "metadata": metadata,
                "createdAt": datetime.fromtimestamp(record.created, UTC).isoformat(),
            })
        except Exception as error:  # noqa: BLE001 - isolate physical log output failure
            emergency_diagnostic("logging.file_handler_failed", error)


class ExceptionFormatter(logging.Formatter):
    """Use the same complete raw traceback formatter as the exception entry point."""

    def formatException(self, ei) -> str:
        error = ei[1]
        return (
            str(format_exception_diagnostics(error)["traceback"])
            if error is not None
            else ""
        )

    def format(self, record: logging.LogRecord) -> str:
        output = super().format(record)
        operations = getattr(record, "database_operations", None)
        if operations:
            output += "\ndatabaseOperations=" + json.dumps(
                operations, ensure_ascii=False, default=str
            )
        return output


def _handler_failure(handler: logging.Handler, record: logging.LogRecord) -> None:
    """Replace logging.handleError's raw traceback/argument dump safely."""
    error = sys.exception()
    if error is None:
        error = RuntimeError("logging handler reported failure without an exception")
    if record.exc_info and record.exc_info[1] is not None:
        emergency_diagnostic("logging.original_exception", record.exc_info[1])
    emergency_diagnostic(
        "logging.handler_failed",
        error,
    )
    try:
        sys.stderr.write(diagnostic_text(record.getMessage()) + "\n")
    except Exception as secondary:  # noqa: BLE001 - independent last output
        emergency_diagnostic(
            "logging.primary_fallback_failed",
            secondary,
        )


def install_handler_fallback(handler: logging.Handler) -> None:
    handler.handleError = MethodType(_handler_failure, handler)


def configure_logging(level: int = logging.ERROR, *, force: bool = False) -> None:
    """Attach the raw exception formatter to the root logger (idempotent).

    Existing handlers are preserved; a stream handler is only added when the
    root logger has no stream handler yet.  Skipped under pytest so test
    capture owns the root logging configuration, unless ``force`` is set.
    """

    global _configured
    if (_configured and not force) or ("pytest" in sys.modules and not force):
        return
    _configured = True

    root = logging.getLogger()
    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            ExceptionFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root.addHandler(stream_handler)
    for handler in root.handlers:
        install_handler_fallback(handler)
        handler.setLevel(level)
    if not any(isinstance(handler, DailyFileHandler) for handler in root.handlers):
        root.addHandler(DailyFileHandler())
    for handler in root.handlers:
        if isinstance(handler, DailyFileHandler):
            handler.setLevel(logging.DEBUG)
    for name in UVICORN_LOGGERS:
        for handler in logging.getLogger(name).handlers:
            install_handler_fallback(handler)
    root.setLevel(logging.DEBUG)


__all__ = ["ExceptionFormatter", "configure_logging"]
