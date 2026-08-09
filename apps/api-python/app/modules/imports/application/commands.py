from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from app.modules.imports.application.ports import ImportUnitOfWork

ResultT = TypeVar("ResultT")


def execute_import_checkpoint(
    unit_of_work: ImportUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    """Persist one recoverable import state transition."""

    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result


def commit_import_checkpoint(unit_of_work: ImportUnitOfWork) -> None:
    """Commit writes already staged by the file-processing adapter."""

    execute_import_checkpoint(unit_of_work, lambda: None)


def release_import_transaction(unit_of_work: ImportUnitOfWork) -> None:
    """Commit and release the database connection before external I/O."""

    unit_of_work.release()


def reset_failed_import_checkpoint(unit_of_work: ImportUnitOfWork) -> None:
    """Discard a failed checkpoint before recording a terminal worker result."""

    unit_of_work.rollback()
