import logging
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from time import monotonic
from typing import Protocol, Self, TypeVar, cast, overload

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine

from app.core.natural_sort import natural_sort_key
from app.db.maintenance import (
    acquire_database_writer_lease,
    release_database_maintenance_lock,
)

logger = logging.getLogger(__name__)

SHORT_WRITE_LOCK_TIMEOUT_SECONDS = 0.5
SQLITE_STATEMENT_TIMEOUT_SECONDS = 2.0

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

    def _start_statement(self) -> None:
        self._budget_exhausted = False
        self._remaining_seconds = cast(
            _StatementBudgetConnection, self.connection
        ).statement_time_budget_seconds
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
        if self._remaining_seconds is None:
            return operation()
        self._started_at = monotonic()
        self._deadline = self._started_at + self._remaining_seconds
        self.connection.set_progress_handler(self._expired, 1_000)
        try:
            self._check_budget()
            result = operation()
            self._check_budget()
            return result
        except sqlite3.OperationalError as error:
            if self._budget_exhausted:
                error.time_budget_exceeded = True
            raise
        finally:
            self._remaining_seconds -= monotonic() - self._started_at
            self._deadline = None
            self.connection.set_progress_handler(None, 0)

    def execute(self, sql: str, parameters: _Parameters = (), /) -> Self:
        self._start_statement()
        return self._run(
            lambda: super(_StatementBudgetCursor, self).execute(sql, parameters)
        )

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[_Parameters], /
    ) -> Self:
        def budgeted_parameters() -> Iterable[_Parameters]:
            for parameters in seq_of_parameters:
                # DBAPI executemany executes a distinct statement for each set of
                # bindings; keep native batching/rowcount and reset only its timer.
                self._start_statement()
                yield parameters
                self._check_budget()

        self._start_statement()
        return self._run(
            lambda: super(_StatementBudgetCursor, self).executemany(
                sql, budgeted_parameters()
            )
        )

    def fetchone(self) -> object:
        return self._run(super().fetchone)

    def fetchmany(self, size: int | None = None) -> list[object]:
        return self._run(
            lambda: super(_StatementBudgetCursor, self).fetchmany(
                self.arraysize if size is None else size
            )
        )

    def fetchall(self) -> list[object]:
        return self._run(super().fetchall)

    def __next__(self) -> object:
        return self._run(super().__next__)


class _StatementBudgetConnection(sqlite3.Connection):
    statement_time_budget_seconds: float | None = None

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
    timeout_seconds: float = 10,
    statement_time_budget_seconds: float | None = None,
    slow_write_threshold_seconds: float | None = 0.1,
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

    @event.listens_for(engine, "before_cursor_execute")
    def observe_first_transaction_dml(
        connection,
        cursor,
        statement,
        parameters,
        execution_context,
        executemany,
    ) -> None:
        del cursor, statement, parameters, executemany
        if not (
            execution_context.isinsert
            or execution_context.isupdate
            or execution_context.isdelete
        ):
            return
        owns_restore_barrier = connection.info.get("database_restore_owner", False)
        if (
            connection.info.get("database_writer_lease") is None
            and not owns_restore_barrier
        ):
            connection.info["database_writer_lease"] = acquire_database_writer_lease(
                database_path,
                timeout_seconds=timeout_seconds,
            )
        if connection.info.get("transaction_write_started_at") is not None:
            return
        started_at = monotonic()
        connection.info["transaction_write_started_at"] = started_at

    def finish_observed_transaction(connection, *, outcome: str) -> None:
        release_database_maintenance_lock(
            connection.info.pop("database_writer_lease", None)
        )
        started_at = connection.info.pop("transaction_write_started_at", None)
        if started_at is None or slow_write_threshold_seconds is None:
            return
        duration_seconds = monotonic() - started_at
        if duration_seconds < slow_write_threshold_seconds:
            return
        logger.warning(
            "database_write_transaction_slow outcome=%s duration_ms=%.1f",
            outcome,
            duration_seconds * 1000,
        )

    def observe_commit(connection) -> None:
        finish_observed_transaction(connection, outcome="committed")

    def observe_rollback(connection) -> None:
        finish_observed_transaction(connection, outcome="rolled_back")

    def release_checked_in_writer_lease(dbapi_connection, connection_record) -> None:
        del dbapi_connection
        release_database_maintenance_lock(
            connection_record.info.pop("database_writer_lease", None)
        )
        connection_record.info.pop("transaction_write_started_at", None)

    event.listen(engine, "commit", observe_commit)
    event.listen(engine, "rollback", observe_rollback)
    event.listen(engine, "checkin", release_checked_in_writer_lease)

    return engine
