from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

ResultT = TypeVar("ResultT")


class LibraryUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def execute_library_write(
    unit_of_work: LibraryUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result
