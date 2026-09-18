"""Unified exception diagnostics recording for API, worker, and background tasks.

The entry point keeps the original exception (type, message, traceback, chain)
instead of the current call stack, emits a structured running log, and best
effort persists a ``SystemEvent`` through an independent session so the
diagnostic survives business transaction rollbacks.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.safe_errors import mask_email

SessionFactory = Callable[[], Session]

MAX_TRACEBACK_CHARS = 16_000
MAX_CHAIN_ITEMS = 8
MAX_DIAGNOSTIC_MESSAGE_CHARS = 2_000
_TAIL_SHARE = 0.4

_CONTEXT_WIRE_KEYS = {
    "request_id": "requestId",
    "task_id": "taskId",
    "task_kind": "taskKind",
    "library_id": "libraryId",
    "resource_id": "resourceId",
    "source_node_id": "sourceNodeId",
    "stage": "stage",
    "outcome": "outcome",
    "path": "path",
    "method": "method",
    "attempt": "attempt",
}

_LOG_EXTRA_KEYS = (
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
    "attempt",
    "diagnostic_id",
)

_SQL_PARAMETERS = re.compile(r"\[parameters:.*?\](\s*\[.*?\])?", re.DOTALL)
_SQL_BACKGROUND = re.compile(r"\(Background on this error at: [^)]+\)")
_AUTHORIZATION = re.compile(
    r"(?i)\b(authorization|proxy-authorization|set-cookie|cookie)\b\s*[:=]\s*[^\r\n]+"
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"client[_-]?secret|refresh[_-]?token)\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:token|key|secret|password|access_token|api_key)=)[^&\s]+"
)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

_session_factory: SessionFactory | None = None
_hooks_installed = False


def configure_exception_storage(factory: SessionFactory | None) -> None:
    """Set the process-wide session factory used by best-effort persistence."""

    global _session_factory
    _session_factory = factory


def reset_exception_storage() -> None:
    configure_exception_storage(None)


def sanitize_diagnostic_text(text: object) -> str:
    """Redact credentials and SQL parameters from diagnostic text."""

    value = str(text)
    value = _SQL_PARAMETERS.sub("[parameters: [redacted]]", value)
    value = _SQL_BACKGROUND.sub("", value)
    value = _AUTHORIZATION.sub(lambda match: f"{match.group(1)}: [redacted]", value)
    value = _CREDENTIAL_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[redacted]", value
    )
    value = _BEARER.sub("Bearer [redacted]", value)
    value = _QUERY_SECRET.sub(r"\1[redacted]", value)
    value = _EMAIL.sub(lambda match: mask_email(match.group(0)), value)
    return value


def _qualified_type(error: BaseException) -> str:
    error_type = type(error)
    module = getattr(error_type, "__module__", "") or ""
    name = getattr(error_type, "__qualname__", None) or error_type.__name__
    return f"{module}.{name}" if module and module != "builtins" else name


def _bound_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    marker = "\n...[diagnostic truncated]...\n"
    head_limit = int(limit * (1 - _TAIL_SHARE))
    tail_limit = max(0, limit - head_limit - len(marker))
    return text[:head_limit] + marker + text[-tail_limit:], True


def _chain_entries(error: BaseException) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        cause = current.__cause__
        context = current.__context__ if cause is None else None
        entries.append(
            {
                "type": _qualified_type(current),
                "message": sanitize_diagnostic_text(current)[
                    :MAX_DIAGNOSTIC_MESSAGE_CHARS
                ],
            }
        )
        current = cause if cause is not None else context
        if len(entries) >= MAX_CHAIN_ITEMS:
            break
    return entries


def format_exception_diagnostics(
    error: BaseException,
    *,
    max_traceback_chars: int = MAX_TRACEBACK_CHARS,
) -> dict[str, Any]:
    """Return sanitized structured diagnostics for one original exception."""

    raw_traceback = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    traceback_text, truncated = _bound_text(
        sanitize_diagnostic_text(raw_traceback), max_traceback_chars
    )
    location: str | None = None
    if error.__traceback__ is not None:
        frames = traceback.extract_tb(error.__traceback__)
        if frames:
            last = frames[-1]
            location = f"{last.filename}:{last.lineno}"
    return {
        "exceptionType": _qualified_type(error),
        "message": sanitize_diagnostic_text(error)[:MAX_DIAGNOSTIC_MESSAGE_CHARS],
        "traceback": traceback_text,
        "chain": _chain_entries(error),
        "location": sanitize_diagnostic_text(location) if location else None,
        "truncated": truncated,
    }


def build_exception_metadata(
    error: BaseException,
    *,
    diagnostic_id: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "diagnostics": {
            "id": diagnostic_id,
            **format_exception_diagnostics(error),
        }
    }
    metadata.update(_context_metadata(context))
    return metadata


def _context_metadata(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
    result: dict[str, Any] = {}
    for key, value in context.items():
        wire_key = _CONTEXT_WIRE_KEYS.get(key)
        if wire_key is None or value is None:
            continue
        result[wire_key] = (
            sanitize_diagnostic_text(value)[:MAX_DIAGNOSTIC_MESSAGE_CHARS]
            if isinstance(value, str)
            else value
        )
    return result


def _log_extra(context: dict[str, Any] | None, diagnostic_id: str) -> dict[str, Any]:
    extra: dict[str, Any] = {"diagnostic_id": diagnostic_id}
    for key in _LOG_EXTRA_KEYS:
        if key == "diagnostic_id":
            continue
        value = (context or {}).get(key)
        if value is not None:
            extra[key] = value
    return extra


def record_exception(
    logger: logging.Logger,
    event: str,
    error: BaseException,
    *,
    level: str = "error",
    context: dict[str, Any] | None = None,
    source: str = "system",
    action: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    session_factory: SessionFactory | None = None,
) -> str:
    """Record one exception to running logs and best-effort SystemEvent storage.

    Returns the stable diagnostic id that callers may expose as a correlation
    handle even when persistence is degraded.
    """

    diagnostic_id = f"diag_{uuid4().hex}"
    log_level = logging.WARNING if level == "warning" else logging.ERROR
    # ``exc_info=error`` formats the original exception traceback instead of
    # the current call stack; ``diagnostic_id`` travels in ``extra`` so the
    # context formatter can render it without changing the stable event name.
    logger.log(
        log_level,
        event,
        exc_info=error,
        extra=_log_extra(context, diagnostic_id),
    )

    factory = session_factory or _session_factory
    if factory is None:
        return diagnostic_id
    _persist_best_effort(
        logger,
        event=event,
        error=error,
        diagnostic_id=diagnostic_id,
        level=level,
        context=context,
        source=source,
        action=action or event,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        factory=factory,
    )
    return diagnostic_id


def _persist_best_effort(
    logger: logging.Logger,
    *,
    event: str,
    error: BaseException,
    diagnostic_id: str,
    level: str,
    context: dict[str, Any] | None,
    source: str,
    action: str,
    actor_type: str,
    actor_id: str | None,
    target_type: str | None,
    target_id: str | None,
    factory: SessionFactory,
) -> bool:
    # Imported lazily so this cross-cutting core module does not pull the
    # system capability into every importer and cannot create an import cycle.
    from app.modules.system.infrastructure.events import (
        prepare_system_event,
        write_prepared_system_events,
    )

    session: Session | None = None
    try:
        metadata = build_exception_metadata(
            error, diagnostic_id=diagnostic_id, context=context
        )
        prepared = prepare_system_event(
            event_id=diagnostic_id,
            level=level,
            source=source,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            message=sanitize_diagnostic_text(error),
            metadata=metadata,
        )
        session = factory()
        write_prepared_system_events(session, [prepared])
        session.commit()
        return True
    except Exception as persistence_error:  # noqa: BLE001 - bounded degradation
        if session is not None:
            try:
                session.rollback()
            except Exception:  # noqa: BLE001, S110 - never mask the failure
                pass
        logger.warning(
            "exception_diagnostics.persist_failed diagnostic_id=%s event=%s "
            "error_type=%s",
            diagnostic_id,
            event,
            type(persistence_error).__name__,
        )
        return False
    finally:
        if session is not None:
            session.close()


def install_exception_hooks() -> None:
    """Install process/thread fallbacks once, preserving prior hooks."""

    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    previous_sys_hook = sys.excepthook

    def _sys_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        try:
            record_exception(
                logging.getLogger("ermao.unhandled"),
                "process.unhandled_exception",
                exc,
                context={"stage": "process"},
            )
        except Exception:  # noqa: BLE001, S110 - hooks must not mask failures
            pass
        finally:
            previous_sys_hook(exc_type, exc, tb)

    sys.excepthook = _sys_hook

    previous_thread_hook = threading.excepthook

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        try:
            if args.exc_value is not None:
                thread_name = getattr(args.thread, "name", None)
                record_exception(
                    logging.getLogger("ermao.unhandled"),
                    "thread.unhandled_exception",
                    args.exc_value,
                    context={"stage": "thread", "path": thread_name},
                )
        except Exception:  # noqa: BLE001, S110 - hooks must not mask failures
            pass
        finally:
            previous_thread_hook(args)

    threading.excepthook = _thread_hook


def install_loop_exception_handler(loop: Any) -> None:
    """Record unobserved asyncio task/loop exceptions without swallowing them."""

    if loop is None or not hasattr(loop, "set_exception_handler"):
        return
    previous = loop.get_exception_handler() if hasattr(loop, "get_exception_handler") else None

    def _handler(active_loop: Any, context: dict[str, Any]) -> None:
        error = context.get("exception")
        if error is not None:
            try:
                record_exception(
                    logging.getLogger("ermao.unhandled"),
                    "asyncio.unhandled_exception",
                    error,
                    context={"stage": "event_loop"},
                )
            except Exception:  # noqa: BLE001, S110 - hooks must not mask failures
                pass
        if previous is not None:
            previous(active_loop, context)
        else:
            active_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


__all__ = [
    "build_exception_metadata",
    "configure_exception_storage",
    "format_exception_diagnostics",
    "install_exception_hooks",
    "install_loop_exception_handler",
    "record_exception",
    "reset_exception_storage",
    "sanitize_diagnostic_text",
]
