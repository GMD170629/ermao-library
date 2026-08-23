from __future__ import annotations

import sqlalchemy as sa

from tests.support.sqlalchemy import StatementRecorder


def test_statement_recorder_counts_executemany_as_one_statement() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    probe = sa.Table(
        "StatementProbe",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(engine)
    try:
        with StatementRecorder(engine) as recorder:
            with engine.begin() as connection:
                connection.execute(sa.select(sa.literal(1)))
            recorder.reset_after_warmup()
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(probe),
                    [{"id": 1}, {"id": 2}, {"id": 3}],
                )

            assert recorder.statement_count == 1
            assert recorder.dml_count == 1
            assert recorder.observations[0].executemany is True
    finally:
        engine.dispose()
