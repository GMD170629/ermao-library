from __future__ import annotations

import pytest
from app.core.sql_batches import rows_per_sqlite_statement, sqlite_parameter_chunks


def test_sqlite_chunks_respect_parameter_budget() -> None:
    values = tuple(range(230))

    chunks = tuple(sqlite_parameter_chunks(values, parameters_per_row=7))

    assert tuple(len(chunk) for chunk in chunks) == (128, 102)
    assert all(len(chunk) * 7 <= 900 for chunk in chunks)


def test_sqlite_chunks_include_fixed_parameters_in_budget() -> None:
    assert (
        rows_per_sqlite_statement(
            parameters_per_row=4,
            fixed_parameters=4,
        )
        == 224
    )


@pytest.mark.parametrize(
    ("parameters_per_row", "fixed_parameters"),
    ((0, 0), (1, -1), (901, 0)),
)
def test_invalid_sqlite_chunk_budget_is_rejected(
    parameters_per_row: int,
    fixed_parameters: int,
) -> None:
    with pytest.raises(ValueError):
        rows_per_sqlite_statement(
            parameters_per_row=parameters_per_row,
            fixed_parameters=fixed_parameters,
        )
