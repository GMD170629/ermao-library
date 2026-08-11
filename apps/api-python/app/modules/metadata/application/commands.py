"""Named metadata unit-of-work boundary shared by worker commands."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self


class MetadataUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class MetadataWriteTransaction:
    """Commit or roll back one named metadata command boundary."""

    def __init__(self, unit_of_work: MetadataUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exception, traceback
        if exception_type is None:
            self._unit_of_work.commit()
        else:
            self._unit_of_work.rollback()
        return False
