from __future__ import annotations

from types import TracebackType
from typing import Literal, Protocol


class AuthUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class AuthWriteTransaction:
    """Own one auth write boundary whose body contains persistence calls only."""

    def __init__(self, unit_of_work: AuthUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exception_type is not None:
            self._unit_of_work.rollback()
            return False
        try:
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return False
