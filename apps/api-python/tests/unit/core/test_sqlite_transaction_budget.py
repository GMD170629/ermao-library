from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
from app.db.sqlite import create_sqlite_engine
from sqlalchemy.exc import OperationalError


def _budget_table(engine: sa.Engine) -> sa.Table:
    metadata = sa.MetaData()
    table = sa.Table(
        "BudgetProbe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(table),
            [{"id": index, "value": index} for index in range(200)],
        )
    return table


def test_transaction_budget_starts_at_first_dml(tmp_path: Path) -> None:
    engine = create_sqlite_engine(
        tmp_path / "budget-after-dml.sqlite3",
        transaction_time_budget_seconds=0.01,
        slow_write_threshold_seconds=None,
    )
    table = _budget_table(engine)
    try:
        with engine.begin() as connection:
            assert (
                connection.scalar(sa.select(sa.func.count()).select_from(table)) == 200
            )
            time.sleep(0.02)
            connection.execute(
                sa.update(table).where(table.c.id == 0).values(value=table.c.value)
            )
    finally:
        engine.dispose()


def test_transaction_budget_interrupts_work_after_first_dml(tmp_path: Path) -> None:
    engine = create_sqlite_engine(
        tmp_path / "budget-writer-interval.sqlite3",
        transaction_time_budget_seconds=0.01,
        slow_write_threshold_seconds=None,
    )
    table = _budget_table(engine)
    left = table.alias("budget_left")
    middle = table.alias("budget_middle")
    right = table.alias("budget_right")
    try:
        with (
            pytest.raises(OperationalError, match="interrupted"),
            engine.begin() as connection,
        ):
            connection.execute(
                sa.update(table).where(table.c.id == 0).values(value=table.c.value)
            )
            time.sleep(0.02)
            connection.scalar(
                sa.select(sa.func.count()).select_from(
                    left.join(middle, left.c.id != middle.c.id).join(
                        right, middle.c.id != right.c.id
                    )
                )
            )

        with engine.begin() as connection:
            connection.execute(
                sa.update(table).where(table.c.id == 1).values(value=table.c.value)
            )
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
