from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

ResultT = TypeVar("ResultT")


class KindleUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def execute_kindle_write(
    unit_of_work: KindleUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    """Commit one Kindle settings or send-task state transition."""

    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result
