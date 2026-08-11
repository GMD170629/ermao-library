"""Stage and enqueue import tasks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.imports.application.ports import ImportUnitOfWork


@dataclass(frozen=True, slots=True)
class ImportEnqueueProjection:
    existing_task: Mapping[str, object] | None
    existing_work: Mapping[str, object] | None
    media_kind_policy: str


@dataclass(frozen=True, slots=True)
class PreparedImportEnqueue:
    task: ImportTaskDTO
    created: bool
    task_row: Mapping[str, object] | None
    asset_rows: tuple[Mapping[str, object], ...]
    work_row: Mapping[str, object] | None
    refresh_work_id: str | None
    available_at: datetime


class PreparedImportEnqueueStore(Protocol):
    def write(self, prepared: PreparedImportEnqueue) -> None: ...


def persist_prepared_import_enqueue(
    store: PreparedImportEnqueueStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedImportEnqueue,
) -> tuple[ImportTaskDTO, bool]:
    """Commit one fully prepared enqueue hand-off in a short transaction."""

    try:
        store.write(prepared)
        unit_of_work.commit()
        return prepared.task, prepared.created
    except Exception:
        unit_of_work.rollback()
        raise
