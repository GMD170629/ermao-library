from __future__ import annotations

from types import TracebackType

from app.modules.imports.application.ports import ImportUnitOfWork


class ImportWriteTransaction:
    """Named short unit-of-work boundary for already prepared import writes."""

    def __init__(self, unit_of_work: ImportUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    def __enter__(self) -> ImportWriteTransaction:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        if exc_type is None:
            self._unit_of_work.commit()
        else:
            self._unit_of_work.rollback()
        return False


def commit_import_checkpoint(unit_of_work: ImportUnitOfWork) -> None:
    """Commit writes already staged by the file-processing adapter."""

    unit_of_work.commit()


def release_import_transaction(unit_of_work: ImportUnitOfWork) -> None:
    """Commit and release the database connection before external I/O."""

    unit_of_work.release()


def reset_failed_import_checkpoint(unit_of_work: ImportUnitOfWork) -> None:
    """Discard a failed checkpoint before recording a terminal worker result."""

    unit_of_work.rollback()
