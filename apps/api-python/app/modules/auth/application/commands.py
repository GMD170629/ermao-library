from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

ResultT = TypeVar("ResultT")


class AuthUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def execute_auth_write(
    unit_of_work: AuthUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    """Commit one authentication or user-administration state transition."""

    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result
