"""Process logging setup that surfaces diagnostics context and tracebacks.

The app loggers rely on the standard library; this module only ensures a
handler/formatter exists that actually renders whitelisted ``extra`` context
fields alongside the exception traceback, even before any business database is
available.
"""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "ermao.diagnostics"

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


class ContextFormatter(logging.Formatter):
    """Render ``extra`` diagnostics fields without dropping the traceback."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = " ".join(
            f"{key}={getattr(record, key)}"
            for key in _CONTEXT_EXTRA_KEYS
            if getattr(record, key, None) is not None
        )
        return f"{base} {context}".rstrip() if context else base


def configure_logging(level: int = logging.INFO) -> None:
    """Attach one context formatter to the root logger (idempotent).

    Skipped under pytest so test capture owns the root logging configuration.
    """

    global _configured
    if _configured or "pytest" in sys.modules:
        return
    _configured = True

    root = logging.getLogger()
    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            ContextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)


__all__ = ["ContextFormatter", "configure_logging"]
