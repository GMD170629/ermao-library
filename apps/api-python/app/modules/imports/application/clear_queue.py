"""Clear every persisted import-queue record inside one transaction."""

from __future__ import annotations

from typing import Protocol

from app.modules.imports.application.ports import ImportUnitOfWork


class ImportQueueMaintenanceStore(Protocol):
    """Persistence needed by the queue-clear control operation."""

    def delete_all_tasks(self) -> int: ...


def clear_import_queue(
    store: ImportQueueMaintenanceStore,
    unit_of_work: ImportUnitOfWork,
) -> int:
    """Delete all queue states while preserving imported library content and files."""

    try:
        deleted = store.delete_all_tasks()
        unit_of_work.commit()
        return deleted
    except Exception:
        unit_of_work.rollback()
        raise
