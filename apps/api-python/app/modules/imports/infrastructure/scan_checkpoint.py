"""SQLAlchemy adapter for prepared directory-scan checkpoints."""

from __future__ import annotations

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import ImportScanJob, ImportWorkItem
from app.modules.imports.application.scan_checkpoint import PreparedScanCheckpoint
from app.modules.imports.infrastructure.scan_batch_store import (
    write_prepared_scan_candidate_batch,
)
from app.services.system_events import write_prepared_system_events


class SqlAlchemyScanCheckpointStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def write(self, prepared: PreparedScanCheckpoint) -> None:
        if prepared.candidate_batch is not None:
            write_prepared_scan_candidate_batch(self._db, prepared.candidate_batch)
        if prepared.job_id is not None and prepared.job_values:
            self._db.execute(
                update(ImportScanJob)
                .where(ImportScanJob.id == prepared.job_id)
                .values(**prepared.job_values)
            )
        if prepared.work_disposition == "complete":
            self._db.execute(
                delete(ImportWorkItem).where(
                    ImportWorkItem.id == prepared.work_item_id
                )
            )
        elif prepared.work_disposition == "release":
            self._db.execute(
                update(ImportWorkItem)
                .where(ImportWorkItem.id == prepared.work_item_id)
                .values(
                    status="PENDING",
                    lease_owner=None,
                    lease_expires_at=None,
                    available_at=prepared.work_available_at,
                    updated_at=prepared.work_available_at,
                )
            )
        write_prepared_system_events(self._db, prepared.events)
