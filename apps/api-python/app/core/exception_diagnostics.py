"""Unified exception diagnostics recording for API, worker, and background tasks.

The entry point keeps the original exception (type, message, traceback, chain)
instead of the current call stack.  Preparing a diagnostic is separated from
persisting it: the sanitized snapshot and running log are produced before any
rollback or cleanup, while the independent ``SystemEvent`` transaction is
written later at a safe boundary.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.safe_errors import mask_email

SessionFactory = Callable[[], Session]

MAX_TRACEBACK_CHARS = 16_000
MAX_CHAIN_ITEMS = 8
MAX_DIAGNOSTIC_MESSAGE_CHARS = 2_000
_TAIL_SHARE = 0.4
_DIAGNOSTIC_ATTR = "_ermao_diagnostic_snapshot"

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
_HEADER_SECRET = re.compile(
    r"(?im)^([ \t]*(?:authorization|proxy-authorization|x-api-key|x-auth-token|"
    r"private-token|cookie|set-cookie)[ \t]*[:=][ \t]*)\S.*$"
)
_CREDENTIAL_QUOTED = re.compile(
    r"(?i)([\"']?(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"client[_-]?secret|refresh[_-]?token|credential|passphrase)[\"']?\s*[:=]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
)
_CREDENTIAL_BARE = re.compile(
    r"(?i)([\"']?\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"client[_-]?secret|refresh[_-]?token|credential|passphrase)\b[\"']?\s*[:=]\s*)"
    r"[^\r\n]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:token|key|secret|password|access_token|api_key)=)[^&\s]+"
)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

_session_factory: SessionFactory | None = None
_hooks_installed = False


@dataclass
class DiagnosticSnapshot:
    """Sanitized, prepared diagnostic ready for logging and persistence."""

    diagnostic_id: str
    event: str
    level: str
    message: str
    metadata: dict[str, Any]
    source: str
    action: str
    actor_type: str
    actor_id: str | None
    target_type: str | None
    target_id: str | None
    persisted: bool = False


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
    value = _HEADER_SECRET.sub(lambda match: f"{match.group(1)}[redacted]", value)
    value = _CREDENTIAL_QUOTED.sub(
        lambda match: f"{match.group(1)}[redacted]", value
    )
    value = _CREDENTIAL_BARE.sub(lambda match: f"{match.group(1)}[redacted]", value)
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


def _sanitized_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
    result: dict[str, Any] = {}
    for key, value in context.items():
        if value is None:
            continue
        result[key] = (
            sanitize_diagnostic_text(value)[:MAX_DIAGNOSTIC_MESSAGE_CHARS]
            if isinstance(value, str)
            else value
        )
    return result


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
    safe = _sanitized_context(context)
    result: dict[str, Any] = {}
    for key, value in safe.items():
        wire_key = _CONTEXT_WIRE_KEYS.get(key)
        if wire_key is None:
            continue
        result[wire_key] = value
    return result


def _context_log_fields(context: dict[str, Any] | None) -> dict[str, Any]:
    safe = _sanitized_context(context)
    return {
        key: safe[key]
        for key in _LOG_EXTRA_KEYS
        if key != "diagnostic_id" and key in safe
    }


def _log_extra(context: dict[str, Any] | None, diagnostic_id: str) -> dict[str, Any]:
    extra = _context_log_fields(context)
    extra["diagnostic_id"] = diagnostic_id
    return extra


def _format_log_text(
    event: str,
    diagnostic_id: str,
    diagnostics: dict[str, Any],
    context: dict[str, Any] | None,
) -> str:
    fields = _context_log_fields(context)
    context_line = " ".join(f"{key}={value}" for key, value in fields.items())
    header = f"{event} diagnostic_id={diagnostic_id}"
    if context_line:
        header = f"{header} {context_line}"
    traceback_text = str(diagnostics.get("traceback") or "")
    location = diagnostics.get("location")
    body = traceback_text if traceback_text else str(diagnostics.get("message") or "")
    if location and str(location) not in body:
        body = f"{body}\nlocation={location}"
    return f"{header}\n{body}".rstrip()


def _existing_snapshot(error: BaseException) -> DiagnosticSnapshot | None:
    snapshot = getattr(error, _DIAGNOSTIC_ATTR, None)
    if isinstance(snapshot, DiagnosticSnapshot):
        return snapshot
    # Asyncio/anyio task boundaries may wrap the prepared failure in a group;
    # reuse the leaf diagnostic instead of creating a second main event.
    if isinstance(error, BaseExceptionGroup):
        for inner in error.exceptions:
            found = _existing_snapshot(inner)
            if found is not None:
                return found
    return None


def prepare_exception_diagnostic(
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
) -> DiagnosticSnapshot:
    """Emit a sanitized running log and return a reusable diagnostic snapshot.

    Calling this again for the same exception instance reuses the snapshot so a
    cross-layer propagation produces a single main event and diagnostic id.
    """

    existing = _existing_snapshot(error)
    if existing is not None:
        return existing

    diagnostic_id = f"diag_{uuid4().hex}"
    try:
        diagnostics = format_exception_diagnostics(error)
        log_text = _format_log_text(event, diagnostic_id, diagnostics, context)
        logger.log(
            logging.WARNING if level == "warning" else logging.ERROR,
            log_text,
            extra=_log_extra(context, diagnostic_id),
        )
    except Exception:  # noqa: BLE001 - diagnostics must never mask the failure
        diagnostics = {
            "exceptionType": _qualified_type(error),
            "message": "",
            "traceback": "",
            "chain": [],
            "location": None,
            "truncated": False,
        }
        logger.log(
            logging.WARNING if level == "warning" else logging.ERROR,
            "%s diagnostic_id=%s exception_type=%s",
            event,
            diagnostic_id,
            diagnostics["exceptionType"],
            extra=_log_extra(context, diagnostic_id),
        )

    metadata = {
        "diagnostics": {"id": diagnostic_id, **diagnostics},
        **_context_metadata(context),
    }
    snapshot = DiagnosticSnapshot(
        diagnostic_id=diagnostic_id,
        event=event,
        level=level,
        message=str(diagnostics.get("message") or _qualified_type(error)),
        metadata=metadata,
        source=source,
        action=action or event,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
    )
    try:
        setattr(error, _DIAGNOSTIC_ATTR, snapshot)
    except Exception:  # noqa: BLE001, S110 - some exceptions forbid attributes
        pass
    return snapshot


def _safe_rollback(session: Session) -> None:
    try:
        session.rollback()
    except Exception:  # noqa: BLE001, S110 - never mask the original failure
        pass


def _safe_close(session: Session) -> None:
    try:
        session.close()
    except Exception:  # noqa: BLE001, S110 - never mask the original failure
        pass


def persist_exception_diagnostic(
    logger: logging.Logger,
    snapshot: DiagnosticSnapshot,
    session_factory: SessionFactory | None = None,
) -> bool:
    """Best-effort persist one snapshot; never raises into business flow."""

    if snapshot.persisted:
        return True
    factory = session_factory or _session_factory
    if factory is None:
        return False

    # Imported lazily so this cross-cutting core module does not pull the
    # system capability into every importer and cannot create an import cycle.
    from app.modules.system.infrastructure.events import (
        prepare_system_event,
        write_prepared_system_events,
    )

    session: Session | None = None
    try:
        prepared = prepare_system_event(
            event_id=snapshot.diagnostic_id,
            level=snapshot.level,
            source=snapshot.source,
            action=snapshot.action,
            actor_type=snapshot.actor_type,
            actor_id=snapshot.actor_id,
            target_type=snapshot.target_type,
            target_id=snapshot.target_id,
            message=snapshot.message,
            metadata=snapshot.metadata,
        )
        session = factory()
        write_prepared_system_events(session, [prepared])
        session.commit()
        snapshot.persisted = True
        return True
    except Exception as persistence_error:  # noqa: BLE001 - bounded degradation
        if session is not None:
            _safe_rollback(session)
        logger.warning(
            "exception_diagnostics.persist_failed diagnostic_id=%s event=%s "
            "error_type=%s",
            snapshot.diagnostic_id,
            snapshot.event,
            type(persistence_error).__name__,
        )
        return False
    finally:
        if session is not None:
            _safe_close(session)


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
    """Prepare and persist one exception, returning its stable diagnostic id."""

    snapshot = prepare_exception_diagnostic(
        logger,
        event,
        error,
        level=level,
        context=context,
        source=source,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
    )
    factory = session_factory or _session_factory
    if factory is not None:
        persist_exception_diagnostic(logger, snapshot, factory)
    return snapshot.diagnostic_id


def _should_skip_unhandled(error: object) -> bool:
    return isinstance(error, (KeyboardInterrupt, SystemExit, asyncio.CancelledError))


def install_exception_hooks() -> None:
    """Install process/thread fallbacks once.

    Recorded failures are printed only through the sanitized diagnostic log;
    the previous hooks are not delegated to for them because the default
    handlers would re-print the raw traceback and secrets.
    """

    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    previous_sys_hook = sys.excepthook

    def _sys_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        if _should_skip_unhandled(exc):
            previous_sys_hook(exc_type, exc, tb)
            return
        try:
            record_exception(
                logging.getLogger("ermao.unhandled"),
                "process.unhandled_exception",
                exc,
                context={"stage": "process"},
            )
        except Exception:  # noqa: BLE001, S110 - hooks must not mask failures
            pass

    sys.excepthook = _sys_hook

    previous_thread_hook = threading.excepthook

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None or _should_skip_unhandled(args.exc_value):
            previous_thread_hook(args)
            return
        try:
            thread_name = getattr(args.thread, "name", None)
            record_exception(
                logging.getLogger("ermao.unhandled"),
                "thread.unhandled_exception",
                args.exc_value,
                context={"stage": "thread", "path": thread_name},
            )
        except Exception:  # noqa: BLE001, S110 - hooks must not mask failures
            pass

    threading.excepthook = _thread_hook


def install_loop_exception_handler(loop: Any) -> None:
    """Record unobserved asyncio task/loop exceptions without re-printing raw."""

    if loop is None or not hasattr(loop, "set_exception_handler"):
        return
    previous = (
        loop.get_exception_handler()
        if hasattr(loop, "get_exception_handler")
        else None
    )

    def _handler(active_loop: Any, context: dict[str, Any]) -> None:
        error = context.get("exception")
        if error is not None and not _should_skip_unhandled(error):
            try:
                record_exception(
                    logging.getLogger("ermao.unhandled"),
                    "asyncio.unhandled_exception",
                    error,
                    context={"stage": "event_loop"},
                )
            except Exception:  # noqa: BLE001, S110 - hooks must not mask failures
                pass
            return
        if previous is not None:
            previous(active_loop, context)
        else:
            active_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


__all__ = [
    "DiagnosticSnapshot",
    "build_exception_metadata",
    "configure_exception_storage",
    "format_exception_diagnostics",
    "install_exception_hooks",
    "install_loop_exception_handler",
    "persist_exception_diagnostic",
    "prepare_exception_diagnostic",
    "record_exception",
    "reset_exception_storage",
    "sanitize_diagnostic_text",
]
