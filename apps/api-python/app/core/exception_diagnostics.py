"""Unified exception diagnostics recording for API, worker, and background tasks.

The entry point keeps the original exception (type, message, traceback, chain)
instead of the current call stack.  Preparing a diagnostic is separated from
persisting it: the raw snapshot and running log are produced before any
rollback or cleanup, while a daily file record is
written later at a safe boundary, without a database transaction.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import subprocess
import sys
import threading
import traceback
from asyncio import CancelledError as AsyncCancelledError
from collections.abc import Callable, Iterator
from concurrent.futures import CancelledError as FutureCancelledError
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import FrameType
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from uuid import uuid4

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.core.database_errors import is_database_operation_timeout

SessionFactory = Callable[[], "Session"]

_DIAGNOSTIC_ATTR = "_ermao_diagnostic_snapshot"

_session_factory: SessionFactory | None = None
_hooks_installed = False
_pending: ContextVar[list[DiagnosticSnapshot] | None] = ContextVar(
    "diagnostic_pending", default=None
)
_persisting: ContextVar[str | None] = ContextVar("diagnostic_persisting", default=None)


@contextmanager
def deferred_exception_persistence() -> Iterator[list[DiagnosticSnapshot]]:
    """Capture now; the owning boundary flushes after releasing its transaction.

    Nested scopes share the same queue. Only the outer owner flushes it, outside
    this context, using persist_exception_diagnostic. This is also inherited by
    ASGI worker threads through their copied context.
    """
    existing = _pending.get()
    pending = existing if existing is not None else []
    token = _pending.set(pending)
    try:
        yield pending
    finally:
        _pending.reset(token)


@contextmanager
def exception_diagnostic_boundary(
    logger: logging.Logger,
    event: str,
    *,
    session_factory: SessionFactory | None = None,
) -> Iterator[None]:
    """Own a request/worker queue and flush after enclosed resources close."""
    pending: list[DiagnosticSnapshot] = []
    owns_queue = _pending.get() is None
    try:
        with deferred_exception_persistence() as pending:
            try:
                yield
            except BaseException as error:
                prepare_exception_diagnostic(logger, event, error)
                raise
    finally:
        if owns_queue:
            for snapshot in pending:
                persist_exception_diagnostic(logger, snapshot, session_factory)


def _enqueue(snapshot: DiagnosticSnapshot) -> None:
    pending = _pending.get()
    if pending is not None and not any(item is snapshot for item in pending):
        pending.append(snapshot)


@dataclass
class DiagnosticSnapshot:
    """Raw, prepared diagnostic ready for logging and persistence."""

    diagnostic_id: str
    event: str
    level: str
    message: str
    metadata: dict[str, Any]
    source: str
    action: str
    actor_type: str
    actor_id: str | None
    persisted: bool = False


def configure_exception_storage(factory: SessionFactory | None) -> None:
    """Set the process-wide session factory used by best-effort persistence."""

    global _session_factory
    _session_factory = factory


def reset_exception_storage(*, expected_factory: SessionFactory | None = None) -> None:
    """Release an app's storage without clearing a newer app's factory."""
    if expected_factory is None or _session_factory is expected_factory:
        configure_exception_storage(None)


def diagnostic_text(text: object) -> str:
    """Render diagnostic text without redaction or alteration."""
    return str(text)


def _qualified_type(error: BaseException) -> str:
    error_type = type(error)
    module = getattr(error_type, "__module__", "") or ""
    name = getattr(error_type, "__qualname__", None) or error_type.__name__
    return f"{module}.{name}" if module and module != "builtins" else name


def exception_message(error: BaseException) -> str:
    """Return original exception types/messages, including causes and group members."""
    messages: list[str] = []
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        messages.append(
            "".join(traceback.format_exception_only(current)).removesuffix("\n")
        )
        cause = current.__cause__ or (
            current.__context__ if not current.__suppress_context__ else None
        )
        if cause is not None:
            pending.append(cause)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions))
    return "\n".join(messages)


def _safe_message(
    error: BaseException, *, report_formatting_failure: bool = True
) -> str:
    try:
        return str(error)
    except Exception as formatting_error:  # noqa: BLE001 - the logging formatter must preserve the original failure
        if report_formatting_failure:
            emergency_diagnostic(
                "exception_diagnostics.message_format_failed",
                formatting_error,
            )
        else:
            _write_fd_fallback("", formatting_error)
        return f"[message unavailable: {_qualified_type(formatting_error)} while formatting {_qualified_type(error)}]"


def _subprocess_stderr_summary(error: subprocess.CalledProcessError) -> str | None:
    value = error.stderr
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="backslashreplace")
    return value if isinstance(value, str) else None


def _source_location(error: BaseException) -> str | None:
    current = error.__traceback__
    if current is None:
        return None
    while current.tb_next is not None:
        current = current.tb_next
    code = current.tb_frame.f_code
    return f"{_source_file(code.co_filename)}:{current.tb_lineno} in {code.co_name}"


def _source_file(filename: str) -> str:
    return filename


def _exception_facts(
    error: BaseException, *, report_formatting_failure: bool = True
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "type": _qualified_type(error),
        "message": _safe_message(
            error, report_formatting_failure=report_formatting_failure
        ),
        "location": _source_location(error),
    }
    for attribute, key in (
        ("errno", "errno"),
        ("sqlite_errorcode", "databaseCode"),
        ("sqlite_errorname", "databaseErrorName"),
        ("sqlstate", "databaseCode"),
        ("pgcode", "databaseCode"),
        ("status_code", "protocolStatus"),
        ("returncode", "exitCode"),
        ("winerror", "winerror"),
        ("smtp_code", "protocolStatus"),
        ("code", "code"),
        ("verify_code", "certificateVerifyCode"),
        ("verify_message", "certificateVerifyMessage"),
    ):
        value = getattr(error, attribute, None)
        if isinstance(value, (int, str)) and not isinstance(value, bool):
            facts[key] = diagnostic_text(value) if isinstance(value, str) else value
    if isinstance(facts.get("errno"), int):
        facts["errorName"] = errno.errorcode.get(facts["errno"], "NOT_PROVIDED")
    notes = getattr(error, "__notes__", None)
    if notes:
        facts["notes"] = [diagnostic_text(note) for note in notes]
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        facts["protocolStatus"] = status
    if isinstance(error, HTTPError):
        facts["protocolStatus"] = error.code
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
        summary = _subprocess_stderr_summary(error)
        if summary:
            facts["stderrSummary"] = summary
        else:
            facts["stderrStatus"] = "OMITTED_UNSTRUCTURED_OUTPUT"
    if isinstance(error, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
        for attribute in ("cmd", "stdout", "stderr", "timeout"):
            value = getattr(error, attribute, None)
            if value is not None:
                facts[attribute] = (
                    value.decode("utf-8", errors="backslashreplace")
                    if isinstance(value, bytes)
                    else value
                )
    if (
        hasattr(error, "statement")
        and hasattr(error, "params")
        and hasattr(error, "orig")
    ):
        # Keep these separately: SQLAlchemy may truncate parameters in str(error)
        # or suppress them with hide_parameters. The admin export needs originals.
        facts["statement"] = error.statement
        facts["parameters"] = json.loads(
            json.dumps(error.params, ensure_ascii=False, default=str)
        )
        facts["isMulti"] = getattr(error, "ismulti", None)
    database_trace = getattr(error, "database_trace", None)
    if isinstance(database_trace, dict):
        facts["databaseTrace"] = database_trace
    return facts


def _explicit_cause(error: BaseException) -> BaseException | None:
    if error.__cause__ is not None:
        return error.__cause__
    original = getattr(error, "orig", None)
    if isinstance(original, BaseException):
        return original
    # urllib's URLError stores DNS/TLS/socket failures in reason, without
    # necessarily setting __cause__ or __context__.
    reason = getattr(error, "reason", None)
    return reason if isinstance(reason, BaseException) else None


def _exception_chain(
    error: BaseException,
) -> list[tuple[BaseException, str, int | None]]:
    """Keep causal and temporal links distinct, including separate contexts.

    Each relationship points to its parent entry. A context says only that the
    exception was raised while handling another; it does not establish cause.
    """
    result: list[tuple[BaseException, str, int | None]] = []
    seen: set[int] = set()
    pending: list[tuple[BaseException, str, int | None]] = [(error, "exception", None)]
    while pending:
        current, relationship, parent_index = pending.pop()
        if id(current) in seen:
            continue
        index = len(result)
        result.append((current, relationship, parent_index))
        seen.add(id(current))
        cause = current.__cause__
        original = getattr(current, "orig", None)
        reason = getattr(current, "reason", None)
        context = current.__context__
        if isinstance(current, BaseExceptionGroup):
            for member in reversed(current.exceptions):
                pending.append((member, "group_member", index))
        # The stack visits explicit causes first. A distinct context remains a
        # separate history branch instead of silently replacing the root cause.
        if context is not None and context is not cause and context is not original:
            pending.append((context, "context", index))
        if isinstance(original, BaseException) and original is not cause:
            pending.append((original, "original", index))
        if (
            isinstance(reason, BaseException)
            and reason is not cause
            and reason is not original
        ):
            pending.append((reason, "reason", index))
        if cause is not None:
            pending.append((cause, "cause", index))
    return result


def format_exception_diagnostics(
    error: BaseException,
) -> dict[str, Any]:
    """Record observed facts; never infer a permission/network/input cause."""
    linked_errors = _exception_chain(error)
    entries = [
        {
            **_exception_facts(item),
            "relationship": relationship,
            "chainIndex": index,
            "parentIndex": parent_index,
        }
        for index, (item, relationship, parent_index) in enumerate(linked_errors)
    ]
    by_identity = {
        id(item): entry
        for (item, _, _), entry in zip(linked_errors, entries, strict=True)
    }
    cause = _explicit_cause(error)
    root = error
    seen = {id(root)}
    while (next_cause := _explicit_cause(root)) is not None and id(
        next_cause
    ) not in seen:
        seen.add(id(next_cause))
        root = next_cause
    root_entry = by_identity[id(root)]
    contexts = [entry for entry in entries if entry["relationship"] == "context"]
    chain_truncated = False
    # Dedicated cause fields retain the actual causal root even when temporal
    # contexts make it an interior entry of a long display chain.
    chain = entries[:]
    trace: list[str] = []
    for (item, relationship, parent_index), facts in reversed(
        list(zip(linked_errors, entries, strict=True))
    ):
        if len(entries) > 1:
            trace.append(
                f"Exception {facts['chainIndex']} ({relationship}, parent={parent_index}):\n"
            )
        if item.__traceback__ is not None:
            trace.append("Traceback (most recent call last):\n")
            for frame in traceback.extract_tb(item.__traceback__):
                trace.append(
                    f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
                )
                if frame.line:
                    trace.append(f"    {frame.line}\n")
        trace.append(f"{facts['type']}: {facts['message']}\n")
        for note in facts.get("notes", []):
            trace.append(f"{note}\n")
        if "statement" in facts:
            trace.append(f"SQL: {facts['statement']}\n")
            trace.append(
                "Parameters: "
                + json.dumps(facts["parameters"], ensure_ascii=False, default=str)
                + "\n"
            )
        for stream in ("stdout", "stderr"):
            if stream in facts:
                trace.append(f"{stream}:\n{facts[stream]}\n")
    traceback_text = "".join(trace)
    truncated = False
    return {
        "exceptionType": entries[0]["type"],
        "message": entries[0]["message"],
        "traceback": traceback_text,
        "chain": chain,
        "location": entries[0]["location"],
        "directException": entries[0],
        "directCause": by_identity[id(cause)] if cause is not None else None,
        "rootCause": root_entry,
        "causeProvided": cause is not None,
        "causeStatus": "PROVIDED" if cause is not None else "NOT_PROVIDED",
        "contexts": contexts,
        "contextProvided": bool(contexts),
        "contextsTruncated": False,
        "chainTruncated": chain_truncated,
        "chainLength": len(entries),
        "truncated": truncated or chain_truncated,
        "databaseOperations": [entry for entry in entries if "statement" in entry],
        "databaseTrace": next(
            (entry["databaseTrace"] for entry in entries if "databaseTrace" in entry),
            None,
        ),
        **(
            {"reason": "time_budget_exceeded"}
            if is_database_operation_timeout(error)
            else {}
        ),
    }


def emergency_diagnostic(event: str, error: BaseException) -> None:
    """Independent raw stderr exit; never re-enter logging or database storage."""
    lines: list[str] = []
    seen: set[int] = set()
    pending = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        lines.append("Traceback (most recent call last):\n")
        tb = current.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            lines.append(
                f'  File "{code.co_filename}", line {tb.tb_lineno}, in {code.co_name}\n'
            )
            tb = tb.tb_next
        lines.append(
            f"{_qualified_type(current)}: {_safe_message(current, report_formatting_failure=False)}\n"
        )
        for attribute in (
            "statement", "params", "cmd", "stdout", "stderr", "__notes__",
            "errno", "winerror", "filename", "filename2", "sqlite_errorcode",
            "sqlite_errorname", "returncode", "status", "status_code", "code",
        ):
            try:
                value = getattr(current, attribute, None)
                if value is not None:
                    lines.append(f"{attribute}: {value!r}\n")
            except Exception as formatting_error:  # noqa: BLE001 - preserve the original in the emergency outlet
                # Remain inside the emergency output; no recursive logging sink.
                _write_fd_fallback("", formatting_error)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions))
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
        for attribute in ("orig", "reason"):
            try:
                linked = getattr(current, attribute, None)
                if isinstance(linked, BaseException):
                    pending.append(linked)
            except Exception as formatting_error:  # noqa: BLE001 - preserve the original in the emergency outlet
                _write_fd_fallback("", formatting_error)
    output = "".join(lines)
    try:
        sys.stderr.write(output)
        sys.stderr.flush()
    except Exception as stream_error:  # noqa: BLE001 - independent physical output fallback
        _write_fd_fallback(output, stream_error)


def _write_fd_fallback(output: str, error: BaseException) -> None:
    output += "".join(
        traceback.TracebackException.from_exception(
            error, max_group_width=sys.maxsize, max_group_depth=sys.maxsize
        ).format()
    )
    try:
        os.write(2, output.encode("utf-8", errors="backslashreplace"))
    except OSError:
        # Both physical stderr exits are unavailable; preserve the business result.
        return


def _format_log_text(diagnostics: dict[str, Any]) -> str:
    return str(diagnostics.get("traceback") or diagnostics.get("message") or "")


def _attach_snapshot(error: BaseException, snapshot: DiagnosticSnapshot) -> None:
    try:
        setattr(error, _DIAGNOSTIC_ATTR, snapshot)
    except Exception as attachment_error:  # noqa: BLE001 - some exceptions forbid attributes
        emergency_diagnostic("exception_diagnostics.attach_failed", attachment_error)


def _direct_snapshot(error: BaseException) -> DiagnosticSnapshot | None:
    snapshot = getattr(error, _DIAGNOSTIC_ATTR, None)
    return snapshot if isinstance(snapshot, DiagnosticSnapshot) else None


def _iter_leaves(error: BaseException):
    pending = [error]
    while pending:
        current = pending.pop()
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions))
        else:
            yield current


def _build_snapshot(
    logger: logging.Logger,
    event: str,
    error: BaseException,
    diagnostics: dict[str, Any],
    *,
    diagnostic_id: str,
    level: str,
    source: str,
    action: str | None,
    actor_type: str,
    actor_id: str | None,
    defer_persistence: bool,
) -> DiagnosticSnapshot:
    if error.__traceback__ is None and diagnostics.get("location") is None:
        # This is where an unraised rule failure was observed, not an invented
        # origin traceback. Skip shared response/recording wrappers.
        frame: FrameType | None = sys._getframe(1)
        while frame is not None:
            filename = _source_file(frame.f_code.co_filename)
            module = frame.f_globals.get("__name__", "")
            if module.startswith("app.") and module not in {
                "app.core.exception_diagnostics",
                "app.schemas.responses",
            }:
                diagnostics.setdefault(
                    "observedAt",
                    f"{filename}:{frame.f_lineno} in {frame.f_code.co_name}",
                )
                break
            frame = frame.f_back
        del frame
    try:
        log_text = _format_log_text(diagnostics)
        logger.log(
            {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}.get(level, logging.ERROR),
            log_text,
            extra={"database_operations": diagnostics.get("databaseOperations", []), "unified_diagnostic": True},
        )
    except Exception as logging_error:  # noqa: BLE001 - independent stderr fallback
        emergency_diagnostic(event, error)
        emergency_diagnostic(
            "exception_diagnostics.log_failed",
            logging_error,
        )
    metadata = {
        "diagnostics": diagnostics,
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
    )
    _attach_snapshot(error, snapshot)
    if defer_persistence:
        _enqueue(snapshot)
    return snapshot


def _prepare_group_diagnostic(
    logger: logging.Logger,
    event: str,
    group: BaseExceptionGroup,
    *,
    level: str,
    source: str,
    action: str | None,
    actor_type: str,
    actor_id: str | None,
    defer_persistence: bool,
) -> DiagnosticSnapshot:
    diagnostics = format_exception_diagnostics(group)
    leaves = list(_iter_leaves(group))
    members = [format_exception_diagnostics(leaf) for leaf in leaves]
    diagnostics["members"] = members
    diagnostics["memberCount"] = len(leaves)
    snapshot = _build_snapshot(
        logger,
        event,
        group,
        diagnostics,
        diagnostic_id=f"diag_{uuid4().hex}",
        level=level,
        source=source,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        defer_persistence=defer_persistence,
    )
    for leaf in leaves:
        if _direct_snapshot(leaf) is None:
            _attach_snapshot(leaf, snapshot)
    return snapshot


def prepare_exception_diagnostic(
    logger: logging.Logger,
    event: str,
    error: BaseException,
    *,
    level: str = "error",
    source: str = "system",
    action: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    defer_persistence: bool = True,
) -> DiagnosticSnapshot:
    """Emit a raw running log and return a reusable diagnostic snapshot.

    Calling this again for the same exception instance (or a group containing a
    recorded leaf) reuses the snapshot so a cross-layer propagation produces a
    single main event and diagnostic id.
    """

    existing = _direct_snapshot(error)
    if existing is not None:
        if existing.event == "exception.caught" and event != "exception.caught":
            existing.event = event
            existing.action = action or event
            existing.source = source
            existing.level = level
        if defer_persistence:
            _enqueue(existing)
        return existing
    diagnostic_id = f"diag_{uuid4().hex}"
    try:
        if isinstance(error, BaseExceptionGroup):
            return _prepare_group_diagnostic(
                logger,
                event,
                error,
                level=level,
                source=source,
                action=action,
                actor_type=actor_type,
                actor_id=actor_id,
                defer_persistence=defer_persistence,
            )
        diagnostics = format_exception_diagnostics(error)
    except Exception as formatting_error:  # noqa: BLE001 - keep original + formatter fault
        emergency_diagnostic(event, error)
        emergency_diagnostic(
            "exception_diagnostics.format_failed",
            formatting_error,
        )
        diagnostics = {
            "exceptionType": _qualified_type(error),
            "message": _safe_message(error),
            "formattingErrorType": _qualified_type(formatting_error),
            "formattingErrorMessage": _safe_message(formatting_error),
            "traceback": "",
            "chain": [],
            "location": None,
            "truncated": False,
        }
    return _build_snapshot(
        logger,
        event,
        error,
        diagnostics,
        diagnostic_id=diagnostic_id,
        level=level,
        source=source,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        defer_persistence=defer_persistence,
    )


def _storage_failure(
    event: str, error: BaseException, snapshot: DiagnosticSnapshot
) -> None:
    emergency_diagnostic(
        event,
        error,
    )


def persist_exception_diagnostic(
    logger: logging.Logger,
    snapshot: DiagnosticSnapshot,
    session_factory: SessionFactory | None = None,
    *,
    force: bool = False,
) -> bool:
    """Best-effort persist one snapshot; never raises into business flow."""

    if snapshot.persisted:
        return True
    if _persisting.get() is not None:
        # Never recursively use a physical log outlet to report its own failure.
        return False
    if _pending.get() is not None and not force:
        _enqueue(snapshot)
        return False
    token = _persisting.set(snapshot.diagnostic_id)
    try:
        from app.modules.system.infrastructure.events import (
            event_record,
            prepare_system_event,
        )
        from app.modules.system.infrastructure.log_files import append_log_event

        prepared = prepare_system_event(
            event_id=snapshot.diagnostic_id, level=snapshot.level,
            source=snapshot.source, action=snapshot.action,
            actor_type=snapshot.actor_type, actor_id=snapshot.actor_id,
            message=snapshot.message, metadata=snapshot.metadata,
        )
        snapshot.persisted = append_log_event(event_record(prepared))
        return snapshot.persisted
    except Exception as persistence_error:  # noqa: BLE001 - preserve the original failure
        _storage_failure("exception_diagnostics.persist_failed", persistence_error, snapshot)
        return False
    finally:
        _persisting.reset(token)


def record_exception(
    logger: logging.Logger,
    event: str,
    error: BaseException,
    *,
    level: str = "error",
    source: str = "system",
    action: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    session_factory: SessionFactory | None = None,
) -> str:
    """Prepare and persist one exception, returning its stable diagnostic id."""

    snapshot = prepare_exception_diagnostic(
        logger,
        event,
        error,
        level=level,
        source=source,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    persist_exception_diagnostic(logger, snapshot, session_factory)
    return snapshot.diagnostic_id


def capture_exception(error: BaseException, *, level: str | None = None, persist: bool = True) -> None:
    """Observe a local catch without changing its return, raise or cleanup behavior.

    Capture every path; configured severity decides whether to save the record.
    Existing boundaries defer writes until cleanup completes. No diagnostic
    creates a database session or changes the business transaction.
    """
    try:
        if _persisting.get() is not None:
            emergency_diagnostic("exception.log_outlet_failure", error)
            return
        logger = logging.getLogger("ermao.exceptions")
        observed_level = level or (
            "debug" if isinstance(error, (BlockingIOError, AsyncCancelledError, FutureCancelledError, StopIteration, StopAsyncIteration)) else "error"
        )
        snapshot = prepare_exception_diagnostic(logger, "exception.caught", error, level=observed_level)
        if persist:
            persist_exception_diagnostic(logger, snapshot)
    except BaseException as recording_error:  # noqa: BLE001 - diagnostic failure must not replace the observed exception
        emergency_diagnostic("exception.original", error)
        emergency_diagnostic("exception.recording_failed", recording_error)


def install_exception_hooks() -> None:
    """Install process/thread fallbacks once.

    Recorded failures use the unified raw diagnostic output once.
    """

    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    def _sys_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        try:
            record_exception(
                logging.getLogger("ermao.unhandled"),
                "process.unhandled_exception",
                exc,
            )
        except Exception as hook_error:  # noqa: BLE001 - independent output
            emergency_diagnostic("exception_diagnostics.hook_failed", hook_error)

    sys.excepthook = _sys_hook

    previous_thread_hook = threading.excepthook

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            previous_thread_hook(args)
            return
        try:
            record_exception(
                logging.getLogger("ermao.unhandled"),
                "thread.unhandled_exception",
                args.exc_value,
            )
        except Exception as hook_error:  # noqa: BLE001 - independent output
            emergency_diagnostic("exception_diagnostics.hook_failed", hook_error)

    threading.excepthook = _thread_hook


def install_loop_exception_handler(loop: Any) -> None:
    """Record unobserved asyncio task/loop exceptions without re-printing raw."""

    if loop is None or not hasattr(loop, "set_exception_handler"):
        return
    previous = (
        loop.get_exception_handler() if hasattr(loop, "get_exception_handler") else None
    )

    def _handler(active_loop: Any, context: dict[str, Any]) -> None:
        error = context.get("exception")
        if error is not None:
            try:
                record_exception(
                    logging.getLogger("ermao.unhandled"),
                    "asyncio.unhandled_exception",
                    error,
                )
            except Exception as hook_error:  # noqa: BLE001 - independent output
                emergency_diagnostic("exception_diagnostics.hook_failed", hook_error)
            return
        if previous is not None:
            previous(active_loop, context)
        else:
            active_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


__all__ = [
    "DiagnosticSnapshot",
    "capture_exception",
    "configure_exception_storage",
    "deferred_exception_persistence",
    "diagnostic_text",
    "emergency_diagnostic",
    "exception_diagnostic_boundary",
    "exception_message",
    "format_exception_diagnostics",
    "install_exception_hooks",
    "install_loop_exception_handler",
    "persist_exception_diagnostic",
    "prepare_exception_diagnostic",
    "record_exception",
    "reset_exception_storage",
]
