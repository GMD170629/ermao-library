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
import traceback

from app.core.exception_diagnostics import sanitize_diagnostic_text

LOGGER_NAME = "ermao.diagnostics"

UVICORN_SANITIZED_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_CONTEXT_EXTRA_KEYS = (
    "request_id",
    "task_id",
    "task_kind",
    "library_id",
    "resource_id",
    "source_node_id",
    "stage",
    "outcome",
    "path",
    "method",
    "diagnostic_id",
)

_configured = False


class SanitizingFilter(logging.Filter):
    """Redact credentials from a record before its handlers format it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and not record.exc_text:
            try:
                text = "".join(traceback.format_exception(*record.exc_info))
            except Exception:  # noqa: BLE001 - never break logging on diagnostics
                text = ""
            record.exc_text = sanitize_diagnostic_text(text)
        if record.args:
            try:
                message = record.getMessage()
            except Exception:  # noqa: BLE001 - fall back to the raw template
                message = str(record.msg)
            record.msg = sanitize_diagnostic_text(message)
            record.args = None
        elif isinstance(record.msg, str):
            record.msg = sanitize_diagnostic_text(record.msg)
        return True


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
        logger = logging.getLogger(name)
        if not any(
            isinstance(existing, SanitizingFilter) for existing in logger.filters
        ):
            logger.addFilter(SanitizingFilter())


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
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)


__all__ = [
    "ContextFormatter",
    "SanitizingFilter",
    "configure_logging",
    "install_uvicorn_sanitizer",
]
