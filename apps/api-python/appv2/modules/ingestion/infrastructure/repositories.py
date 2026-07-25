from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.ingestion.contracts import (
    ImportRequest,
    ImportResult,
    IngestionJob,
    IngestionRepository,
    MonitorFolder,
)
from appv2.modules.ingestion.infrastructure.models import (
    IngestionJobRecord,
    MonitorFolderRecord,
)


def _job(record: IngestionJobRecord) -> IngestionJob:
    return IngestionJob(
        id=record.id,
        kind=record.kind,
        status=record.status,
        source_path=record.source_path,
        attempt=record.attempt,
        next_attempt_at=record.next_attempt_at,
        lease_expires_at=record.lease_expires_at,
        result_id=record.result_id,
        error_code=record.error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _folder(record: MonitorFolderRecord) -> MonitorFolder:
    return MonitorFolder(
        id=record.id,
        path=record.path,
        enabled=record.enabled,
        recursive=record.recursive,
        move_source=record.move_source,
        options=record.options,
        last_scan_at=record.last_scan_at,
        created_at=record.created_at,
    )


class SqlIngestionRepository(IngestionRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, request: ImportRequest, *, kind: str = "import") -> ImportResult:
        statement = (
            insert(IngestionJobRecord)
            .values(
                kind=kind,
                status="queued",
                source_path=request.source_path,
                requested_by=request.requested_by,
                idempotency_key=request.idempotency_key,
                options={"moveSource": request.move_source},
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
            edition_id=record.result_id,
            duplicate=duplicate,
        )

    def list_jobs(
        self, *, offset: int, limit: int, status: str | None
    ) -> tuple[list[IngestionJob], int]:
        criteria = [IngestionJobRecord.status == status] if status else []
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

    def get_job(self, job_id: uuid.UUID) -> IngestionJob | None:
        record = self._session.get(IngestionJobRecord, job_id)
        return _job(record) if record is not None else None

    def claim_next(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> IngestionJob | None:
        record = self._session.scalar(
            select(IngestionJobRecord)
            .where(
                IngestionJobRecord.status.in_(("queued", "retry")),
                IngestionJobRecord.next_attempt_at <= now,
                (
                    IngestionJobRecord.lease_expires_at.is_(None)
                    | (IngestionJobRecord.lease_expires_at < now)
                ),
            )
            .order_by(IngestionJobRecord.next_attempt_at, IngestionJobRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.status = "running"
        record.attempt += 1
        record.lease_owner = worker_id
        record.lease_expires_at = lease_until
        self._session.flush()
        return _job(record)

    def complete(self, job_id: uuid.UUID, edition_id: uuid.UUID) -> None:
        record = self._required_job(job_id)
        record.status = "completed"
        record.result_id = edition_id
        record.lease_owner = None
        record.lease_expires_at = None
        record.error_code = None
        record.error_detail = None

    def fail(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> None:
        record = self._required_job(job_id)
        record.status = "retry" if retry_at is not None else "failed"
        record.next_attempt_at = retry_at or record.next_attempt_at
        record.lease_owner = None
        record.lease_expires_at = None
        record.error_code = error_code
        record.error_detail = error_detail[:4000]

    def cancel(self, job_id: uuid.UUID) -> bool:
        record = self._session.get(IngestionJobRecord, job_id)
        if record is None or record.status in {"completed", "cancelled"}:
            return False
        record.status = "cancelled"
        record.lease_owner = None
        record.lease_expires_at = None
        return True

    def retry(self, job_id: uuid.UUID, now: datetime) -> bool:
        record = self._session.get(IngestionJobRecord, job_id)
        if record is None or record.status not in {"failed", "cancelled"}:
            return False
        record.status = "queued"
        record.next_attempt_at = now
        record.lease_owner = None
        record.lease_expires_at = None
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
        move_source: bool,
        options: dict[str, object],
    ) -> MonitorFolder:
        record = MonitorFolderRecord(
            path=path,
            enabled=True,
            recursive=recursive,
            move_source=move_source,
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
        move_source: bool | None,
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
        if move_source is not None:
            record.move_source = move_source
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

    def _required_job(self, job_id: uuid.UUID) -> IngestionJobRecord:
        record = self._session.get(IngestionJobRecord, job_id)
        if record is None:
            raise RuntimeError("ingestion job no longer exists")
        return record


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
