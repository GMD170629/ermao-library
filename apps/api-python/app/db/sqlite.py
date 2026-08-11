import logging
from pathlib import Path
from time import monotonic

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine

from app.db.maintenance import (
    acquire_database_writer_lease,
    release_database_maintenance_lock,
)

logger = logging.getLogger(__name__)


def create_sqlite_engine(
    database_path: Path,
    *,
    timeout_seconds: float = 10,
    transaction_time_budget_seconds: float | None = None,
    slow_write_threshold_seconds: float | None = 0.1,
) -> Engine:
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        connect_args={"timeout": timeout_seconds},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
            cursor.execute("PRAGMA synchronous = NORMAL")
        finally:
            cursor.close()
        if transaction_time_budget_seconds is not None:
            connection_record.info["transaction_deadline"] = None

            def interrupt_expired_transaction() -> int:
                deadline = connection_record.info.get("transaction_deadline")
                return int(deadline is not None and monotonic() >= deadline)

            dbapi_connection.set_progress_handler(
                interrupt_expired_transaction,
                1_000,
            )

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
        if transaction_time_budget_seconds is not None:
            connection.info["transaction_deadline"] = (
                started_at + transaction_time_budget_seconds
            )

    def finish_observed_transaction(connection, *, outcome: str) -> None:
        release_database_maintenance_lock(
            connection.info.pop("database_writer_lease", None)
        )
        started_at = connection.info.pop("transaction_write_started_at", None)
        connection.info["transaction_deadline"] = None
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
        connection_record.info["transaction_deadline"] = None

    event.listen(engine, "commit", observe_commit)
    event.listen(engine, "rollback", observe_rollback)
    event.listen(engine, "checkin", release_checked_in_writer_lease)

    return engine
