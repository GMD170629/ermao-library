"""SQL-only adapter for prepared scan requests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.imports.application.scan_jobs import PreparedImportScanJob
from app.modules.imports.infrastructure.work_queue import insert_prepared_scan_jobs
from app.modules.system.public import PreparedSystemEvent
from app.services.system_events import write_prepared_system_events


class SqlAlchemyScanRequestStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def write(
        self,
        scan_jobs: tuple[PreparedImportScanJob, ...],
        events: tuple[PreparedSystemEvent, ...],
    ) -> int:
        created_count = insert_prepared_scan_jobs(self._db, scan_jobs)
        write_prepared_system_events(self._db, events)
        return created_count
