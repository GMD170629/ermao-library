"""Bridge LibraryImportTask onto the ADR 0002 ImportWorkItem queue."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.common import cuid, db_timestamp
from app.models.import_pipeline import ImportScanJob, ImportTask, ImportWorkItem
from app.modules.imports.application.readable_resource.ports import (
    ClaimedWork,
    WorkQueuePort,
)
from app.modules.imports.infrastructure.work_queue import (
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
                .where(
                    ImportWorkItem.status.in_(("PENDING", "LEASED")),
                    or_(self._overlay_scan_predicate(), self._overlay_import_predicate()),
                )
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

    def claim_next(self, worker_id: str, *, lease_seconds: int) -> ClaimedWork | None:
        now = db_timestamp()
        claimable = or_(
            ImportWorkItem.status == "PENDING",
            and_(
                ImportWorkItem.status == "LEASED",
                ImportWorkItem.lease_expires_at.is_not(None),
                ImportWorkItem.lease_expires_at <= now,
            ),
        )
        row = self._session.scalar(
            select(ImportWorkItem)
            .where(
                ImportWorkItem.available_at <= now,
                claimable,
                or_(self._overlay_scan_predicate(), self._overlay_import_predicate()),
            )
            .order_by(
                ImportWorkItem.priority.asc(),
                ImportWorkItem.created_at.asc(),
                ImportWorkItem.id.asc(),
            )
            .limit(1)
        )
        if row is None:
            return None

        lease_secs = lease_seconds if row.kind == "IMPORT_SOURCE" else min(lease_seconds, 60)
        lease_expires_at = now + timedelta(seconds=lease_secs)
        claimed = self._session.execute(
            update(ImportWorkItem)
            .where(ImportWorkItem.id == row.id, claimable)
            .values(
                status="LEASED",
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
                attempts=ImportWorkItem.attempts + 1,
                updated_at=now,
            )
        )
        if not claimed.rowcount:
            return None

        if row.kind == "SCAN_DIRECTORY" and row.scan_job_id is not None:
            job = self._session.get(ImportScanJob, row.scan_job_id)
            if job is None:
                return None
            if job.status == "PENDING":
                job.status = "RUNNING"
                job.started_at = now
            job.heartbeat_at = now
            job.updated_at = now
            self._session.flush()
            return ClaimedWork(
                work_item_id=row.id,
                work_kind="scan",
                target_id=job.library_id,
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
                scan_job_id=job.id,
                bridge_import_task_id=None,
            )

        if row.kind == "IMPORT_SOURCE" and row.import_task_id is not None:
            bridge = self._session.get(ImportTask, row.import_task_id)
            if bridge is None or bridge.source_path is None:
                return None
            self._session.flush()
            return ClaimedWork(
                work_item_id=row.id,
                work_kind="import",
                target_id=bridge.source_path,
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
                scan_job_id=None,
                bridge_import_task_id=bridge.id,
            )
        return None

    def complete(self, claim: ClaimedWork) -> bool:
        now = db_timestamp()
        leased = self._session.execute(
            update(ImportWorkItem)
            .where(
                ImportWorkItem.id == claim.work_item_id,
                ImportWorkItem.status == "LEASED",
                ImportWorkItem.lease_owner == claim.lease_owner,
                or_(
                    ImportWorkItem.lease_expires_at.is_(None),
                    ImportWorkItem.lease_expires_at > now,
                ),
            )
            .values(updated_at=now)
        )
        if not leased.rowcount:
            return False
        if claim.work_kind == "import" and claim.bridge_import_task_id is not None:
            bridge = self._session.get(ImportTask, claim.bridge_import_task_id)
            if bridge is not None:
                bridge.status = "COMPLETED"
        if claim.work_kind == "scan" and claim.scan_job_id is not None:
            job = self._session.get(ImportScanJob, claim.scan_job_id)
            if job is not None:
                job.status = "COMPLETED"
        complete_work_item(self._session, claim.work_item_id)
        self._session.flush()
        return True

    def heartbeat(self, claim: ClaimedWork) -> bool:
        return self.fence_claim(claim, lease_seconds=60)

    def fence_claim(self, claim: ClaimedWork, *, lease_seconds: int) -> bool:
        now = db_timestamp()
        expires = now + timedelta(seconds=lease_seconds)
        result = self._session.execute(
            update(ImportWorkItem)
            .where(
                ImportWorkItem.id == claim.work_item_id,
                ImportWorkItem.status == "LEASED",
                ImportWorkItem.lease_owner == claim.lease_owner,
                or_(
                    ImportWorkItem.lease_expires_at.is_(None),
                    ImportWorkItem.lease_expires_at > now,
                ),
            )
            .values(lease_expires_at=expires, updated_at=now)
        )
        self._session.flush()
        return bool(result.rowcount)

    def release_and_requeue(
        self, claim: ClaimedWork, *, delay_seconds: int = 5
    ) -> bool:
        now = db_timestamp()
        available_at = now + timedelta(seconds=delay_seconds)
        result = self._session.execute(
            update(ImportWorkItem)
            .where(
                ImportWorkItem.id == claim.work_item_id,
                ImportWorkItem.lease_owner == claim.lease_owner,
            )
            .values(
                status="PENDING",
                lease_owner=None,
                lease_expires_at=None,
                available_at=available_at,
                updated_at=now,
            )
        )
        self._session.flush()
        return bool(result.rowcount)

    def is_claim_valid(self, claim: ClaimedWork) -> bool:
        row = self._session.get(ImportWorkItem, claim.work_item_id)
        if row is None:
            return False
        if row.status != "LEASED" or row.lease_owner != claim.lease_owner:
            return False
        now = db_timestamp()
        if row.lease_expires_at is not None and row.lease_expires_at <= now:
            return False
        return True

    def _overlay_scan_predicate(self) -> object:
        return and_(
            ImportWorkItem.kind == "SCAN_DIRECTORY",
            ImportWorkItem.scan_job_id.is_not(None),
            exists().where(
                and_(
                    ImportScanJob.id == ImportWorkItem.scan_job_id,
                    ImportScanJob.trigger == OVERLAY_SCAN_TRIGGER,
                )
            ),
        )

    def _overlay_import_predicate(self) -> object:
        return and_(
            ImportWorkItem.kind == "IMPORT_SOURCE",
            ImportWorkItem.import_task_id.is_not(None),
            exists().where(
                and_(
                    ImportTask.id == ImportWorkItem.import_task_id,
                    ImportTask.origin == OVERLAY_IMPORT_ORIGIN,
                )
            ),
        )
