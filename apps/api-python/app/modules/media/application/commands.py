"""Transaction boundary for media projection writes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

ResultT = TypeVar("ResultT")


class MediaUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def execute_media_write(
    unit_of_work: MediaUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result
