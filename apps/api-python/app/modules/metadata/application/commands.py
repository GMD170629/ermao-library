from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

ResultT = TypeVar("ResultT")


class MetadataUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def execute_metadata_transaction(
    unit_of_work: MetadataUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    """Commit one recoverable metadata lifecycle transition."""

    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result
