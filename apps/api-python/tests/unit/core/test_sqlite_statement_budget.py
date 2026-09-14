from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from app.db.sqlite import (
    SHORT_WRITE_LOCK_TIMEOUT_SECONDS,
    SQLITE_STATEMENT_TIMEOUT_SECONDS,
    create_sqlite_engine,
)


def test_statement_budget_and_lock_wait_are_independent() -> None:
    assert SHORT_WRITE_LOCK_TIMEOUT_SECONDS == 0.5
    assert SQLITE_STATEMENT_TIMEOUT_SECONDS == 2.0


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
def test_sql_statements_do_not_share_a_transaction_deadline(
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
        with engine.begin() as connection:
            if executemany:
                assert connection.execute(statement, parameters).rowcount == 8
            else:
                for bindings in parameters:
                    assert connection.execute(statement, bindings).rowcount == 1
        assert time.monotonic() - started > 0.5
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.select(sa.func.count()).where(table.c.value == 999)
                )
                == 8
            )
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
                pytest.raises(OperationalError, match="interrupted"),
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
            with pytest.raises(OperationalError, match="interrupted"):
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


def test_slow_writer_interval_is_logged_without_sql_text(
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
            caplog.at_level(logging.WARNING, logger="app.db.sqlite"),
            engine.begin() as connection,
        ):
            connection.execute(
                sa.update(table).where(table.c.id == 0).values(value=table.c.value)
            )
            time.sleep(0.02)

        messages = [record.getMessage() for record in caplog.records]
        assert len(messages) == 1
        assert "database_write_transaction_slow outcome=committed" in messages[0]
        assert "UPDATE" not in messages[0]
    finally:
        engine.dispose()
