"""Application use cases for Book mutations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class BookMutationPort(Protocol):
    """Persistence operations required by the Book mutation use case."""

    def update_book(
        self, *, book_id: str, values: Mapping[str, object]
    ) -> Mapping[str, object] | None: ...


class BookMutationUnitOfWork(Protocol):
    """Transaction boundary owned by a Book mutation."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class UpdateBookCommand:
    book_id: str
    values: Mapping[str, object]


class UpdateBook:
    """Apply one Book update and own its database transaction."""

    def __init__(
        self,
        port: BookMutationPort,
        unit_of_work: BookMutationUnitOfWork,
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work

    def execute(self, command: UpdateBookCommand) -> Mapping[str, object] | None:
        try:
            updated = self._port.update_book(
                book_id=command.book_id,
                values=command.values,
            )
            if updated is None:
                self._unit_of_work.rollback()
                return None
            self._unit_of_work.commit()
            return updated
        except Exception:
            self._unit_of_work.rollback()
            raise


__all__ = [
    "BookMutationPort",
    "BookMutationUnitOfWork",
    "UpdateBook",
    "UpdateBookCommand",
]
