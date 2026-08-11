"""SQL adapter for the monitor rescan completion checkpoint."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.settings import SystemSetting
from app.modules.imports.application.scan_jobs import PreparedImportScanJob
from app.modules.imports.infrastructure.work_queue import insert_prepared_scan_jobs
from app.modules.system.public import PreparedSystemEvent
from app.services.system_events import write_prepared_system_events


class SqlAlchemyRescanCompletionStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def persist(
        self,
        *,
        setting_key: str,
        setting_value: str,
        checkpoint_at: datetime,
        scan_jobs: tuple[PreparedImportScanJob, ...],
        events: tuple[PreparedSystemEvent, ...],
    ) -> int:
        created_count = insert_prepared_scan_jobs(self._db, scan_jobs)
        self._db.execute(
            sqlite_insert(SystemSetting)
            .values(
                key=setting_key,
                value=setting_value,
                created_at=checkpoint_at,
                updated_at=checkpoint_at,
            )
            .on_conflict_do_update(
                index_elements=[SystemSetting.key],
                set_={
                    "value": setting_value,
                    "updated_at": checkpoint_at,
                },
            )
        )
        write_prepared_system_events(self._db, events)
        return created_count
