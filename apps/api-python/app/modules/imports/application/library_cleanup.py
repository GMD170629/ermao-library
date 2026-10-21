"""Resume one bounded part of an already committed library removal."""

from typing import Protocol

from app.core.exception_diagnostics import capture_exception
from app.modules.imports.application.library_commands import LibraryWriteUnitOfWork


class LibraryCleanupStore(Protocol):
    def advance(self) -> bool: ...


class ProcessLibraryCleanup:
    def __init__(self, store: LibraryCleanupStore, unit_of_work: LibraryWriteUnitOfWork) -> None:
        self._store = store
        self._unit_of_work = unit_of_work

    def execute(self) -> bool:
        try:
            worked = self._store.advance()
            if worked:
                self._unit_of_work.commit()
            else:
                self._unit_of_work.rollback()
            return worked
        except Exception as error:
            capture_exception(error)
            self._unit_of_work.rollback()
            raise
