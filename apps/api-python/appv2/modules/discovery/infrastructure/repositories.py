from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.discovery.contracts import (
    DiscoveryRepository,
    DownloadJob,
    DownloadRequest,
    SearchResultView,
    SourceResult,
    SourceView,
)
from appv2.modules.discovery.infrastructure.models import (
    DownloadJobRecord,
    SearchResultRecord,
    SourceRecord,
)


def _source(record: SourceRecord) -> SourceView:
    return SourceView(
        id=record.id,
        name=record.name,
        kind=record.kind,
        base_url=record.base_url,
        enabled=record.enabled,
        config=record.config,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _result(record: SearchResultRecord) -> SearchResultView:
    return SearchResultView(
        id=record.id,
        source_id=record.source_id,
        external_id=record.external_id,
        title=record.title,
        author=record.author,
        download_url=record.download_url,
        info_url=record.info_url,
        payload=record.payload,
        state=record.state,
        created_at=record.created_at,
    )


def _job(record: DownloadJobRecord) -> DownloadJob:
    return DownloadJob(
        id=record.id,
        result_id=record.result_id,
        requested_by=record.requested_by,
        status=record.status,
        attempt=record.attempt,
        next_attempt_at=record.next_attempt_at,
        destination_path=record.destination_path,
        error_code=record.error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlDiscoveryRepository(DiscoveryRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_sources(self) -> list[SourceView]:
        records = self._session.scalars(select(SourceRecord).order_by(SourceRecord.name)).all()
        return [_source(record) for record in records]

    def get_source(self, source_id: uuid.UUID) -> SourceView | None:
        record = self._session.get(SourceRecord, source_id)
        return _source(record) if record is not None else None

    def add_source(
        self,
        *,
        name: str,
        kind: str,
        base_url: str,
        enabled: bool,
        config: dict[str, object],
    ) -> SourceView:
        record = SourceRecord(
            name=name,
            kind=kind,
            base_url=base_url,
            enabled=enabled,
            config=config,
        )
        self._session.add(record)
        self._session.flush()
        return _source(record)

    def update_source(
        self,
        source_id: uuid.UUID,
        *,
        name: str | None,
        base_url: str | None,
        enabled: bool | None,
        config: dict[str, object] | None,
    ) -> SourceView | None:
        record = self._session.get(SourceRecord, source_id)
        if record is None:
            return None
        if name is not None:
            record.name = name
        if base_url is not None:
            record.base_url = base_url
        if enabled is not None:
            record.enabled = enabled
        if config is not None:
            record.config = config
        self._session.flush()
        return _source(record)

    def delete_source(self, source_id: uuid.UUID) -> bool:
        record = self._session.get(SourceRecord, source_id)
        if record is None:
            return False
        self._session.delete(record)
        return True

    def save_results(
        self, source_id: uuid.UUID, results: list[SourceResult]
    ) -> list[SearchResultView]:
        saved: list[SearchResultView] = []
        for result in results:
            record = self._session.scalar(
                insert(SearchResultRecord)
                .values(
                    source_id=source_id,
                    external_id=result.external_id,
                    title=result.title,
                    author=result.author,
                    download_url=result.download_url,
                    info_url=result.info_url,
                    payload=result.payload,
                    state="new",
                )
                .on_conflict_do_update(
                    constraint="uq_search_results_source_external",
                    set_={
                        "title": result.title,
                        "author": result.author,
                        "download_url": result.download_url,
                        "info_url": result.info_url,
                        "payload": result.payload,
                    },
                )
                .returning(SearchResultRecord)
            )
            if record is not None:
                saved.append(_result(record))
        return saved

    def list_results(
        self, *, offset: int, limit: int, state: str | None
    ) -> tuple[list[SearchResultView], int]:
        criteria = [SearchResultRecord.state == state] if state else []
        total = int(
            self._session.scalar(
                select(func.count()).select_from(SearchResultRecord).where(*criteria)
            )
            or 0
        )
        records = self._session.scalars(
            select(SearchResultRecord)
            .where(*criteria)
            .order_by(SearchResultRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_result(record) for record in records], total

    def get_result(self, result_id: uuid.UUID) -> SearchResultView | None:
        record = self._session.get(SearchResultRecord, result_id)
        return _result(record) if record is not None else None

    def enqueue_download(self, request: DownloadRequest, *, now: datetime) -> DownloadJob:
        record = self._session.scalar(
            insert(DownloadJobRecord)
            .values(
                result_id=request.result_id,
                requested_by=request.requested_by,
                status="queued",
                idempotency_key=request.idempotency_key,
                attempt=0,
                max_attempts=5,
                next_attempt_at=now,
            )
            .on_conflict_do_update(
                index_elements=["idempotency_key"],
                set_={"result_id": request.result_id},
            )
            .returning(DownloadJobRecord)
        )
        if record is None:
            raise RuntimeError("download job upsert did not return a row")
        return _job(record)

    def list_downloads(
        self, *, offset: int, limit: int, status: str | None
    ) -> tuple[list[DownloadJob], int]:
        criteria = [DownloadJobRecord.status == status] if status else []
        total = int(
            self._session.scalar(
                select(func.count()).select_from(DownloadJobRecord).where(*criteria)
            )
            or 0
        )
        records = self._session.scalars(
            select(DownloadJobRecord)
            .where(*criteria)
            .order_by(DownloadJobRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_job(record) for record in records], total

    def claim_download(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> tuple[DownloadJob, SearchResultView] | None:
        record = self._session.scalar(
            select(DownloadJobRecord)
            .where(
                DownloadJobRecord.status.in_(("queued", "retry")),
                DownloadJobRecord.next_attempt_at <= now,
                (
                    DownloadJobRecord.lease_expires_at.is_(None)
                    | (DownloadJobRecord.lease_expires_at < now)
                ),
            )
            .order_by(DownloadJobRecord.next_attempt_at, DownloadJobRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        result = self._session.get(SearchResultRecord, record.result_id)
        if result is None:
            raise RuntimeError("download result no longer exists")
        record.status = "running"
        record.attempt += 1
        record.lease_owner = worker_id
        record.lease_expires_at = lease_until
        self._session.flush()
        return _job(record), _result(result)

    def complete_download(self, job_id: uuid.UUID, destination_path: str) -> None:
        record = self._required_job(job_id)
        record.status = "completed"
        record.destination_path = destination_path
        record.lease_owner = None
        record.lease_expires_at = None
        record.error_code = None
        record.error_detail = None

    def fail_download(
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

    def _required_job(self, job_id: uuid.UUID) -> DownloadJobRecord:
        record = self._session.get(DownloadJobRecord, job_id)
        if record is None:
            raise RuntimeError("download job no longer exists")
        return record


class DiscoverySqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.discovery: DiscoveryRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.discovery = SqlDiscoveryRepository(self._session)
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


def discovery_uow_factory(
    session_factory: sessionmaker[Session],
) -> Callable[[], DiscoverySqlUnitOfWork]:
    return lambda: DiscoverySqlUnitOfWork(session_factory)
