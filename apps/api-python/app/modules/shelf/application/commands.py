"""Transaction boundary for shelf write intentions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

ResultT = TypeVar("ResultT")


class ShelfUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def execute_shelf_write(
    unit_of_work: ShelfUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result
