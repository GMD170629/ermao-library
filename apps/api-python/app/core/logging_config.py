"""Process logging setup that surfaces diagnostics context and tracebacks.

The app loggers rely on the standard library; this module only ensures a
handler/formatter exists that actually renders whitelisted ``extra`` context
fields.  Rendered output is sanitized as a second layer, and a sanitizing
filter is attached to ``uvicorn`` loggers so the server's own unhandled-error
output is safe too.
"""

from __future__ import annotations

import logging
import sys
from types import MethodType
from uuid import uuid4

from app.core.exception_diagnostics import (
    emergency_diagnostic,
    format_exception_diagnostics,
    sanitize_diagnostic_text,
)

LOGGER_NAME = "ermao.diagnostics"

UVICORN_SANITIZED_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_CONTEXT_EXTRA_KEYS = (
    "request_id",
    "task_id",
    "task_kind",
    "library_id",
    "resource_id",
    "source_node_id",
    "plan_id",
    "upload_id",
    "node_id",
    "book_id",
    "import_task_id",
    "stage",
    "outcome",
    "path",
    "method",
    "diagnostic_id",
    "operation_id",
    "target_ordinal",
    "step",
    "attempt",
    "parent_diagnostic_id",
)

_configured = False


def _sanitize_arg(value: object) -> object:
    return sanitize_diagnostic_text(value) if isinstance(value, str) else value


class SanitizingFilter(logging.Filter):
    """Redact credentials from a record before its handlers format it.

    ``preserve_args`` keeps ``record.msg``/``record.args`` intact so formatters
    such as uvicorn's ``AccessFormatter`` can unpack their positional contract;
    only string argument values are sanitized.  Otherwise the full message is
    rendered first so combined fields (for example ``"%s=%s"``) can be
    detected, then sanitized, and the arguments are dropped so they cannot be
    formatted a second time.
    """

    def __init__(self, *, preserve_args: bool = False) -> None:
        super().__init__()
        self.preserve_args = preserve_args

    def filter(self, record: logging.LogRecord) -> bool:
        self._sanitize_exception(record)
        if self.preserve_args:
            self._sanitize_args_in_place(record)
        else:
            self._collapse_message(record)
        return True

    def _sanitize_exception(self, record: logging.LogRecord) -> None:
        if record.exc_info:
            original = record.exc_info[1]
            try:
                text = format_exception_diagnostics(original)["traceback"] if original else ""
            except Exception as formatting_error:  # noqa: BLE001 - independent stderr
                diagnostic_id = getattr(record, "diagnostic_id", None) or f"diag_{uuid4().hex}"
                if original is not None:
                    emergency_diagnostic("logging.original_exception", original,
                                         diagnostic_id=diagnostic_id)
                emergency_diagnostic("logging.exception_format_failed", formatting_error,
                                     diagnostic_id=f"diag_{uuid4().hex}", parent_diagnostic_id=diagnostic_id)
                text = "[exception formatting failed; see stderr diagnostic]"
            record.exc_text = sanitize_diagnostic_text(text)
        elif record.exc_text:
            record.exc_text = sanitize_diagnostic_text(record.exc_text)

    def _sanitize_args_in_place(self, record: logging.LogRecord) -> None:
        if isinstance(record.args, tuple):
            record.args = tuple(_sanitize_arg(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: _sanitize_arg(value) for key, value in record.args.items()
            }

    def _collapse_message(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception as error:  # noqa: BLE001 - retain formatter cause
            emergency_diagnostic("logging.message_format_failed", error,
                                 diagnostic_id=f"diag_{uuid4().hex}")
            # Do not call the same broken __str__ a second time. A literal
            # template is safe to retain; non-text objects retain their type.
            message = record.msg if isinstance(record.msg, str) else f"[unformattable {type(record.msg).__name__}]"
        record.msg = sanitize_diagnostic_text(message)
        record.args = None


class ContextFormatter(logging.Formatter):
    """Render diagnostics context and sanitize the final output."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = " ".join(
            f"{key}={getattr(record, key)}"
            for key in _CONTEXT_EXTRA_KEYS
            if getattr(record, key, None) is not None
        )
        rendered = f"{base} {context}".rstrip() if context else base
        return sanitize_diagnostic_text(rendered)


def install_uvicorn_sanitizer() -> None:
    """Attach the sanitizing filter to uvicorn loggers without replacing them."""

    for name in UVICORN_SANITIZED_LOGGERS:
        preserve_args = name == "uvicorn.access"
        logger = logging.getLogger(name)
        if not any(
            isinstance(existing, SanitizingFilter)
            and existing.preserve_args == preserve_args
            for existing in logger.filters
        ):
            logger.addFilter(SanitizingFilter(preserve_args=preserve_args))


def _handler_failure(handler: logging.Handler, record: logging.LogRecord) -> None:
    """Replace logging.handleError's raw traceback/argument dump safely."""
    error = sys.exception()
    if error is None:
        error = RuntimeError("logging handler reported failure without an exception")
    diagnostic_id = getattr(record, "diagnostic_id", None) or f"diag_{uuid4().hex}"
    if record.exc_info and record.exc_info[1] is not None:
        emergency_diagnostic("logging.original_exception", record.exc_info[1],
                             diagnostic_id=diagnostic_id)
    emergency_diagnostic("logging.handler_failed", error,
                         diagnostic_id=f"diag_{uuid4().hex}", parent_diagnostic_id=diagnostic_id)
    try:
        sys.stderr.write(sanitize_diagnostic_text(record.getMessage()) + "\n")
    except Exception as secondary:  # noqa: BLE001 - independent last output
        emergency_diagnostic("logging.primary_fallback_failed", secondary,
                             diagnostic_id=f"diag_{uuid4().hex}", parent_diagnostic_id=diagnostic_id)


def install_handler_fallback(handler: logging.Handler) -> None:
    handler.handleError = MethodType(_handler_failure, handler)


def configure_logging(level: int = logging.INFO, *, force: bool = False) -> None:
    """Attach one context formatter to the root logger (idempotent).

    Existing handlers are preserved; a context handler is only added when the
    root logger has no stream handler yet.  Skipped under pytest so test
    capture owns the root logging configuration, unless ``force`` is set.
    """

    global _configured
    if (_configured and not force) or ("pytest" in sys.modules and not force):
        return
    _configured = True

    install_uvicorn_sanitizer()

    root = logging.getLogger()
    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            ContextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root.addHandler(handler)
    for handler in root.handlers:
        if not any(isinstance(existing, SanitizingFilter) for existing in handler.filters):
            handler.addFilter(SanitizingFilter())
        install_handler_fallback(handler)
    for name in UVICORN_SANITIZED_LOGGERS:
        for handler in logging.getLogger(name).handlers:
            install_handler_fallback(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)


__all__ = [
    "ContextFormatter",
    "SanitizingFilter",
    "configure_logging",
    "install_uvicorn_sanitizer",
]
