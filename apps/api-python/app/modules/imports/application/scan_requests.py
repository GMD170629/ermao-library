"""Named atomic command for prepared monitor scan requests."""

from __future__ import annotations

from typing import Protocol

from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.imports.application.scan_jobs import PreparedImportScanJob
from app.modules.system.public import PreparedSystemEvent


class ScanRequestStore(Protocol):
    def write(
        self,
        scan_jobs: tuple[PreparedImportScanJob, ...],
        events: tuple[PreparedSystemEvent, ...],
    ) -> int: ...


def persist_scan_requests(
    store: ScanRequestStore,
    unit_of_work: ImportUnitOfWork,
    scan_jobs: tuple[PreparedImportScanJob, ...],
    events: tuple[PreparedSystemEvent, ...],
) -> int:
    """Commit one set of jobs and its audit events as a single checkpoint."""

    try:
        created_count = store.write(scan_jobs, events)
        unit_of_work.commit()
        return created_count
    except Exception:
        unit_of_work.rollback()
        raise
