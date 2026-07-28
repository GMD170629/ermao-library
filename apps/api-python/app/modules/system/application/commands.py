from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

ResultT = TypeVar("ResultT")


class SystemUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def execute_system_transaction(
    unit_of_work: SystemUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    """Commit one independently observable system state transition."""

    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result


def reset_failed_system_transaction(unit_of_work: SystemUnitOfWork) -> None:
    """Reset a failed probe/checkpoint before recording its error state."""

    unit_of_work.rollback()
