"""Pure sizing rules for bounded SQLite expression batches."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TypeVar

BatchValue = TypeVar("BatchValue")

SQLITE_BIND_PARAMETER_BUDGET = 900


def rows_per_sqlite_statement(
    *,
    parameters_per_row: int,
    fixed_parameters: int = 0,
    parameter_budget: int = SQLITE_BIND_PARAMETER_BUDGET,
) -> int:
    if parameters_per_row < 1:
        raise ValueError("parameters_per_row must be positive")
    if fixed_parameters < 0:
        raise ValueError("fixed_parameters cannot be negative")
    available = parameter_budget - fixed_parameters
    if available < parameters_per_row:
        raise ValueError("parameter budget cannot fit one row")
    return available // parameters_per_row


def sqlite_parameter_chunks(
    values: Sequence[BatchValue],
    *,
    parameters_per_row: int,
    fixed_parameters: int = 0,
    parameter_budget: int = SQLITE_BIND_PARAMETER_BUDGET,
) -> Iterator[tuple[BatchValue, ...]]:
    chunk_size = rows_per_sqlite_statement(
        parameters_per_row=parameters_per_row,
        fixed_parameters=fixed_parameters,
        parameter_budget=parameter_budget,
    )
    for offset in range(0, len(values), chunk_size):
        yield tuple(values[offset : offset + chunk_size])
