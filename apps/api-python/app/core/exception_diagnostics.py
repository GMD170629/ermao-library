"""Unified exception diagnostics recording for API, worker, and background tasks.

The entry point keeps the original exception (type, message, traceback, chain)
instead of the current call stack.  Preparing a diagnostic is separated from
persisting it: the sanitized snapshot and running log are produced before any
rollback or cleanup, while the independent ``SystemEvent`` transaction is
written later at a safe boundary.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import re
import subprocess
import sys
import threading
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from uuid import uuid4

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.core.database_errors import is_database_operation_timeout
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
    "plan_id": "planId",
    "upload_id": "uploadId",
    "node_id": "nodeId",
    "book_id": "bookId",
    "import_task_id": "importTaskId",
    "stage": "stage",
    "outcome": "outcome",
    "path": "path",
    "method": "method",
    "attempt": "attempt",
    "operation_id": "operationId",
    "target_ordinal": "targetOrdinal",
    "step": "step",
    "parent_diagnostic_id": "parentDiagnosticId",
    "code": "code",
    "protocol_status": "protocolStatus",
    "exit_code": "exitCode",
}

_LOG_EXTRA_KEYS = (
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
    "attempt",
    "operation_id",
    "target_ordinal",
    "step",
    "parent_diagnostic_id",
    "code",
    "protocol_status",
    "exit_code",
    "diagnostic_id",
)

_SQL_PARAMETERS_MARKER = "[parameters:"
_SQL_BACKGROUND = re.compile(r"\(Background on this error at: [^)]+\)")
_SENSITIVE_KEYS = (
    r"authorization|proxy-authorization|x-api-key|x-auth-token|private-token|"
    r"cookie|set-cookie|password|passwd|pwd|secret|token|api[_-]?key|"
    r"access[_-]?key|client[_-]?secret|refresh[_-]?token|credential|passphrase"
)
_SENSITIVE_VALUE = r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\r\n]+)"
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)([\"']?\b(?:"
    + _SENSITIVE_KEYS
    + r")\b[\"']?[ \t]*[:=][ \t]*)"
    + _SENSITIVE_VALUE
)
_BASIC = re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=._~-]+")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:token|key|secret|password|access_token|api_key)=)[^&\s]+"
)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

_session_factory: SessionFactory | None = None
_hooks_installed = False
_pending: ContextVar[list[DiagnosticSnapshot] | None] = ContextVar("diagnostic_pending", default=None)
_context: ContextVar[dict[str, Any] | None] = ContextVar("diagnostic_context", default=None)
_persisting: ContextVar[str | None] = ContextVar("diagnostic_persisting", default=None)


@contextmanager
def deferred_exception_persistence(
    *, context: dict[str, Any] | None = None,
) -> Iterator[list[DiagnosticSnapshot]]:
    """Capture now; the owning boundary flushes after releasing its transaction.

    Nested scopes share the same queue. Only the outer owner flushes it, outside
    this context, using persist_exception_diagnostic. This is also inherited by
    ASGI worker threads through their copied context.
    """
    existing = _pending.get()
    pending = existing if existing is not None else []
    token = _pending.set(pending)
    context_token = _context.set({**(_context.get() or {}), **(context or {})})
    try:
        yield pending
    finally:
        _context.reset(context_token)
        _pending.reset(token)



@contextmanager
def exception_diagnostic_boundary(
    logger: logging.Logger, event: str, *, context: dict[str, Any] | None = None,
    session_factory: SessionFactory | None = None,
) -> Iterator[None]:
    """Own a request/worker queue and flush after enclosed resources close."""
    pending: list[DiagnosticSnapshot] = []
    owns_queue = _pending.get() is None
    try:
        with deferred_exception_persistence(context=context) as pending:
            try:
                yield
            except Exception as error:
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


def reset_exception_storage(*, expected_factory: SessionFactory | None = None) -> None:
    """Release an app's storage without clearing a newer app's factory."""
    if expected_factory is None or _session_factory is expected_factory:
        configure_exception_storage(None)


def _redact_sql_block(text: str, marker: str) -> str:
    """Redact SQLAlchemy SQL/parameter blocks with bracket/quote awareness.

    Parameter values may contain ``]``, newlines, or nested lists/dicts, so a
    non-greedy regex would stop early and leave later parameters exposed.
    """

    result: list[str] = []
    index = 0
    length = len(text)
    while True:
        start = text.find(marker, index)
        if start == -1:
            result.append(text[index:])
            break
        result.append(text[index:start])
        depth = 0
        quote: str | None = None
        cursor = start
        while cursor < length:
            char = text[cursor]
            if quote is not None:
                if char == "\\":
                    # Backslash-escaped character inside a quoted value (for
                    # example repr of ``a\'b``); never treat it as the closing
                    # quote or as a bracket.
                    cursor += 2
                    continue
                if char == quote:
                    if cursor + 1 < length and text[cursor + 1] == quote:
                        cursor += 2
                        continue
                    quote = None
            elif char in ("'", '"'):
                quote = char
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    cursor += 1
                    break
            cursor += 1
        result.append(f"{marker} [redacted]]")
        index = cursor
    return "".join(result)


def sanitize_diagnostic_text(text: object) -> str:
    """Redact credentials, SQL statements and parameters from diagnostics."""

    value = _redact_sql_block(str(text), _SQL_PARAMETERS_MARKER)
    # SQL may contain inline literals rather than bound parameters. The driver
    # message, type and database codes carry the failure; statement text is not
    # safe even after its separate parameters block has been removed.
    value = _redact_sql_block(value, "[SQL:")
    value = _SQL_BACKGROUND.sub("", value)
    value = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}[redacted]", value
    )
    value = _BASIC.sub("Basic [redacted]", value)
    value = _BEARER.sub("Bearer [redacted]", value)
    value = _QUERY_SECRET.sub(r"\1[redacted]", value)
    value = _EMAIL.sub(lambda match: mask_email(match.group(0)), value)
    # Never retain URL userinfo or query strings containing resource contents.
    value = re.sub(r"(https?://)[^/\s@]+@", r"\1[redacted]@", value)
    value = re.sub(r"(?i)([?&](?:body|content|payload|query|sql)=)[^&\s]+", r"\1[redacted]", value)
    # Source locations are rendered separately from code objects. Absolute
    # paths in exception messages identify private filesystem resources.
    value = re.sub(r'''(["'])(?:[A-Za-z]:[\\/]|/)[^\r\n]*?\1''', "'[private-path]'", value)
    value = re.sub(r"(?<![\w:/])(?:[A-Za-z]:[\\/]|/)(?:[^\s\"'<>:;,()\[\]]+[\\/])+[^\s\"'<>:;,()\[\]]*", "[private-path]", value)
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


def _safe_message(
    error: BaseException, *, limit: int | None = MAX_DIAGNOSTIC_MESSAGE_CHARS,
    report_formatting_failure: bool = True,
) -> str:
    try:
        # SDK wrappers may repeat the validation exception's raw input_value
        # in their own message. Keep their type, but use the actual validation
        # details without rejected inputs for every wrapper in that chain.
        validation = None
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, (ValidationError, RequestValidationError)):
                validation = current
                break
            # An implicit context may be a separate rollback/cleanup failure;
            # do not replace its actual message with the earlier validation.
            current = current.__cause__
        if validation is not None:
            message = json.dumps([
                {"type": item.get("type"), "loc": item.get("loc"),
                 "message": sanitize_diagnostic_text(item.get("msg", ""))}
                for item in validation.errors()
            ], ensure_ascii=True)
        # Commands and arbitrary child output can contain unlabelled secrets.
        elif isinstance(error, subprocess.CalledProcessError):
            message = f"Process exited with status {error.returncode}"
            stderr_summary = _subprocess_stderr_summary(error)
            if stderr_summary:
                message += f": {stderr_summary}"
        elif isinstance(error, subprocess.TimeoutExpired):
            message = f"Process timed out after {error.timeout} seconds"
        else:
            raw_message = str(error)
            if isinstance(error, OSError):
                for filename in (error.filename, error.filename2):
                    if filename is not None:
                        path = os.fsdecode(filename)
                        raw_message = raw_message.replace(repr(path), "'[private-path]'").replace(path, "[private-path]")
            message = sanitize_diagnostic_text(raw_message)
    except Exception as formatting_error:  # noqa: BLE001 - diagnostic failure isolation
        # diagnostics-control-flow: The emergency serializer disables recursive reporting of its own formatting probe; its returned diagnostic still names the original and formatter types.
        if report_formatting_failure:
            emergency_diagnostic(
                "exception_diagnostics.message_format_failed", formatting_error,
                diagnostic_id=f"diag_{uuid4().hex}",
            )
        # The emergency serializer uses this same path with reporting disabled:
        # even a second broken __str__ cannot recursively invoke the logger.
        message = f"[message unavailable: {_qualified_type(formatting_error)} while formatting {_qualified_type(error)}]"
    return message if limit is None else _bound_text(message, limit)[0]


def _subprocess_stderr_summary(error: subprocess.CalledProcessError) -> str | None:
    """Keep child diagnostic lines, never its command, stdout or document data."""
    stderr = error.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    if not isinstance(stderr, str) or not stderr.strip():
        return None
    # Child output is not a typed error. Restrict it to recognizable diagnostic
    # lines; arbitrary output can be the contents of the document being parsed.
    arguments = error.cmd if isinstance(error.cmd, (list, tuple)) else ()
    command = arguments[0] if arguments else error.cmd
    known_diagnostics = isinstance(command, (str, os.PathLike)) and Path(command).name in {"mv", "cp", "rm", "ffprobe"}
    if known_diagnostics:
        for argument in arguments[1:]:
            if isinstance(argument, (str, os.PathLike)) and Path(argument).is_absolute():
                stderr = stderr.replace(os.fspath(argument), "[private-path]")
    lines = [line for line in stderr.splitlines() if known_diagnostics or re.search(
        r"(?i)(?:^(?:mv|cp|rm|install|uv|pip|unzip|tar):|\berror\b|\bfailed\b|"
        r"\bdenied\b|no space left|read.only file system|cross.device link|"
        r"no such file|cannot |unable to |not found|invalid )", line
    )]
    return _bound_text(sanitize_diagnostic_text("\n".join(lines[-3:])), 2_000)[0] if lines else None


def _source_location(error: BaseException) -> str | None:
    current = error.__traceback__
    if current is None:
        return None
    while current.tb_next is not None:
        current = current.tb_next
    code = current.tb_frame.f_code
    return f"{_source_file(code.co_filename)}:{current.tb_lineno} in {code.co_name}"


def _source_file(filename: str) -> str:
    parts = Path(filename).parts
    for anchor in ("app", "tests", "scripts", "site-packages"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor):])
    return Path(filename).name


def _exception_facts(error: BaseException, *, report_formatting_failure: bool = True) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "type": _qualified_type(error),
        "message": _safe_message(error, report_formatting_failure=report_formatting_failure),
        "location": _source_location(error),
    }
    for attribute, key in (
        ("errno", "errno"), ("sqlite_errorcode", "databaseCode"),
        ("sqlite_errorname", "databaseErrorName"), ("sqlstate", "databaseCode"),
        ("pgcode", "databaseCode"), ("status_code", "protocolStatus"),
        ("returncode", "exitCode"), ("winerror", "winerror"),
        ("smtp_code", "protocolStatus"), ("code", "code"),
        ("verify_code", "certificateVerifyCode"),
        ("verify_message", "certificateVerifyMessage"),
    ):
        value = getattr(error, attribute, None)
        if isinstance(value, (int, str)) and not isinstance(value, bool):
            facts[key] = sanitize_diagnostic_text(value) if isinstance(value, str) else value
    if isinstance(facts.get("errno"), int):
        facts["errorName"] = errno.errorcode.get(facts["errno"], "NOT_PROVIDED")
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
    if isinstance(error, StatementError) and error.statement is not None:
        facts["statementOmitted"] = True
    return facts


def _explicit_cause(error: BaseException) -> BaseException | None:
    if error.__cause__ is not None:
        return error.__cause__
    original = getattr(error, "orig", None)
    return original if isinstance(original, BaseException) else None


def _exception_chain(error: BaseException) -> list[tuple[BaseException, str, int | None]]:
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
        context = current.__context__
        # The stack visits explicit causes first. A distinct context remains a
        # separate history branch instead of silently replacing the root cause.
        if context is not None and context is not cause and context is not original:
            pending.append((context, "context", index))
        if isinstance(original, BaseException) and original is not cause:
            pending.append((original, "original", index))
        if cause is not None:
            pending.append((cause, "cause", index))
    return result


def format_exception_diagnostics(
    error: BaseException,
    *,
    max_traceback_chars: int = MAX_TRACEBACK_CHARS,
) -> dict[str, Any]:
    """Record observed facts; never infer a permission/network/input cause."""
    linked_errors = _exception_chain(error)
    entries = [
        {**_exception_facts(item), "relationship": relationship,
         "chainIndex": index, "parentIndex": parent_index}
        for index, (item, relationship, parent_index) in enumerate(linked_errors)
    ]
    by_identity = {id(item): entry for (item, _, _), entry in zip(linked_errors, entries, strict=True)}
    cause = _explicit_cause(error)
    root = error
    seen = {id(root)}
    while (next_cause := _explicit_cause(root)) is not None and id(next_cause) not in seen:
        seen.add(id(next_cause))
        root = next_cause
    root_entry = by_identity[id(root)]
    contexts = [entry for entry in entries if entry["relationship"] == "context"]
    chain_truncated = len(entries) > MAX_CHAIN_ITEMS
    # Dedicated cause fields retain the actual causal root even when temporal
    # contexts make it an interior entry of a long display chain.
    chain = entries[:MAX_CHAIN_ITEMS - 1] if chain_truncated else entries[:]
    if chain_truncated:
        chain.append(root_entry if root_entry not in chain else entries[-1])
    trace: list[str] = []
    for (item, relationship, parent_index), facts in reversed(list(zip(linked_errors, entries, strict=True))):
        if len(entries) > 1:
            trace.append(f"Exception {facts['chainIndex']} ({relationship}, parent={parent_index}):\n")
        if item.__traceback__ is not None:
            trace.append("Traceback (most recent call last):\n")
            for frame in traceback.extract_tb(item.__traceback__):
                # No source lines or locals: they can contain SQL/body literals.
                trace.append(f'  File "{_source_file(frame.filename)}", line {frame.lineno}, in {frame.name}\n')
        trace.append(f"{facts['type']}: {facts['message']}\n")
    # Traceback may be longer than the structured summary, retain both ends.
    # Keep full exception message here (bounded below), as before.
    if len(linked_errors) == 1 and not isinstance(error, (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValidationError, RequestValidationError)):
        full_message = _safe_message(error, limit=None, report_formatting_failure=False)
        trace[-1] = f"{entries[0]['type']}: {full_message}\n"
    traceback_text, truncated = _bound_text("".join(trace), max_traceback_chars)
    return {
        "exceptionType": entries[0]["type"], "message": entries[0]["message"],
        "traceback": traceback_text, "chain": chain,
        "location": entries[0]["location"],
        "directException": entries[0],
        "directCause": by_identity[id(cause)] if cause is not None else None,
        "rootCause": root_entry, "causeProvided": cause is not None,
        "causeStatus": "PROVIDED" if cause is not None else "NOT_PROVIDED",
        "contexts": contexts[:MAX_CHAIN_ITEMS], "contextProvided": bool(contexts),
        "contextsTruncated": len(contexts) > MAX_CHAIN_ITEMS,
        "chainTruncated": chain_truncated, "chainLength": len(entries),
        "truncated": truncated or chain_truncated,
        **({"reason": "time_budget_exceeded"} if is_database_operation_timeout(error) else {}),
    }


def emergency_diagnostic(
    event: str, error: BaseException, *, diagnostic_id: str,
    parent_diagnostic_id: str | None = None,
    _minimal: bool = False,
) -> None:
    """Last-resort sanitized stderr; never invokes logging or the database."""
    try:
        if _minimal:
            output = (
                f"{event} diagnostic_id={diagnostic_id} parent_diagnostic_id={parent_diagnostic_id} "
                f"exception_type={_qualified_type(error)} "
                f"message={_safe_message(error, report_formatting_failure=False)}\n"
            )
        else:
            payload = {
                "event": event, "diagnosticId": diagnostic_id,
                "parentDiagnosticId": parent_diagnostic_id,
                "chain": [
                    {**_exception_facts(item, report_formatting_failure=False),
                     "relationship": relationship, "chainIndex": index, "parentIndex": parent_index}
                    for index, (item, relationship, parent_index) in enumerate(_exception_chain(error))
                ],
            }
            if isinstance(error, BaseExceptionGroup):
                payload["members"] = [
                    [{**_exception_facts(item, report_formatting_failure=False),
                      "relationship": relationship, "chainIndex": index, "parentIndex": parent_index}
                     for index, (item, relationship, parent_index) in enumerate(_exception_chain(leaf))]
                    for leaf in _iter_leaves(error) if leaf is not error
                ]
            output = json.dumps(payload, ensure_ascii=True) + "\n"
    except Exception as formatter_error:  # noqa: BLE001 - diagnostic failure isolation
        emergency_diagnostic(event, error, diagnostic_id=diagnostic_id,
                             parent_diagnostic_id=parent_diagnostic_id, _minimal=True)
        emergency_diagnostic(
            "exception_diagnostics.emergency_format_failed", formatter_error,
            diagnostic_id=f"diag_{uuid4().hex}", parent_diagnostic_id=diagnostic_id, _minimal=True,
        )
        return
    try:
        sys.stderr.write(output)
        sys.stderr.flush()
    except Exception as stream_error:  # noqa: BLE001 - independent last output
        # The stream may be replaced/broken; fd 2 is an independent last exit.
        _write_fd_fallback(output, stream_error, diagnostic_id=diagnostic_id)


def _write_fd_fallback(output: str, error: BaseException, *, diagnostic_id: str) -> None:
    """Terminal diagnostic sink when the configured stderr object is broken."""
    output += (
        f"exception_diagnostics.stderr_failed diagnostic_id=diag_{uuid4().hex} "
        f"parent_diagnostic_id={diagnostic_id} "
        f"exception_type={_qualified_type(error)} "
        f"message={_safe_message(error, report_formatting_failure=False)}\n"
    )
    try:
        os.write(2, output.encode("utf-8", errors="replace"))
    except OSError:
        # diagnostics-control-flow: Both independent stderr exits are unavailable; return preserves the original business failure, proven by sink-failure injection.
        return


def _sanitized_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
    result: dict[str, Any] = {}
    for key, value in context.items():
        if value is None:
            continue
        if key == "path" and context.get("method") and isinstance(value, str):
            # The ASGI path is public routing context, not a filesystem path.
            result[key] = value.split("?", 1)[0][:MAX_DIAGNOSTIC_MESSAGE_CHARS]
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
    if diagnostics.get("reason") == "time_budget_exceeded":
        header += " reason=time_budget_exceeded"
    if context_line:
        header = f"{header} {context_line}"
    traceback_text = str(diagnostics.get("traceback") or "")
    location = diagnostics.get("location")
    body = traceback_text if traceback_text else str(diagnostics.get("message") or "")
    if location and str(location) not in body:
        body = f"{body}\nlocation={location}"
    if not location and diagnostics.get("observedAt"):
        body = f"{body}\nobserved_at={diagnostics['observedAt']}"
    return f"{header}\n{body}".rstrip()


def _attach_snapshot(error: BaseException, snapshot: DiagnosticSnapshot) -> None:
    try:
        setattr(error, _DIAGNOSTIC_ATTR, snapshot)
    except Exception:  # noqa: BLE001, S110 - some exceptions forbid attributes
        # diagnostics-control-flow: Exception snapshot attachment is an optional deduplication probe; immutable exceptions still produce the returned snapshot and log.
        pass


def _direct_snapshot(error: BaseException) -> DiagnosticSnapshot | None:
    snapshot = getattr(error, _DIAGNOSTIC_ATTR, None)
    return snapshot if isinstance(snapshot, DiagnosticSnapshot) else None


def _iter_leaves(error: BaseException):
    # A node that already carries a diagnostic is treated as a recorded leaf so
    # a nested group's aggregate is not expanded and re-recorded.
    if _direct_snapshot(error) is not None:
        yield error
        return
    if isinstance(error, BaseExceptionGroup):
        for child in error.exceptions:
            yield from _iter_leaves(child)
    else:
        yield error


def _build_snapshot(
    logger: logging.Logger,
    event: str,
    error: BaseException,
    diagnostics: dict[str, Any],
    *,
    diagnostic_id: str,
    level: str,
    context: dict[str, Any] | None,
    source: str,
    action: str | None,
    actor_type: str,
    actor_id: str | None,
    target_type: str | None,
    target_id: str | None,
) -> DiagnosticSnapshot:
    if error.__traceback__ is None and diagnostics.get("location") is None:
        # This is where an unraised rule failure was observed, not an invented
        # origin traceback. Skip shared response/recording wrappers.
        frame = sys._getframe(1)
        while frame is not None:
            filename = _source_file(frame.f_code.co_filename)
            if filename.startswith("app/") and filename not in {
                "app/core/exception_diagnostics.py", "app/schemas/responses.py",
            }:
                diagnostics.setdefault("observedAt", f"{filename}:{frame.f_lineno} in {frame.f_code.co_name}")
                break
            frame = frame.f_back
        del frame
    try:
        log_text = _format_log_text(event, diagnostic_id, diagnostics, context)
        logger.log(
            logging.WARNING if level == "warning" else logging.ERROR,
            log_text,
            extra=_log_extra(context, diagnostic_id),
        )
    except Exception as logging_error:  # noqa: BLE001 - independent stderr fallback
        emergency_diagnostic(event, error, diagnostic_id=diagnostic_id)
        emergency_diagnostic(
            "exception_diagnostics.log_failed", logging_error,
            diagnostic_id=f"diag_{uuid4().hex}", parent_diagnostic_id=diagnostic_id,
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
    _attach_snapshot(error, snapshot)
    _enqueue(snapshot)
    return snapshot


def _prepare_group_diagnostic(
    logger: logging.Logger,
    event: str,
    group: BaseExceptionGroup,
    *,
    level: str,
    context: dict[str, Any] | None,
    source: str,
    action: str | None,
    actor_type: str,
    actor_id: str | None,
    target_type: str | None,
    target_id: str | None,
) -> DiagnosticSnapshot:
    """Diagnose every independent leaf exactly once.

    Already recorded leaves are referenced by id; unrecorded leaves are
    aggregated into one group event so a single propagation still produces a
    single main event.
    """

    leaves = list(_iter_leaves(group))
    recorded = [
        snapshot
        for snapshot in (_direct_snapshot(leaf) for leaf in leaves)
        if snapshot is not None
    ]
    unrecorded = [leaf for leaf in leaves if _direct_snapshot(leaf) is None]
    if not unrecorded:
        reused = recorded[0]
        _attach_snapshot(group, reused)
        return reused

    diagnostic_id = f"diag_{uuid4().hex}"
    group_diagnostics = format_exception_diagnostics(group)
    member_diagnostics = [format_exception_diagnostics(leaf) for leaf in unrecorded]
    combined_traceback, truncated = _bound_text(
        "\n".join(str(item.get("traceback") or "") for item in [group_diagnostics, *member_diagnostics]),
        MAX_TRACEBACK_CHARS,
    )
    diagnostics: dict[str, Any] = {
        **group_diagnostics,
        "traceback": combined_traceback,
        "truncated": truncated
        or group_diagnostics["truncated"]
        or any(item.get("truncated") for item in member_diagnostics),
        "members": [
            {key: value for key, value in item.items() if key != "traceback"}
            for item in member_diagnostics
        ],
        "memberCount": len(leaves),
        "relatedIds": [snapshot.diagnostic_id for snapshot in recorded],
    }
    snapshot = _build_snapshot(
        logger,
        event,
        group,
        diagnostics,
        diagnostic_id=diagnostic_id,
        level=level,
        context=context,
        source=source,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
    )
    for leaf in unrecorded:
        _attach_snapshot(leaf, snapshot)
    return snapshot


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

    Calling this again for the same exception instance (or a group containing a
    recorded leaf) reuses the snapshot so a cross-layer propagation produces a
    single main event and diagnostic id.
    """

    context = {**(_context.get() or {}), **(context or {})}
    if _persisting.get() is not None:
        context.setdefault("parent_diagnostic_id", _persisting.get())
    existing = _direct_snapshot(error)
    # Explicit wrappers preserve the same incident. Implicit __context__ often
    # describes a *secondary* rollback failure and must not be deduplicated.
    if existing is None and not context.get("parent_diagnostic_id"):
        cause = error.__cause__
        seen = {id(error)}
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            existing = _direct_snapshot(cause)
            if existing is not None:
                break
            cause = cause.__cause__
    if existing is not None:
        changed_attempt = any(
            key in context and wire in existing.metadata and context[key] != existing.metadata[wire]
            for key, wire in (("operation_id", "operationId"), ("target_ordinal", "targetOrdinal"), ("attempt", "attempt"))
        )
        if not changed_attempt:
            for key, value in _context_metadata(context).items():
                existing.metadata.setdefault(key, value)
            _attach_snapshot(error, existing)
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
                context=context,
                source=source,
                action=action,
                actor_type=actor_type,
                actor_id=actor_id,
                target_type=target_type,
                target_id=target_id,
            )
        diagnostics = format_exception_diagnostics(error)
    except Exception as formatting_error:  # noqa: BLE001 - keep original + formatter fault
        emergency_diagnostic(event, error, diagnostic_id=diagnostic_id)
        emergency_diagnostic("exception_diagnostics.format_failed", formatting_error,
                             diagnostic_id=f"diag_{uuid4().hex}", parent_diagnostic_id=diagnostic_id)
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
        context=context,
        source=source,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
    )


def _storage_failure(event: str, error: BaseException, snapshot: DiagnosticSnapshot) -> None:
    emergency_diagnostic(event, error, diagnostic_id=f"diag_{uuid4().hex}",
                         parent_diagnostic_id=snapshot.diagnostic_id)


def persist_exception_diagnostic(
    logger: logging.Logger,
    snapshot: DiagnosticSnapshot,
    session_factory: SessionFactory | None = None,
    *, force: bool = False,
) -> bool:
    """Best-effort persist one snapshot; never raises into business flow."""

    if snapshot.persisted:
        return True
    if _persisting.get() is not None:
        # A logging database failure already has a running-log snapshot. Never
        # recursively use the same database to report its own write failure.
        return False
    if _pending.get() is not None and not force:
        _enqueue(snapshot)
        return False
    factory = session_factory or _session_factory
    if factory is None:
        return False

    session: Session | None = None
    token = _persisting.set(snapshot.diagnostic_id)
    try:
        # Lazy import also belongs to this boundary: unavailable dependencies
        # must not replace the operation failure whose event is being stored.
        from app.modules.system.infrastructure.events import (
            prepare_system_event,
            write_prepared_system_events,
        )

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
        info = getattr(session, "info", None)
        if isinstance(info, dict):
            info["diagnostics_storage"] = True
        write_prepared_system_events(session, [prepared])
        session.commit()
        snapshot.persisted = True
        return True
    except Exception as persistence_error:  # noqa: BLE001 - preserve storage failure before rollback
        _storage_failure("exception_diagnostics.persist_failed", persistence_error, snapshot)
        if session is not None:
            try:
                session.rollback()
            except Exception as rollback_error:  # noqa: BLE001 - diagnostic failure isolation
                _storage_failure("exception_diagnostics.rollback_failed", rollback_error, snapshot)
        return False
    finally:
        try:
            if session is not None:
                try:
                    session.close()
                except Exception as close_error:  # noqa: BLE001 - diagnostic failure isolation
                    _storage_failure("exception_diagnostics.close_failed", close_error, snapshot)
        finally:
            _persisting.reset(token)


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
        except Exception as hook_error:  # noqa: BLE001 - independent output
            emergency_diagnostic("exception_diagnostics.hook_failed", hook_error, diagnostic_id=f"diag_{uuid4().hex}")

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
        except Exception as hook_error:  # noqa: BLE001 - independent output
            emergency_diagnostic("exception_diagnostics.hook_failed", hook_error, diagnostic_id=f"diag_{uuid4().hex}")

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
        if error is not None and not _should_skip_unhandled(error):
            try:
                record_exception(
                    logging.getLogger("ermao.unhandled"),
                    "asyncio.unhandled_exception",
                    error,
                    context={"stage": "event_loop"},
                )
            except Exception as hook_error:  # noqa: BLE001 - independent output
                emergency_diagnostic("exception_diagnostics.hook_failed", hook_error, diagnostic_id=f"diag_{uuid4().hex}")
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
    "deferred_exception_persistence",
    "emergency_diagnostic",
    "exception_diagnostic_boundary",
    "format_exception_diagnostics",
    "install_exception_hooks",
    "install_loop_exception_handler",
    "persist_exception_diagnostic",
    "prepare_exception_diagnostic",
    "record_exception",
    "reset_exception_storage",
    "sanitize_diagnostic_text",
]
