
import hashlib
import json
import logging
import re
import sqlite3
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, thread_time
from typing import Any, Protocol, Self, TypeVar, cast, overload

from app.core.exception_diagnostics import capture_exception

try:
    import resource
except ImportError as _caught_error:  # diagnostics-control-flow: Windows does not provide the optional resource module.
    capture_exception(_caught_error)
    resource = None

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine

from app.core.natural_sort import natural_sort_key
from app.db.maintenance import (
    acquire_database_writer_lease,
    release_database_maintenance_lock,
)

logger = logging.getLogger(__name__)

SQLITE_LOCK_WAIT_SECONDS = 30.0
SQLITE_STATEMENT_TIMEOUT_SECONDS = 30.0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _thread_usage() -> tuple[float, int | None, int | None, int | None, int | None]:
    cpu = thread_time()
    if resource is None or not hasattr(resource, "RUSAGE_THREAD"):
        return (cpu, None, None, None, None)
    usage = resource.getrusage(resource.RUSAGE_THREAD)
    return (cpu, usage.ru_inblock, usage.ru_oublock, usage.ru_nvcsw, usage.ru_nivcsw)


def _usage_delta(
    started: tuple[float, int | None, int | None, int | None, int | None],
) -> dict[str, float | int | None]:
    finished = _thread_usage()
    return {
        "thread_cpu_ms": round((finished[0] - started[0]) * 1000, 2),
        "block_reads": finished[1] - started[1] if finished[1] is not None and started[1] is not None else None,
        "block_writes": finished[2] - started[2] if finished[2] is not None and started[2] is not None else None,
        "voluntary_switches": finished[3] - started[3] if finished[3] is not None and started[3] is not None else None,
        "involuntary_switches": finished[4] - started[4] if finished[4] is not None and started[4] is not None else None,
    }


def _application_callsite() -> str | None:
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_code.co_filename.replace("\\", "/")
        marker = "/app/"
        if marker in name and not name.endswith("/app/db/sqlite.py"):
            return f"app/{name.split(marker, 1)[1]}:{frame.f_lineno} in {frame.f_code.co_name}"
        frame = frame.f_back
    return None


def _statement_kind(execution_context: Any, sql: str) -> str:
    if execution_context.isinsert:
        return "INSERT"
    if execution_context.isupdate:
        return "UPDATE"
    if execution_context.isdelete:
        return "DELETE"
    first_word = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    if first_word in {"INSERT", "UPDATE", "DELETE", "SELECT"}:
        return first_word
    return "OTHER"


def _statement_table(execution_context: Any) -> str | None:
    compiled = getattr(execution_context, "compiled", None)
    statement = getattr(compiled, "statement", None)
    table = getattr(statement, "table", None)
    name = getattr(table, "name", None)
    return name if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) else None


@dataclass(slots=True)
class _TransactionTrace:
    started_at: float
    started_utc: str
    usage_started: tuple[float, int | None, int | None, int | None, int | None]
    first_write_at: float | None = None
    statement_count: int = 0
    dbapi_ms: float = 0.0
    lease_wait_ms: float = 0.0
    slowest_statement_ms: float = 0.0
    statements: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class _StatementTrace:
    started_at: float
    started_utc: str
    usage_started: tuple[float, int | None, int | None, int | None, int | None]
    operation: str
    table: str | None
    sql_sha256: str
    callsite: str | None
    preparation_started_at: float | None
    dbapi_started_at: float | None = None
    lease_wait_ms: float = 0.0
    operation_record: dict[str, object] | None = None


def _log_timing(event_name: str, *, level: int = logging.INFO, **fields: object) -> None:
    logger.log(
        level, "%s %s", event_name,
        json.dumps(fields, ensure_ascii=False, default=str, separators=(",", ":")),
        # The exception entry includes failed-statement timing and its full
        # transaction trace. Do not append a second file record for that error.
        extra={"unified_diagnostic": event_name == "database_statement_failed"},
    )


def _attach_database_trace(error: BaseException, fields: dict[str, object]) -> None:
    try:
        error.database_trace = fields
    except (AttributeError, TypeError) as _caught_error:  # diagnostics-control-flow: Foreign DBAPI exceptions may reject diagnostic attributes.
        capture_exception(_caught_error)


def _finish_transaction(info: dict[str, Any], *, outcome: str, boundary_ms: float) -> None:
    trace = info.pop("database_transaction_trace", None)
    session_info = info.pop("database_diagnostic_session_info", None)
    release_database_maintenance_lock(info.pop("database_writer_lease", None))
    info.pop("database_statement_trace", None)
    info.pop("database_statement_preparation_started_at", None)
    info.pop("transaction_write_started_at", None)
    if not isinstance(trace, _TransactionTrace):
        return
    elapsed_ms = (monotonic() - trace.started_at) * 1000
    fields = {
        "outcome": outcome,
        "started_utc": trace.started_utc,
        "finished_utc": _utc_now(),
        "duration_ms": round(elapsed_ms, 2),
        "boundary_ms": round(boundary_ms, 2),
        "write_boundary_ms": round((monotonic() - trace.first_write_at) * 1000, 2) if trace.first_write_at is not None else None,
        "statement_count": trace.statement_count,
        "dbapi_ms": round(trace.dbapi_ms, 2),
        "lease_wait_ms": round(trace.lease_wait_ms, 2),
        "outside_dbapi_ms": round(max(0.0, elapsed_ms - trace.dbapi_ms - boundary_ms), 2),
        "slowest_statement_ms": round(trace.slowest_statement_ms, 2),
        **_usage_delta(trace.usage_started),
    }
    _log_timing("database_transaction_finished", **fields)
    threshold = info.get("database_slow_write_threshold_seconds")
    if trace.first_write_at is not None and threshold is not None and elapsed_ms > threshold * 1000:
        _log_timing("database_write_transaction_slow", level=logging.WARNING, **fields)
        if isinstance(session_info, dict) and not session_info.get("diagnostics_storage"):
            session_info.setdefault("database_slow_transactions", []).append(
                {**fields, "statements": trace.statements}
            )

_Result = TypeVar("_Result")
_Cursor = TypeVar("_Cursor", bound=sqlite3.Cursor)


class _PositionalParameters(Protocol):
    def __len__(self) -> int: ...

    def __getitem__(self, index: int, /) -> object: ...


_Parameters = _PositionalParameters | Mapping[str, object]


class _StatementBudgetCursor(sqlite3.Cursor):
    """Budget SQLite execution and fetching, excluding time between DBAPI calls."""

    _remaining_seconds: float | None = None
    _deadline: float | None = None
    _started_at: float = 0
    _budget_exhausted: bool = False
    _progress_calls: int = 0
    _last_progress_at: float | None = None
    _last_call_elapsed_seconds: float = 0.0
    _diagnostic_statement: dict[str, object] | None = None
    _diagnostic_transaction: _TransactionTrace | None = None
    _pre_execute_wait_seconds: float = 0.0

    def _start_statement(self) -> None:
        self._budget_exhausted = False
        self._progress_calls = 0
        self._last_progress_at = None
        self._remaining_seconds = cast(
            _StatementBudgetConnection, self.connection
        ).statement_time_budget_seconds
        if self._remaining_seconds is not None:
            self._remaining_seconds -= self._pre_execute_wait_seconds
        self._pre_execute_wait_seconds = 0.0
        self._started_at = monotonic()
        self._deadline = (
            self._started_at + self._remaining_seconds
            if self._remaining_seconds is not None
            else None
        )

    def _expired(self) -> int:
        expired = self._deadline is not None and monotonic() >= self._deadline
        self._budget_exhausted = self._budget_exhausted or expired
        return int(expired)

    def _on_progress(self) -> int:
        self._progress_calls += 1
        self._last_progress_at = monotonic()
        return self._expired()

    def _check_budget(self) -> None:
        if self._expired():
            # Short statements and blocking functions can complete before the next
            # SQLite progress callback. Still report failure to the owning UoW.
            error = sqlite3.OperationalError("interrupted")
            error.sqlite_errorcode = sqlite3.SQLITE_INTERRUPT
            error.sqlite_errorname = "SQLITE_INTERRUPT"
            error.time_budget_exceeded = True
            raise error

    def _run(self, operation: Callable[[], _Result]) -> _Result:
        call_started = monotonic()
        if self._remaining_seconds is None:
            try:
                return operation()
            finally:
                self._last_call_elapsed_seconds = monotonic() - call_started
        self._started_at = call_started
        self._deadline = call_started + self._remaining_seconds
        self.connection.set_progress_handler(self._on_progress, 1_000)
        try:
            self._check_budget()
            result = operation()
            self._check_budget()
            return result
        except sqlite3.OperationalError as error:
            capture_exception(error)
            if self._budget_exhausted:
                error.time_budget_exceeded = True
            raise
        finally:
            self._remaining_seconds -= monotonic() - self._started_at
            self._last_call_elapsed_seconds = monotonic() - call_started
            self._deadline = None
            self.connection.set_progress_handler(None, 0)

    def execute(self, sql: str, parameters: _Parameters = (), /) -> Self:
        self._diagnostic_statement = None
        self._diagnostic_transaction = None
        self._start_statement()
        return self._run(
            lambda: super(_StatementBudgetCursor, self).execute(sql, parameters)
        )

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[_Parameters], /
    ) -> Self:
        self._diagnostic_statement = None
        self._diagnostic_transaction = None
        def budgeted_parameters() -> Iterable[_Parameters]:
            for parameters in seq_of_parameters:
                # All bindings in one DBAPI call share one active SQL budget.
                self._check_budget()
                yield parameters
                self._check_budget()

        self._start_statement()
        return self._run(
            lambda: super(_StatementBudgetCursor, self).executemany(
                sql, budgeted_parameters()
            )
        )

    def fetchone(self) -> object:
        return self._run_fetch("fetchone", super().fetchone)

    def fetchmany(self, size: int | None = None) -> list[object]:
        return self._run_fetch("fetchmany",
            lambda: super(_StatementBudgetCursor, self).fetchmany(
                self.arraysize if size is None else size
            )
        )

    def fetchall(self) -> list[object]:
        return self._run_fetch("fetchall", super().fetchall)

    def __next__(self) -> object:
        return self._run_fetch("next", super().__next__)

    def _run_fetch(self, method: str, operation: Callable[[], _Result]) -> _Result:
        statement = self._diagnostic_statement
        started = monotonic()
        try:
            result = self._run(operation)
        except StopIteration as _caught_error:
            capture_exception(_caught_error, persist=False)
            raise
        except Exception as error:
            capture_exception(error)
            if statement is not None:
                fields = {
                    "phase": method,
                    "duration_ms": round((monotonic() - started) * 1000, 2),
                    "progress_calls": self._progress_calls,
                    "time_budget_exceeded": bool(getattr(error, "time_budget_exceeded", False)),
                    "error_type": type(error).__name__,
                    "transaction_statements": self._diagnostic_transaction.statements if self._diagnostic_transaction else [],
                }
                _attach_database_trace(error, fields)
                _log_timing("database_fetch_failed", level=logging.ERROR, **{key: value for key, value in fields.items() if key != "transaction_statements"})
            raise
        if statement is not None:
            _log_timing(
                "database_fetch_finished", phase=method,
                duration_ms=round((monotonic() - started) * 1000, 2),
                row_count=len(result) if isinstance(result, list) else int(result is not None),
                progress_calls=self._progress_calls,
            )
        return result


class _StatementBudgetConnection(sqlite3.Connection):
    statement_time_budget_seconds: float | None = None
    diagnostic_info: dict[str, Any] | None = None

    def commit(self) -> None:
        started = monotonic()
        try:
            super().commit()
        except Exception as error:
            capture_exception(error)
            trace = self.diagnostic_info.get("database_transaction_trace") if self.diagnostic_info else None
            if isinstance(trace, _TransactionTrace):
                _attach_database_trace(error, {
                    "phase": "commit",
                    "transaction_statements": trace.statements,
                })
            _log_timing("database_commit_failed", level=logging.ERROR,
                        duration_ms=round((monotonic() - started) * 1000, 2),
                        error_type=type(error).__name__, error_message=str(error),
                        sqlite_error_name=getattr(error, "sqlite_errorname", None))
            raise
        if self.diagnostic_info is not None:
            _finish_transaction(self.diagnostic_info, outcome="committed", boundary_ms=(monotonic() - started) * 1000)

    def rollback(self) -> None:
        started = monotonic()
        try:
            super().rollback()
        except Exception as error:
            capture_exception(error)
            trace = self.diagnostic_info.get("database_transaction_trace") if self.diagnostic_info else None
            if isinstance(trace, _TransactionTrace):
                _attach_database_trace(error, {
                    "phase": "rollback",
                    "transaction_statements": trace.statements,
                })
            _log_timing("database_rollback_failed", level=logging.ERROR,
                        duration_ms=round((monotonic() - started) * 1000, 2),
                        error_type=type(error).__name__, error_message=str(error),
                        sqlite_error_name=getattr(error, "sqlite_errorname", None))
            raise
        if self.diagnostic_info is not None:
            _finish_transaction(self.diagnostic_info, outcome="rolled_back", boundary_ms=(monotonic() - started) * 1000)

    @overload
    def cursor(self, factory: None = None) -> sqlite3.Cursor: ...

    @overload
    def cursor(self, factory: Callable[[sqlite3.Connection], _Cursor]) -> _Cursor: ...

    def cursor(
        self, factory: Callable[[sqlite3.Connection], sqlite3.Cursor] | None = None
    ) -> sqlite3.Cursor:
        return super().cursor(factory or _StatementBudgetCursor)


class SQLiteWalModeRequiredError(RuntimeError):
    """The persistent database could not enter the required WAL mode."""


def create_sqlite_engine(
    database_path: Path,
    *,
    timeout_seconds: float = SQLITE_LOCK_WAIT_SECONDS,
    statement_time_budget_seconds: float | None = SQLITE_STATEMENT_TIMEOUT_SECONDS,
    slow_write_threshold_seconds: float | None = 1.0,
) -> Engine:
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        connect_args={
            "timeout": timeout_seconds,
            "factory": _StatementBudgetConnection,
        },
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, connection_record) -> None:
        def natural_compare(left: str, right: str) -> int:
            left_key, right_key = natural_sort_key(left), natural_sort_key(right)
            return (left_key > right_key) - (left_key < right_key)

        dbapi_connection.create_collation("ERMAO_NATURAL", natural_compare)
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
            # SQLite exposes journal configuration only through PRAGMA at the
            # DBAPI connection boundary. WAL is persistent for the database,
            # but every process verifies it instead of silently falling back
            # to DELETE mode on an unsupported filesystem or read-only mount.
            journal_mode_row = cursor.execute("PRAGMA journal_mode = WAL").fetchone()
            journal_mode = (
                str(journal_mode_row[0]).casefold() if journal_mode_row else None
            )
            if journal_mode != "wal":
                raise SQLiteWalModeRequiredError(
                    "SQLite WAL mode is required; "
                    f"database reported {journal_mode or 'no journal mode'}"
                )
            cursor.execute("PRAGMA synchronous = NORMAL")
        finally:
            cursor.close()
        dbapi_connection.statement_time_budget_seconds = statement_time_budget_seconds
        connection_record.info["database_slow_write_threshold_seconds"] = slow_write_threshold_seconds

    @event.listens_for(engine, "before_execute")
    def observe_statement_preparation(
        connection, clauseelement, multiparams, params, execution_options
    ) -> None:
        del clauseelement, multiparams, params, execution_options
        connection.info["database_statement_preparation_started_at"] = monotonic()

    def complete_statement(
        connection, cursor, error: BaseException | None = None
    ) -> dict[str, object] | None:
        trace = connection.info.pop("database_statement_trace", None)
        if not isinstance(trace, _StatementTrace):
            return None
        transaction = connection.info.get("database_transaction_trace")
        dbapi_ms = (
            float(cursor._last_call_elapsed_seconds) * 1000
            if isinstance(cursor, _StatementBudgetCursor)
            else (monotonic() - trace.dbapi_started_at) * 1000 if trace.dbapi_started_at is not None else 0.0
        )
        total_ms = (monotonic() - trace.started_at) * 1000
        fields: dict[str, object] = {
            "outcome": "failed" if error is not None else "ok",
            "started_utc": trace.started_utc,
            "finished_utc": _utc_now(),
            "operation": trace.operation,
            "table": trace.table,
            "sql_sha256": trace.sql_sha256,
            "callsite": trace.callsite,
            "total_ms": round(total_ms, 2),
            "preparation_ms": round(max(0.0, trace.started_at - trace.preparation_started_at) * 1000, 2) if trace.preparation_started_at is not None else None,
            "pre_dbapi_ms": round(max(0.0, (trace.dbapi_started_at or trace.started_at) - trace.started_at) * 1000, 2),
            "lease_wait_ms": round(trace.lease_wait_ms, 2),
            "dbapi_ms": round(dbapi_ms, 2),
            "progress_calls": cursor._progress_calls if isinstance(cursor, _StatementBudgetCursor) else None,
            "last_progress_gap_ms": round((monotonic() - cursor._last_progress_at) * 1000, 2) if isinstance(cursor, _StatementBudgetCursor) and cursor._last_progress_at is not None else None,
            "rowcount": cursor.rowcount if cursor is not None else None,
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
            "sqlite_error_name": getattr(error, "sqlite_errorname", None),
            "time_budget_exceeded": bool(getattr(error, "time_budget_exceeded", False)),
            **_usage_delta(trace.usage_started),
        }
        if isinstance(transaction, _TransactionTrace):
            transaction.statement_count += 1
            transaction.dbapi_ms += dbapi_ms
            transaction.lease_wait_ms += trace.lease_wait_ms
            if transaction.statement_count == 1 or total_ms > transaction.slowest_statement_ms:
                transaction.slowest_statement_ms = total_ms
            if trace.operation_record is not None:
                trace.operation_record["timing"] = fields
        if isinstance(cursor, _StatementBudgetCursor) and trace.operation_record is not None:
            cursor._diagnostic_statement = fields
            cursor._diagnostic_transaction = transaction if isinstance(transaction, _TransactionTrace) else None
        _log_timing(
            "database_statement_finished" if error is None else "database_statement_failed",
            level=logging.ERROR if error is not None else logging.INFO,
            **fields,
        )
        if error is not None and isinstance(transaction, _TransactionTrace):
            return {**fields, "transaction_statements": transaction.statements}
        return fields

    @event.listens_for(engine, "before_cursor_execute")
    def observe_statement_start(
        connection, cursor, statement, parameters, execution_context, executemany
    ) -> None:
        del executemany
        info = connection.info
        dbapi_connection = connection.connection.driver_connection
        if isinstance(dbapi_connection, _StatementBudgetConnection):
            dbapi_connection.diagnostic_info = info
        transaction = info.get("database_transaction_trace")
        if not isinstance(transaction, _TransactionTrace):
            transaction = _TransactionTrace(
                started_at=monotonic(),
                started_utc=_utc_now(), usage_started=_thread_usage(),
            )
            info["database_transaction_trace"] = transaction
        started_at = monotonic()
        trace = _StatementTrace(
            started_at=started_at, started_utc=_utc_now(),
            usage_started=_thread_usage(), operation=_statement_kind(execution_context, statement),
            table=_statement_table(execution_context),
            sql_sha256=hashlib.sha256(statement.encode("utf-8")).hexdigest(),
            callsite=_application_callsite(),
            preparation_started_at=info.pop("database_statement_preparation_started_at", None),
        )
        trace.operation_record = {
            "started_utc": trace.started_utc,
            "operation": trace.operation,
            "table": trace.table,
            "callsite": trace.callsite,
            "statement": statement,
            "parameters": parameters,
        }
        transaction.statements.append(trace.operation_record)
        info["database_statement_trace"] = trace
        logger.info(
            "database_statement_started started_utc=%s operation=%s table=%s sql_sha256=%s callsite=%s",
            trace.started_utc, trace.operation,
            trace.table, trace.sql_sha256, trace.callsite,
            extra={"database_operations": [{"statement": statement, "parameters": parameters}]},
        )
        if trace.operation in {"INSERT", "UPDATE", "DELETE"}:
            if transaction.first_write_at is None:
                transaction.first_write_at = started_at
            if info.get("database_writer_lease") is None and not info.get("database_restore_owner", False):
                lease_started = monotonic()
                try:
                    info["database_writer_lease"] = acquire_database_writer_lease(
                        database_path, timeout_seconds=timeout_seconds,
                    )
                except Exception as error:
                    capture_exception(error)
                    trace.lease_wait_ms = (monotonic() - lease_started) * 1000
                    fields = complete_statement(connection, None, error)
                    if fields is not None:
                        _attach_database_trace(error, fields)
                    raise
                trace.lease_wait_ms = (monotonic() - lease_started) * 1000
        if isinstance(cursor, _StatementBudgetCursor):
            cursor._pre_execute_wait_seconds = trace.lease_wait_ms / 1000
        trace.dbapi_started_at = monotonic()

    @event.listens_for(engine, "after_cursor_execute")
    def observe_statement_finish(
        connection, cursor, statement, parameters, execution_context, executemany
    ) -> None:
        del statement, parameters, execution_context, executemany
        complete_statement(connection, cursor)

    @event.listens_for(engine, "handle_error")
    def observe_statement_error(exception_context) -> None:
        connection = exception_context.connection
        if connection is None:
            return
        cursor = getattr(exception_context.execution_context, "cursor", None)
        fields = complete_statement(connection, cursor, exception_context.original_exception)
        if fields is not None:
            for error in (exception_context.original_exception, exception_context.sqlalchemy_exception):
                if error is not None:
                    _attach_database_trace(error, fields)

    def release_checked_in_writer_lease(dbapi_connection, connection_record) -> None:
        if isinstance(dbapi_connection, _StatementBudgetConnection):
            dbapi_connection.diagnostic_info = None
        _finish_transaction(connection_record.info, outcome="checked_in", boundary_ms=0.0)

    event.listen(engine, "checkin", release_checked_in_writer_lease)

    return engine
