"""Named persistence command for a completed monitor rescan request."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.imports.application.scan_jobs import PreparedImportScanJob
from app.modules.system.public import PreparedSystemEvent


class RescanCompletionStore(Protocol):
    def persist(
        self,
        *,
        setting_key: str,
        setting_value: str,
        checkpoint_at: datetime,
        scan_jobs: tuple[PreparedImportScanJob, ...],
        events: tuple[PreparedSystemEvent, ...],
    ) -> int: ...


def persist_rescan_completion(
    store: RescanCompletionStore,
    unit_of_work: ImportUnitOfWork,
    *,
    setting_key: str,
    setting_value: str,
    checkpoint_at: datetime,
    scan_jobs: tuple[PreparedImportScanJob, ...],
    events: tuple[PreparedSystemEvent, ...],
) -> int:
    try:
        created_count = store.persist(
            setting_key=setting_key,
            setting_value=setting_value,
            checkpoint_at=checkpoint_at,
            scan_jobs=scan_jobs,
            events=events,
        )
        unit_of_work.commit()
        return created_count
    except Exception:
        unit_of_work.rollback()
        raise
