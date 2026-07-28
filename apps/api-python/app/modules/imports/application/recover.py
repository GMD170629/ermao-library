"""Recover stale PARSING import tasks back to PENDING."""

from __future__ import annotations

from app.modules.imports.application.commands import commit_import_checkpoint
from app.modules.imports.application.ports import ImportTaskStore, ImportUnitOfWork

DEFAULT_RECOVER_MESSAGE = "后台任务恢复后重新排队"


def recover_stale_import_tasks(
    store: ImportTaskStore,
    unit_of_work: ImportUnitOfWork,
    *,
    now: int,
    message: str = DEFAULT_RECOVER_MESSAGE,
) -> int:
    recovered = store.recover_stale(now=now, message=message)
    commit_import_checkpoint(unit_of_work)
    return recovered
