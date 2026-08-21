"""Bridge LibraryImportTask onto the ADR 0002 ImportWorkItem queue."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.common import cuid, db_timestamp
from app.models.import_pipeline import ImportScanJob, ImportTask, ImportWorkItem
from app.modules.imports.application.readable_resource.ports import WorkQueuePort
from app.modules.imports.infrastructure.work_queue import (
    claim_next_work_item,
    complete_work_item,
    ensure_import_work_item,
)

OVERLAY_IMPORT_ORIGIN = "READABLE_RESOURCE_OVERLAY"
OVERLAY_SCAN_TRIGGER = "READABLE_RESOURCE_SCAN"


class SqlAlchemyReadableResourceWorkQueue(WorkQueuePort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def queued_item_count(self) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(ImportWorkItem)
                .where(ImportWorkItem.status.in_(("PENDING", "LEASED")))
            )
            or 0
        )

    def enqueue_library_import_task(self, task_id: str) -> None:
        bridge = self._session.scalar(
            select(ImportTask).where(
                ImportTask.origin == OVERLAY_IMPORT_ORIGIN,
                ImportTask.source_path == task_id,
            )
        )
        if bridge is None:
            bridge = ImportTask(
                id=cuid(),
                library_id=None,
                origin=OVERLAY_IMPORT_ORIGIN,
                status="PENDING",
                source_path=task_id,
                source_key=f"overlay-task:{task_id}",
                task_kind="READABLE_RESOURCE",
            )
            self._session.add(bridge)
            self._session.flush()
        ensure_import_work_item(self._session, bridge, priority=20)
        self._session.flush()

    def enqueue_library_scan(self, library_id: str) -> None:
        job = ImportScanJob(
            id=cuid(),
            library_id=library_id,
            actor_user_id=None,
            root_path="",
            trigger=OVERLAY_SCAN_TRIGGER,
            status="PENDING",
        )
        self._session.add(job)
        self._session.flush()
        work = ImportWorkItem(
            id=f"work_{cuid()}",
            kind="SCAN_DIRECTORY",
            scan_job_id=job.id,
            import_task_id=None,
            dedupe_key=f"overlay-scan:{library_id}:{job.id}",
            status="PENDING",
            priority=50,
        )
        self._session.add(work)
        self._session.flush()

    def claim_next(
        self, worker_id: str, *, lease_seconds: int
    ) -> tuple[str, str] | None:
        item = claim_next_work_item(
            self._session, worker_id=worker_id, import_lease_seconds=lease_seconds
        )
        if item is None:
            return None
        if item.kind == "SCAN_DIRECTORY" and item.scan_job_id is not None:
            job = self._session.get(ImportScanJob, item.scan_job_id)
            if job is None or job.trigger != OVERLAY_SCAN_TRIGGER:
                # Not an overlay scan; release lease for legacy workers.
                self._session.execute(
                    update(ImportWorkItem)
                    .where(ImportWorkItem.id == item.id)
                    .values(
                        status="PENDING",
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=db_timestamp(),
                    )
                )
                self._session.flush()
                return None
            return ("scan", job.library_id)
        if item.kind == "IMPORT_SOURCE" and item.import_task_id is not None:
            bridge = self._session.get(ImportTask, item.import_task_id)
            if bridge is None or bridge.origin != OVERLAY_IMPORT_ORIGIN:
                self._session.execute(
                    update(ImportWorkItem)
                    .where(ImportWorkItem.id == item.id)
                    .values(
                        status="PENDING",
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=db_timestamp(),
                    )
                )
                self._session.flush()
                return None
            return ("import", bridge.source_path)
        return None

    def complete(self, work_kind: str, target_id: str) -> None:
        if work_kind == "import":
            bridge = self._session.scalar(
                select(ImportTask).where(
                    ImportTask.origin == OVERLAY_IMPORT_ORIGIN,
                    ImportTask.source_path == target_id,
                )
            )
            if bridge is None:
                return
            work = self._session.scalar(
                select(ImportWorkItem).where(
                    ImportWorkItem.import_task_id == bridge.id
                )
            )
            if work is not None:
                complete_work_item(self._session, work.id)
            bridge.status = "COMPLETED"
            self._session.flush()
            return
        if work_kind == "scan":
            job = self._session.scalar(
                select(ImportScanJob)
                .where(
                    ImportScanJob.library_id == target_id,
                    ImportScanJob.trigger == OVERLAY_SCAN_TRIGGER,
                    ImportScanJob.status.in_(("PENDING", "RUNNING")),
                )
                .order_by(ImportScanJob.created_at.desc())
                .limit(1)
            )
            if job is None:
                return
            work = self._session.scalar(
                select(ImportWorkItem).where(ImportWorkItem.scan_job_id == job.id)
            )
            if work is not None:
                complete_work_item(self._session, work.id)
            job.status = "COMPLETED"
            self._session.flush()

    def heartbeat(self, work_kind: str, target_id: str, worker_id: str) -> None:
        now = db_timestamp()
        expires = now + timedelta(seconds=60)
        if work_kind == "import":
            bridge = self._session.scalar(
                select(ImportTask).where(
                    ImportTask.origin == OVERLAY_IMPORT_ORIGIN,
                    ImportTask.source_path == target_id,
                )
            )
            if bridge is None:
                return
            self._session.execute(
                update(ImportWorkItem)
                .where(
                    ImportWorkItem.import_task_id == bridge.id,
                    ImportWorkItem.lease_owner == worker_id,
                )
                .values(lease_expires_at=expires, updated_at=now)
            )
            self._session.flush()
