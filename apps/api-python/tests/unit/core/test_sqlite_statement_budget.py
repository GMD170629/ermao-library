from __future__ import annotations

import json
import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core import exception_diagnostics as diagnostics
from app.core.database_errors import is_database_operation_timeout
from app.core.exception_diagnostics import format_exception_diagnostics
from app.db.diagnostic_session import DiagnosticSession
from app.db.sqlite import (
    SQLITE_LOCK_WAIT_SECONDS,
    SQLITE_STATEMENT_TIMEOUT_SECONDS,
    create_sqlite_engine,
)
from app.models.settings import SystemEvent, SystemSetting


def test_statement_budget_and_lock_wait_share_thirty_second_cap() -> None:
    assert SQLITE_LOCK_WAIT_SECONDS == 30.0
    assert SQLITE_STATEMENT_TIMEOUT_SECONDS == 30.0


def test_external_sqlite_interruption_is_not_a_budget_timeout():
    original = sqlite3.OperationalError("interrupted")
    original.sqlite_errorcode = sqlite3.SQLITE_INTERRUPT
    assert not is_database_operation_timeout(original)
    assert not is_database_operation_timeout(OperationalError("query", {}, original))


def _budget_table(engine: sa.Engine) -> sa.Table:
    metadata = sa.MetaData()
    table = sa.Table(
        "BudgetProbe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )
    # The tiny budgets exercise statements below, not filesystem latency while
    # creating the fixture. CI disk stalls must not fail before the tested query.
    assert engine.url.database is not None
    setup_engine = create_sqlite_engine(
        Path(engine.url.database),
        statement_time_budget_seconds=None,
        slow_write_threshold_seconds=None,
    )
    try:
        metadata.create_all(setup_engine)
        with setup_engine.begin() as connection:
            connection.execute(
                sa.insert(table),
                [{"id": index, "value": index} for index in range(200)],
            )
    finally:
        setup_engine.dispose()
    return table


@pytest.mark.parametrize("executemany", [False, True])
def test_separate_sql_statements_have_separate_budgets_but_executemany_shares_one(
    tmp_path: Path, executemany: bool
) -> None:
    engine = create_sqlite_engine(
        tmp_path / "independent-statements.sqlite3",
        statement_time_budget_seconds=0.25,
        slow_write_threshold_seconds=None,
    )

    @sa.event.listens_for(engine, "connect")
    def register_slow_value(dbapi_connection, _record) -> None:
        def slow_value(value: int) -> int:
            time.sleep(0.08)
            return value

        dbapi_connection.create_function("slow_value", 1, slow_value)

    table = _budget_table(engine)
    statement = (
        sa.update(table)
        .where(table.c.id == sa.bindparam("probe_id"))
        .values(value=sa.func.slow_value(sa.bindparam("new_value")))
    )
    parameters = [{"probe_id": index, "new_value": 999} for index in range(8)]
    try:
        started = time.monotonic()
        if executemany:
            with pytest.raises(OperationalError), engine.begin() as connection:
                connection.execute(statement, parameters)
        else:
            with engine.begin() as connection:
                for bindings in parameters:
                    assert connection.execute(statement, bindings).rowcount == 1
        assert time.monotonic() - started > 0.2
        with engine.connect() as connection:
            assert connection.scalar(
                sa.select(sa.func.count()).where(table.c.value == 999)
            ) == (0 if executemany else 8)
    finally:
        engine.dispose()


def test_writer_waits_past_old_half_second_limit_and_uses_thirty_second_busy_timeout(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "writer-wait.sqlite3")
    table = _budget_table(engine)
    try:
        with engine.connect() as holder:
            assert holder.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30_000
            holder.execute(sa.update(table).where(table.c.id == 0).values(value=1))

            def competing_write() -> float:
                started = time.monotonic()
                with engine.begin() as writer:
                    writer.execute(sa.update(table).where(table.c.id == 1).values(value=2))
                return time.monotonic() - started

            with ThreadPoolExecutor(max_workers=1) as executor:
                waiting = executor.submit(competing_write)
                time.sleep(0.7)
                holder.commit()
                assert waiting.result(timeout=5) >= 0.5
        with engine.connect() as check:
            assert check.scalar(sa.select(table.c.value).where(table.c.id == 1)) == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize("statement_kind", ["read", "write"])
def test_slow_sql_interrupts_and_transaction_rolls_back_with_connection_reuse(
    tmp_path: Path,
    statement_kind: str,
) -> None:
    engine = create_sqlite_engine(
        tmp_path / "slow-statement.sqlite3",
        statement_time_budget_seconds=0.05,
        slow_write_threshold_seconds=None,
    )
    table = _budget_table(engine)
    left, middle, right = (table.alias(name) for name in ("left", "middle", "right"))
    expensive_count = sa.select(sa.func.count()).select_from(
        left.join(middle, left.c.id != middle.c.id).join(
            right, middle.c.id != right.c.id
        )
    )
    try:
        with engine.connect() as connection:
            with (
                pytest.raises(OperationalError, match="interrupted") as interrupted,
                connection.begin(),
            ):
                connection.execute(
                    sa.update(table).where(table.c.id == 0).values(value=999)
                )
                if statement_kind == "read":
                    connection.scalar(expensive_count)
                else:
                    connection.execute(
                        sa.update(table)
                        .where(table.c.id == 1)
                        .values(value=expensive_count.scalar_subquery())
                    )
            assert is_database_operation_timeout(interrupted.value)
            assert (
                format_exception_diagnostics(interrupted.value)["reason"]
                == "time_budget_exceeded"
            )
            trace = format_exception_diagnostics(interrupted.value)["databaseTrace"]
            assert trace["transaction_id"].startswith("dbtx_")
            assert any(
                record["operation"] == "UPDATE" and record["parameters"]
                for record in trace["transaction_statements"]
            )
            assert interrupted.value.orig.sqlite_errorcode == 9
            assert (
                connection.scalar(sa.select(table.c.value).where(table.c.id == 0)) == 0
            )
            connection.rollback()
            with connection.begin():
                connection.execute(
                    sa.update(table).where(table.c.id == 1).values(value=999)
                )
        with engine.connect() as connection:
            assert (
                connection.scalar(sa.select(table.c.value).where(table.c.id == 1))
                == 999
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "fetch_method", ["fetchone", "fetchmany", "fetchall", "iterator"]
)
def test_read_only_sql_budget_includes_result_fetching(
    tmp_path: Path, fetch_method: str
) -> None:
    engine = create_sqlite_engine(
        tmp_path / "fetch-budget.sqlite3",
        statement_time_budget_seconds=0.05,
        slow_write_threshold_seconds=None,
    )

    @sa.event.listens_for(engine, "connect")
    def register_slow_value(dbapi_connection, _record) -> None:
        def slow_value(value: int) -> int:
            time.sleep(0.003)
            return value

        dbapi_connection.create_function("slow_value", 1, slow_value)

    table = _budget_table(engine)
    try:
        with engine.connect() as connection:
            result = connection.execute(sa.select(sa.func.slow_value(table.c.value)))
            with pytest.raises(OperationalError, match="interrupted") as timed_out:
                if fetch_method == "fetchall":
                    result.fetchall()
                elif fetch_method == "fetchmany":
                    while result.fetchmany(3):
                        pass
                elif fetch_method == "fetchone":
                    while result.fetchone() is not None:
                        pass
                else:
                    list(result)
            trace = format_exception_diagnostics(timed_out.value)["databaseTrace"]
            assert trace["phase"] in {"fetchone", "fetchmany", "fetchall", "next"}
            assert 'SELECT slow_value("BudgetProbe".value)' in trace["transaction_statements"][-1]["statement"]
            result.close()
            connection.rollback()
            assert (
                connection.scalar(sa.select(sa.func.count()).select_from(table)) == 200
            )
    finally:
        engine.dispose()


def test_application_pauses_and_other_cursors_do_not_consume_sql_budget(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(
        tmp_path / "paused-fetch.sqlite3",
        statement_time_budget_seconds=0.04,
        slow_write_threshold_seconds=None,
    )
    table = _budget_table(engine)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.update(table).where(table.c.id == 0).values(value=999)
            )
            result = connection.execute(
                sa.select(table.c.id).order_by(table.c.id).limit(3)
            )
            for expected in range(3):
                time.sleep(0.06)
                assert (
                    connection.scalar(sa.select(sa.func.count()).select_from(table))
                    == 200
                )
                assert result.fetchone() == (expected,)
            assert result.fetchone() is None
    finally:
        engine.dispose()


def test_slow_writer_interval_is_logged_with_sql_evidence(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_sqlite_engine(
        tmp_path / "slow-writer.sqlite3",
        slow_write_threshold_seconds=0.01,
    )
    table = _budget_table(engine)
    try:
        caplog.clear()
        with (
            caplog.at_level(logging.INFO, logger="app.db.sqlite"),
            engine.begin() as connection,
        ):
            connection.execute(
                sa.update(table).where(table.c.id == 0).values(value=table.c.value)
            )
            time.sleep(0.02)

        started = next(record for record in caplog.records if record.getMessage().startswith("database_statement_started"))
        finished = next(record for record in caplog.records if record.getMessage().startswith("database_statement_finished"))
        slow = next(record for record in caplog.records if record.getMessage().startswith("database_write_transaction_slow"))
        operation = started.database_operations[0]
        assert 'UPDATE "BudgetProbe"' in operation["statement"]
        assert operation["parameters"] == (0,)
        assert f"statement_id={json.loads(finished.getMessage().split(' ', 1)[1])['statement_id']}" in started.getMessage()
        assert json.loads(slow.getMessage().split(" ", 1)[1])["outcome"] == "committed"
    finally:
        engine.dispose()


def test_slow_write_transaction_is_saved_with_full_sql_and_bindings(tmp_path: Path) -> None:
    engine = create_sqlite_engine(
        tmp_path / "slow-write-event.sqlite3",
        slow_write_threshold_seconds=0.01,
    )
    SystemEvent.__table__.create(engine)
    SystemSetting.__table__.create(engine)
    try:
        with DiagnosticSession(engine) as session:
            session.execute(sa.insert(SystemSetting).values(key="probe", value="full binding"))
            time.sleep(0.02)
            session.commit()
        with DiagnosticSession(engine, info={"diagnostics_storage": True}) as check:
            event_row = check.scalars(
                sa.select(SystemEvent).where(
                    SystemEvent.action == "database.write_transaction_slow"
                )
            ).one().metadata_json
        trace = event_row["databaseTrace"]
        assert trace["outcome"] == "committed"
        assert trace["duration_ms"] >= 10
        assert trace["statements"][0]["parameters"][:2] == ["probe", "full binding"]
        assert 'INSERT INTO "SystemSetting"' in trace["statements"][0]["statement"]
        assert trace["statements"][0]["timing"]["statement_id"] == trace["statements"][0]["statement_id"]
        assert trace["slowest_statement_id"] == trace["statements"][0]["statement_id"]
    finally:
        engine.dispose()


def test_default_slow_write_threshold_records_only_transactions_over_one_second(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_sqlite_engine(tmp_path / "default-slow-write-event.sqlite3")
    SystemEvent.__table__.create(engine)
    SystemSetting.__table__.create(engine)
    try:
        with caplog.at_level(logging.WARNING, logger="app.db.sqlite"):
            with DiagnosticSession(engine) as session:
                session.execute(sa.insert(SystemSetting).values(key="fast", value="fast"))
                time.sleep(0.15)
                session.commit()

            with DiagnosticSession(engine, info={"diagnostics_storage": True}) as check:
                assert check.scalar(
                    sa.select(sa.func.count()).select_from(SystemEvent).where(
                        SystemEvent.action == "database.write_transaction_slow"
                    )
                ) == 0

            with DiagnosticSession(engine) as session:
                session.execute(sa.insert(SystemSetting).values(key="slow", value="slow"))
                time.sleep(1.05)
                session.commit()

        warnings = [
            record for record in caplog.records
            if record.getMessage().startswith("database_write_transaction_slow")
        ]
        assert len(warnings) == 1
        assert json.loads(warnings[0].getMessage().split(" ", 1)[1])["duration_ms"] > 1000
        with DiagnosticSession(engine, info={"diagnostics_storage": True}) as check:
            events = check.scalars(
                sa.select(SystemEvent).where(SystemEvent.action == "database.write_transaction_slow")
            ).all()
        assert len(events) == 1
        assert events[0].metadata_json["databaseTrace"]["duration_ms"] > 1000
    finally:
        engine.dispose()


def test_database_failure_event_keeps_preceding_transaction_statements(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "failed-transaction-event.sqlite3")
    SystemEvent.__table__.create(engine)
    SystemSetting.__table__.create(engine)
    diagnostics.configure_exception_storage(sessionmaker(bind=engine, class_=Session))
    try:
        with DiagnosticSession(engine) as session:
            session.execute(sa.insert(SystemSetting).values(key="first", value="first binding"))
            session.execute(sa.insert(SystemSetting).values(key="duplicate", value="second binding"))
            try:
                session.execute(sa.insert(SystemSetting).values(key="duplicate", value="failed binding"))
            except IntegrityError:
                session.rollback()
        with Session(engine) as check:
            event_row = check.scalars(sa.select(SystemEvent)).one()
        trace = event_row.metadata_json["diagnostics"]["databaseTrace"]
        assert trace["outcome"] == "failed"
        assert len(trace["transaction_statements"]) == 3
        assert trace["transaction_statements"][0]["parameters"][:2] == ["first", "first binding"]
        assert trace["transaction_statements"][2]["parameters"][:2] == ["duplicate", "failed binding"]
    finally:
        diagnostics.reset_exception_storage()
        engine.dispose()
