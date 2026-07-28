"""Claim the next pending import task under a worker lease."""

from __future__ import annotations

from app.modules.imports.application.commands import commit_import_checkpoint
from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.imports.application.ports import ImportTaskStore, ImportUnitOfWork


def claim_next_import_task(
    store: ImportTaskStore,
    unit_of_work: ImportUnitOfWork,
    worker_id: str,
    lease_seconds: int,
    *,
    now: int,
) -> ImportTaskDTO | None:
    task = store.claim_next(
        worker_id,
        lease_seconds=lease_seconds,
        now=now,
    )
    commit_import_checkpoint(unit_of_work)
    return task
