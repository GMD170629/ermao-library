"""Atomic persistence contract for one prepared directory-scan slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.imports.application.work_queue_dto import PreparedScanCandidateBatch
from app.modules.system.public import PreparedSystemEvent

ScanWorkDisposition = Literal["complete", "release", "keep"]


@dataclass(frozen=True, slots=True)
class PreparedScanCheckpoint:
    job_id: str | None
    work_item_id: str
    job_values: dict[str, object]
    work_disposition: ScanWorkDisposition
    work_available_at: datetime | None
    candidate_batch: PreparedScanCandidateBatch | None
    events: tuple[PreparedSystemEvent, ...]


class ScanCheckpointStore(Protocol):
    def write(self, prepared: PreparedScanCheckpoint) -> None: ...


def persist_scan_checkpoint(
    store: ScanCheckpointStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedScanCheckpoint,
) -> None:
    """Persist one scanner state transition in a SQL-only short transaction."""

    try:
        store.write(prepared)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
