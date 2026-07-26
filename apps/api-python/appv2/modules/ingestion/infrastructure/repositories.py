from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from appv2.modules.ingestion.contracts import (
    ImportRequest,
    ImportResult,
    IngestionJob,
    IngestionOutboxEvent,
    IngestionPolicy,
    IngestionRepository,
    JobLog,
    MonitorFolder,
    ScanRun,
)
from appv2.modules.ingestion.infrastructure.models import (
    IngestionJobLogRecord,
    IngestionJobRecord,
    IngestionOutboxRecord,
    IngestionPolicyRecord,
    MonitorFolderRecord,
    MonitorObservationRecord,
    ScanRunRecord,
)


def _job(record: IngestionJobRecord) -> IngestionJob:
    return IngestionJob(
        id=record.id,
        kind=record.kind,
        origin=record.origin,
        status=record.status,
        stage=record.stage,
        progress=record.progress,
        source_path=record.source_path,
        requested_by=record.requested_by,
        monitor_folder_id=record.monitor_folder_id,
        triggered_by=record.triggered_by,
        options=record.options,
        attempt=record.attempt,
        max_attempts=record.max_attempts,
        next_attempt_at=record.next_attempt_at,
        lease_expires_at=record.lease_expires_at,
        cancel_requested=record.cancel_requested,
        result_work_id=record.result_work_id,
        result_edition_id=record.result_edition_id,
        result_volume_ids=tuple(uuid.UUID(value) for value in record.result_volume_ids),
        retryable=record.retryable,
        error_code=record.error_code,
        error_detail=record.error_detail,
        started_at=record.started_at,
        finished_at=record.finished_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _folder(record: MonitorFolderRecord) -> MonitorFolder:
    return MonitorFolder(
        id=record.id,
        path=record.path,
        enabled=record.enabled,
        recursive=record.recursive,
        options=record.options,
        last_scan_at=record.last_scan_at,
        created_at=record.created_at,
    )


def _scan_run(record: ScanRunRecord) -> ScanRun:
    return ScanRun(
        id=record.id,
        trigger=record.trigger,
        status=record.status,
        monitor_folder_id=record.monitor_folder_id,
        requested_by=record.requested_by,
        directories_scanned=record.directories_scanned,
        files_scanned=record.files_scanned,
        candidates_found=record.candidates_found,
        queued=record.queued,
        ignored=record.ignored,
        errors=tuple(record.errors),
        started_at=record.started_at,
        finished_at=record.finished_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _policy(record: IngestionPolicyRecord) -> IngestionPolicy:
    return IngestionPolicy(
        id=record.id,
        allowed_extensions=tuple(record.allowed_extensions),
        ignore_patterns=tuple(record.ignore_patterns),
        stability_check_enabled=record.stability_check_enabled,
        stability_check_seconds=record.stability_check_seconds,
        auto_convert_to_epub=record.auto_convert_to_epub,
        updated_at=record.updated_at,
    )


class SqlIngestionRepository(IngestionRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, request: ImportRequest, *, kind: str = "import") -> ImportResult:
        statement = (
            insert(IngestionJobRecord)
            .values(
                kind=kind,
                origin=request.origin,
                status="queued",
                stage="queued",
                progress=0,
                source_path=request.source_path,
                requested_by=request.requested_by,
                monitor_folder_id=request.monitor_folder_id,
                triggered_by=request.triggered_by,
                idempotency_key=request.idempotency_key,
                options=request.options,
                attempt=0,
                max_attempts=5,
                next_attempt_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(IngestionJobRecord)
        )
        record = self._session.scalar(statement)
        duplicate = record is None
        if record is None:
            record = self._session.scalar(
                select(IngestionJobRecord).where(
                    IngestionJobRecord.idempotency_key == request.idempotency_key
                )
            )
        if record is None:
            raise RuntimeError("failed to enqueue or locate ingestion job")
        return ImportResult(
            job_id=record.id,
            status=record.status,
            work_id=record.result_work_id,
            edition_id=record.result_edition_id,
            volume_ids=tuple(uuid.UUID(value) for value in record.result_volume_ids),
            duplicate=duplicate,
        )

    def list_jobs(
        self,
        *,
        offset: int,
        limit: int,
        status: str | None,
        kind: str | None,
        origin: str | None = None,
        keyword: str | None = None,
        monitor_folder_ids: tuple[uuid.UUID, ...] | None = None,
        requested_by: uuid.UUID | None = None,
    ) -> tuple[list[IngestionJob], int]:
        criteria: list[ColumnElement[bool]] = []
        if status:
            criteria.append(IngestionJobRecord.status == status)
        if kind:
            criteria.append(IngestionJobRecord.kind == kind)
        if origin:
            criteria.append(IngestionJobRecord.origin == origin)
        if keyword:
            criteria.append(IngestionJobRecord.source_path.ilike(f"%{keyword}%"))
        if monitor_folder_ids is not None:
            scope: list[ColumnElement[bool]] = [
                IngestionJobRecord.monitor_folder_id.in_(monitor_folder_ids)
            ]
            if requested_by is not None:
                scope.append(IngestionJobRecord.requested_by == requested_by)
            criteria.append(or_(*scope))
        total = int(
            self._session.scalar(
                select(func.count()).select_from(IngestionJobRecord).where(*criteria)
            )
            or 0
        )
        records = self._session.scalars(
            select(IngestionJobRecord)
            .where(*criteria)
            .order_by(IngestionJobRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_job(record) for record in records], total

    def queue_counts(self) -> dict[str, int]:
        rows = self._session.execute(
            select(IngestionJobRecord.status, func.count())
            .group_by(IngestionJobRecord.status)
            .order_by(IngestionJobRecord.status)
        ).all()
        return {str(status): int(count) for status, count in rows}

    def get_job(self, job_id: uuid.UUID) -> IngestionJob | None:
        record = self._session.get(IngestionJobRecord, job_id)
        return _job(record) if record is not None else None

    def claim_next(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> IngestionJob | None:
        record = self._session.scalar(
            select(IngestionJobRecord)
            .where(
                or_(
                    and_(
                        IngestionJobRecord.status.in_(("queued", "retry")),
                        IngestionJobRecord.next_attempt_at <= now,
                    ),
                    and_(
                        IngestionJobRecord.status == "running",
                        IngestionJobRecord.lease_expires_at < now,
                    ),
                ),
            )
            .order_by(IngestionJobRecord.next_attempt_at, IngestionJobRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.status = "running"
        record.stage = "preparing"
        record.progress = max(record.progress, 5)
        record.attempt += 1
        record.lease_owner = worker_id
        record.lease_expires_at = lease_until
        record.started_at = record.started_at or now
        self._session.flush()
        return _job(record)

    def renew_lease(self, job_id: uuid.UUID, *, worker_id: str, lease_until: datetime) -> bool:
        record = self._session.scalar(
            select(IngestionJobRecord).where(
                IngestionJobRecord.id == job_id,
                IngestionJobRecord.status == "running",
                IngestionJobRecord.lease_owner == worker_id,
                IngestionJobRecord.cancel_requested.is_(False),
            )
        )
        if record is None:
            return False
        record.lease_expires_at = lease_until
        return True

    def update_progress(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        stage: str,
        progress: int,
        message_key: str,
        params: dict[str, object] | None = None,
    ) -> bool:
        record = self._session.scalar(
            select(IngestionJobRecord).where(
                IngestionJobRecord.id == job_id,
                IngestionJobRecord.status == "running",
                IngestionJobRecord.lease_owner == worker_id,
                IngestionJobRecord.cancel_requested.is_(False),
            )
        )
        if record is None:
            return False
        record.stage = stage
        record.progress = min(99, max(record.progress, progress))
        self._session.add(
            IngestionJobLogRecord(
                job_id=job_id,
                level="info",
                message_key=message_key,
                params=params or {},
                created_at=datetime.now(UTC),
            )
        )
        return True

    def complete(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        volume_ids: tuple[uuid.UUID, ...],
    ) -> bool:
        record = self._session.scalar(
            select(IngestionJobRecord).where(
                IngestionJobRecord.id == job_id,
                IngestionJobRecord.status == "running",
                IngestionJobRecord.lease_owner == worker_id,
                IngestionJobRecord.cancel_requested.is_(False),
            )
        )
        if record is None:
            return False
        record.status = "completed"
        record.stage = "completed"
        record.progress = 100
        record.result_work_id = work_id
        record.result_edition_id = edition_id
        record.result_volume_ids = [str(value) for value in volume_ids]
        record.lease_owner = None
        record.lease_expires_at = None
        record.retryable = False
        record.error_code = None
        record.error_detail = None
        record.finished_at = datetime.now(UTC)
        self._session.add(
            IngestionJobLogRecord(
                job_id=job_id,
                level="info",
                message_key="import.completed",
                params={
                    "workId": str(work_id),
                    "editionId": str(edition_id),
                },
                created_at=record.finished_at,
            )
        )
        self._session.add(
            IngestionOutboxRecord(
                event_type="import.completed",
                aggregate_id=work_id,
                payload={
                    "jobId": str(job_id),
                    "workId": str(work_id),
                    "editionId": str(edition_id),
                    "volumeIds": [str(value) for value in volume_ids],
                },
                idempotency_key=f"import.completed:{job_id}",
                attempt=0,
                next_attempt_at=record.finished_at,
            )
        )
        return True

    def acknowledge_cancellation(self, job_id: uuid.UUID, *, worker_id: str) -> bool:
        record = self._session.scalar(
            select(IngestionJobRecord).where(
                IngestionJobRecord.id == job_id,
                IngestionJobRecord.status == "running",
                IngestionJobRecord.lease_owner == worker_id,
                IngestionJobRecord.cancel_requested.is_(True),
            )
        )
        if record is None:
            return False
        record.status = "cancelled"
        record.stage = "cancelled"
        record.progress = 100
        record.lease_owner = None
        record.lease_expires_at = None
        record.finished_at = datetime.now(UTC)
        record.retryable = True
        return True

    def fail(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        error_code: str,
        error_detail: str,
        retryable: bool,
        retry_at: datetime | None,
    ) -> bool:
        record = self._session.scalar(
            select(IngestionJobRecord).where(
                IngestionJobRecord.id == job_id,
                IngestionJobRecord.status == "running",
                IngestionJobRecord.lease_owner == worker_id,
                IngestionJobRecord.cancel_requested.is_(False),
            )
        )
        if record is None:
            return False
        record.status = "retry" if retryable and retry_at is not None else "failed"
        record.stage = "retry_wait" if record.status == "retry" else "failed"
        record.next_attempt_at = retry_at or record.next_attempt_at
        record.lease_owner = None
        record.lease_expires_at = None
        record.retryable = retryable
        record.error_code = error_code
        record.error_detail = error_detail[:4000]
        record.finished_at = None if record.status == "retry" else datetime.now(UTC)
        self._session.add(
            IngestionJobLogRecord(
                job_id=job_id,
                level="warning" if record.status == "retry" else "error",
                message_key=(
                    "import.retry_scheduled" if record.status == "retry" else "import.failed"
                ),
                params={"code": error_code},
                created_at=datetime.now(UTC),
            )
        )
        return True

    def cancel(self, job_id: uuid.UUID) -> bool:
        record = self._session.get(IngestionJobRecord, job_id)
        if record is None or record.status in {"completed", "cancelled", "failed"}:
            return False
        if record.status == "running":
            if record.stage == "publishing":
                return False
            record.cancel_requested = True
        else:
            record.status = "cancelled"
            record.stage = "cancelled"
            record.progress = 100
            record.lease_owner = None
            record.lease_expires_at = None
            record.finished_at = datetime.now(UTC)
            record.retryable = True
        self._session.flush()
        return True

    def delete_job(self, job_id: uuid.UUID) -> bool:
        record = self._session.get(IngestionJobRecord, job_id)
        if record is None or record.status not in {"completed", "failed", "cancelled"}:
            return False
        self._session.delete(record)
        return True

    def clear_finished(self) -> int:
        criteria = IngestionJobRecord.status.in_(("completed", "failed", "cancelled"))
        count = int(
            self._session.scalar(
                select(func.count()).select_from(IngestionJobRecord).where(criteria)
            )
            or 0
        )
        self._session.execute(delete(IngestionJobRecord).where(criteria))
        return count

    def retry(self, job_id: uuid.UUID, now: datetime) -> bool:
        record = self._session.get(IngestionJobRecord, job_id)
        if record is None or record.status not in {"failed", "cancelled"}:
            return False
        record.status = "queued"
        record.stage = "queued"
        record.progress = 0
        record.next_attempt_at = now
        record.lease_owner = None
        record.lease_expires_at = None
        record.cancel_requested = False
        record.finished_at = None
        record.error_code = None
        record.error_detail = None
        return True

    def list_logs(self, job_id: uuid.UUID, *, limit: int = 100) -> list[JobLog]:
        records = self._session.scalars(
            select(IngestionJobLogRecord)
            .where(IngestionJobLogRecord.job_id == job_id)
            .order_by(IngestionJobLogRecord.created_at.desc())
            .limit(limit)
        ).all()
        return [
            JobLog(
                id=record.id,
                job_id=record.job_id,
                level=record.level,
                message_key=record.message_key,
                params=record.params,
                created_at=record.created_at,
            )
            for record in records
        ]

    def get_policy(self) -> IngestionPolicy:
        record = self._session.scalar(
            select(IngestionPolicyRecord).where(IngestionPolicyRecord.name == "default").limit(1)
        )
        if record is None:
            raise RuntimeError("default ingestion policy is missing")
        return _policy(record)

    def update_policy(
        self,
        *,
        allowed_extensions: tuple[str, ...],
        ignore_patterns: tuple[str, ...],
        stability_check_enabled: bool,
        stability_check_seconds: int,
        auto_convert_to_epub: bool,
    ) -> IngestionPolicy:
        record = self._session.scalar(
            select(IngestionPolicyRecord).where(IngestionPolicyRecord.name == "default").limit(1)
        )
        if record is None:
            raise RuntimeError("default ingestion policy is missing")
        record.allowed_extensions = list(allowed_extensions)
        record.ignore_patterns = list(ignore_patterns)
        record.stability_check_enabled = stability_check_enabled
        record.stability_check_seconds = stability_check_seconds
        record.auto_convert_to_epub = auto_convert_to_epub
        self._session.flush()
        return _policy(record)

    def create_scan_run(
        self,
        *,
        trigger: str,
        monitor_folder_id: uuid.UUID | None,
        requested_by: uuid.UUID | None,
    ) -> ScanRun:
        if trigger in {"event", "periodic"}:
            existing = self._session.scalar(
                select(ScanRunRecord)
                .where(
                    ScanRunRecord.trigger == trigger,
                    ScanRunRecord.monitor_folder_id == monitor_folder_id,
                    ScanRunRecord.status.in_(("queued", "running")),
                )
                .order_by(ScanRunRecord.created_at)
                .limit(1)
            )
            if existing is not None:
                return _scan_run(existing)
        record = ScanRunRecord(
            trigger=trigger,
            status="queued",
            monitor_folder_id=monitor_folder_id,
            requested_by=requested_by,
        )
        self._session.add(record)
        self._session.flush()
        return _scan_run(record)

    def get_scan_run(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        record = self._session.get(ScanRunRecord, scan_run_id)
        return _scan_run(record) if record is not None else None

    def claim_scan_run(
        self,
        *,
        now: datetime,
        recovery_before: datetime,
    ) -> ScanRun | None:
        record = self._session.scalar(
            select(ScanRunRecord)
            .where(
                or_(
                    ScanRunRecord.status == "queued",
                    and_(
                        ScanRunRecord.status == "running",
                        ScanRunRecord.started_at < recovery_before,
                    ),
                )
            )
            .order_by(ScanRunRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.status = "running"
        record.started_at = now
        self._session.flush()
        return _scan_run(record)

    def observe_and_enqueue(
        self,
        *,
        monitor_folder_id: uuid.UUID,
        normalized_path: str,
        request: ImportRequest,
        seen_at: datetime,
    ) -> ImportResult | None:
        observation_id = self._session.scalar(
            insert(MonitorObservationRecord)
            .values(
                monitor_folder_id=monitor_folder_id,
                normalized_path=normalized_path,
                source_kind="file",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            )
            .on_conflict_do_nothing(index_elements=["monitor_folder_id", "normalized_path"])
            .returning(MonitorObservationRecord.id)
        )
        if observation_id is None:
            existing = self._session.scalar(
                select(MonitorObservationRecord)
                .where(
                    MonitorObservationRecord.monitor_folder_id == monitor_folder_id,
                    MonitorObservationRecord.normalized_path == normalized_path,
                )
                .with_for_update()
            )
            if existing is not None:
                existing.last_seen_at = seen_at
            return None
        result = self.enqueue(request)
        observation = self._session.get(MonitorObservationRecord, observation_id)
        if observation is None:
            raise RuntimeError("new monitor observation is missing")
        observation.import_job_id = result.job_id
        return result

    def complete_scan_run(
        self,
        scan_run_id: uuid.UUID,
        *,
        directories_scanned: int,
        files_scanned: int,
        candidates_found: int,
        queued: int,
        ignored: int,
        errors: tuple[dict[str, str], ...],
        finished_at: datetime,
    ) -> bool:
        record = self._session.scalar(
            select(ScanRunRecord).where(
                ScanRunRecord.id == scan_run_id,
                ScanRunRecord.status == "running",
            )
        )
        if record is None:
            return False
        record.status = "completed"
        record.directories_scanned = directories_scanned
        record.files_scanned = files_scanned
        record.candidates_found = candidates_found
        record.queued = queued
        record.ignored = ignored
        record.errors = list(errors)
        record.finished_at = finished_at
        return True

    def fail_scan_run(
        self,
        scan_run_id: uuid.UUID,
        *,
        errors: tuple[dict[str, str], ...],
        finished_at: datetime,
    ) -> bool:
        record = self._session.scalar(
            select(ScanRunRecord).where(
                ScanRunRecord.id == scan_run_id,
                ScanRunRecord.status == "running",
            )
        )
        if record is None:
            return False
        record.status = "failed"
        record.errors = list(errors)
        record.finished_at = finished_at
        return True

    def claim_outbox(
        self,
        *,
        now: datetime,
        lease_until: datetime,
    ) -> IngestionOutboxEvent | None:
        record = self._session.scalar(
            select(IngestionOutboxRecord)
            .where(
                IngestionOutboxRecord.published_at.is_(None),
                IngestionOutboxRecord.next_attempt_at <= now,
            )
            .order_by(IngestionOutboxRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.attempt += 1
        record.next_attempt_at = lease_until
        self._session.flush()
        return IngestionOutboxEvent(
            id=record.id,
            event_type=record.event_type,
            aggregate_id=record.aggregate_id,
            payload=record.payload,
            attempt=record.attempt,
        )

    def publish_outbox(self, event_id: uuid.UUID, *, published_at: datetime) -> bool:
        record = self._session.get(IngestionOutboxRecord, event_id)
        if record is None or record.published_at is not None:
            return False
        record.published_at = published_at
        record.error_detail = None
        return True

    def fail_outbox(
        self,
        event_id: uuid.UUID,
        *,
        error_detail: str,
        retry_at: datetime,
    ) -> bool:
        record = self._session.get(IngestionOutboxRecord, event_id)
        if record is None or record.published_at is not None:
            return False
        record.error_detail = error_detail[:4000]
        record.next_attempt_at = retry_at
        return True

    def list_folders(self) -> list[MonitorFolder]:
        records = self._session.scalars(
            select(MonitorFolderRecord).order_by(MonitorFolderRecord.path)
        ).all()
        return [_folder(record) for record in records]

    def get_folder(self, folder_id: uuid.UUID) -> MonitorFolder | None:
        record = self._session.get(MonitorFolderRecord, folder_id)
        return _folder(record) if record is not None else None

    def add_folder(
        self,
        *,
        path: str,
        recursive: bool,
        options: dict[str, object],
    ) -> MonitorFolder:
        record = MonitorFolderRecord(
            path=path,
            enabled=True,
            recursive=recursive,
            options=options,
        )
        self._session.add(record)
        self._session.flush()
        return _folder(record)

    def update_folder(
        self,
        folder_id: uuid.UUID,
        *,
        enabled: bool | None,
        recursive: bool | None,
        options: dict[str, object] | None,
        scanned_at: datetime | None,
    ) -> MonitorFolder | None:
        record = self._session.get(MonitorFolderRecord, folder_id)
        if record is None:
            return None
        if enabled is not None:
            record.enabled = enabled
        if recursive is not None:
            record.recursive = recursive
        if options is not None:
            record.options = options
        if scanned_at is not None:
            record.last_scan_at = scanned_at
        self._session.flush()
        return _folder(record)

    def delete_folder(self, folder_id: uuid.UUID) -> bool:
        record = self._session.get(MonitorFolderRecord, folder_id)
        if record is None:
            return False
        self._session.delete(record)
        return True


class IngestionSqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.ingestion: IngestionRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.ingestion = SqlIngestionRepository(self._session)
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        if self._session is None:
            return False
        try:
            if exc_type is not None or not self._committed:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None
        return False

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before commit")
        self._session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before rollback")
        self._session.rollback()


def ingestion_uow_factory(
    session_factory: sessionmaker[Session],
) -> Callable[[], IngestionSqlUnitOfWork]:
    return lambda: IngestionSqlUnitOfWork(session_factory)
