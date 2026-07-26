from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.metadata.contracts import (
    MetadataCandidate,
    MetadataJob,
    MetadataRepository,
    OrganizePolicy,
    ProviderView,
)
from appv2.modules.metadata.infrastructure.models import (
    MetadataCandidateRecord,
    MetadataJobRecord,
    OrganizeJobRecord,
    OrganizePolicyRecord,
    ProviderRecord,
)


def _provider(record: ProviderRecord) -> ProviderView:
    return ProviderView(
        id=record.id,
        slug=record.slug,
        name=record.name,
        enabled=record.enabled,
        priority=record.priority,
        config=record.config,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _job(record: MetadataJobRecord) -> MetadataJob:
    return MetadataJob(
        id=record.id,
        work_id=record.work_id,
        provider_id=record.provider_id,
        status=record.status,
        query=record.query,
        attempt=record.attempt,
        next_attempt_at=record.next_attempt_at,
        lease_expires_at=record.lease_expires_at,
        error_code=record.error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlMetadataRepository(MetadataRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_providers(self) -> list[ProviderView]:
        records = self._session.scalars(
            select(ProviderRecord).order_by(ProviderRecord.priority, ProviderRecord.name)
        ).all()
        return [_provider(record) for record in records]

    def get_provider(self, provider_id: uuid.UUID) -> ProviderView | None:
        record = self._session.get(ProviderRecord, provider_id)
        return _provider(record) if record is not None else None

    def add_provider(
        self,
        *,
        slug: str,
        name: str,
        enabled: bool,
        priority: int,
        config: dict[str, object],
    ) -> ProviderView:
        record = ProviderRecord(
            slug=slug,
            name=name,
            enabled=enabled,
            priority=priority,
            config=config,
        )
        self._session.add(record)
        self._session.flush()
        return _provider(record)

    def update_provider(
        self,
        provider_id: uuid.UUID,
        *,
        name: str | None,
        enabled: bool | None,
        priority: int | None,
        config: dict[str, object] | None,
    ) -> ProviderView | None:
        record = self._session.get(ProviderRecord, provider_id)
        if record is None:
            return None
        if name is not None:
            record.name = name
        if enabled is not None:
            record.enabled = enabled
        if priority is not None:
            record.priority = priority
        if config is not None:
            record.config = config
        self._session.flush()
        return _provider(record)

    def enqueue_job(
        self,
        *,
        work_id: uuid.UUID,
        provider_id: uuid.UUID | None,
        requested_by: uuid.UUID | None,
        query: str,
        idempotency_key: str,
        now: datetime,
    ) -> MetadataJob:
        statement = (
            insert(MetadataJobRecord)
            .values(
                work_id=work_id,
                provider_id=provider_id,
                requested_by=requested_by,
                status="queued",
                query=query,
                idempotency_key=idempotency_key,
                attempt=0,
                max_attempts=5,
                next_attempt_at=now,
            )
            .on_conflict_do_update(
                index_elements=["idempotency_key"],
                set_={"query": query},
            )
            .returning(MetadataJobRecord)
        )
        record = self._session.scalar(statement)
        if record is None:
            raise RuntimeError("metadata job upsert did not return a row")
        return _job(record)

    def list_jobs(
        self, *, offset: int, limit: int, status: str | None
    ) -> tuple[list[MetadataJob], int]:
        criteria = [MetadataJobRecord.status == status] if status else []
        total = int(
            self._session.scalar(
                select(func.count()).select_from(MetadataJobRecord).where(*criteria)
            )
            or 0
        )
        records = self._session.scalars(
            select(MetadataJobRecord)
            .where(*criteria)
            .order_by(MetadataJobRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_job(record) for record in records], total

    def queue_counts(self) -> dict[str, int]:
        rows = self._session.execute(
            select(MetadataJobRecord.status, func.count())
            .group_by(MetadataJobRecord.status)
            .order_by(MetadataJobRecord.status)
        ).all()
        return {str(status): int(count) for status, count in rows}

    def get_job(self, job_id: uuid.UUID) -> MetadataJob | None:
        record = self._session.get(MetadataJobRecord, job_id)
        return _job(record) if record is not None else None

    def list_candidates(self, job_id: uuid.UUID) -> list[MetadataCandidate]:
        records = self._session.scalars(
            select(MetadataCandidateRecord)
            .where(MetadataCandidateRecord.job_id == job_id)
            .order_by(MetadataCandidateRecord.confidence.desc())
        ).all()
        return [
            MetadataCandidate(
                provider_id=record.provider_id,
                external_id=record.external_id,
                title=record.title,
                author=record.author,
                confidence=float(record.confidence),
                cover_url=record.cover_url,
                raw_payload=record.raw_payload,
                id=record.id,
                job_id=record.job_id,
            )
            for record in records
        ]

    def get_candidate(self, job_id: uuid.UUID, candidate_id: uuid.UUID) -> MetadataCandidate | None:
        record = self._session.scalar(
            select(MetadataCandidateRecord).where(
                MetadataCandidateRecord.id == candidate_id,
                MetadataCandidateRecord.job_id == job_id,
            )
        )
        if record is None:
            return None
        return MetadataCandidate(
            provider_id=record.provider_id,
            external_id=record.external_id,
            title=record.title,
            author=record.author,
            confidence=float(record.confidence),
            cover_url=record.cover_url,
            raw_payload=record.raw_payload,
            id=record.id,
            job_id=record.job_id,
        )

    def retry_job(self, job_id: uuid.UUID, *, now: datetime) -> MetadataJob | None:
        record = self._session.get(MetadataJobRecord, job_id)
        if record is None or record.status == "running":
            return _job(record) if record is not None else None
        record.status = "queued"
        record.attempt = 0
        record.next_attempt_at = now
        record.lease_owner = None
        record.lease_expires_at = None
        record.error_code = None
        record.error_detail = None
        self._session.flush()
        return _job(record)

    def delete_job(self, job_id: uuid.UUID) -> str:
        status = self._session.scalar(
            select(MetadataJobRecord.status).where(MetadataJobRecord.id == job_id)
        )
        if status is None:
            return "missing"
        if status == "running":
            return "running"
        self._session.execute(delete(MetadataJobRecord).where(MetadataJobRecord.id == job_id))
        return "deleted"

    def claim_next(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> MetadataJob | None:
        record = self._session.scalar(
            select(MetadataJobRecord)
            .where(
                MetadataJobRecord.status.in_(("queued", "retry")),
                MetadataJobRecord.next_attempt_at <= now,
                (
                    MetadataJobRecord.lease_expires_at.is_(None)
                    | (MetadataJobRecord.lease_expires_at < now)
                ),
            )
            .order_by(MetadataJobRecord.next_attempt_at, MetadataJobRecord.created_at)
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

    def save_candidates(self, job_id: uuid.UUID, candidates: list[MetadataCandidate]) -> None:
        job = self._session.get(MetadataJobRecord, job_id)
        if job is None:
            raise RuntimeError("metadata job no longer exists")
        for candidate in candidates:
            self._session.execute(
                insert(MetadataCandidateRecord)
                .values(
                    job_id=job_id,
                    provider_id=candidate.provider_id,
                    external_id=candidate.external_id,
                    title=candidate.title,
                    author=candidate.author,
                    confidence=Decimal(str(candidate.confidence)),
                    cover_url=candidate.cover_url,
                    raw_payload=candidate.raw_payload,
                )
                .on_conflict_do_update(
                    constraint="uq_candidates_job_provider_external",
                    set_={
                        "title": candidate.title,
                        "author": candidate.author,
                        "confidence": Decimal(str(candidate.confidence)),
                        "cover_url": candidate.cover_url,
                        "raw_payload": candidate.raw_payload,
                    },
                )
            )
        job.status = "completed"
        job.lease_owner = None
        job.lease_expires_at = None
        job.error_code = None
        job.error_detail = None

    def fail_job(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> None:
        job = self._session.get(MetadataJobRecord, job_id)
        if job is None:
            raise RuntimeError("metadata job no longer exists")
        job.status = "retry" if retry_at is not None else "failed"
        job.next_attempt_at = retry_at or job.next_attempt_at
        job.lease_owner = None
        job.lease_expires_at = None
        job.error_code = error_code
        job.error_detail = error_detail[:4000]

    def get_organize_policy(self) -> OrganizePolicy:
        record = self._session.scalar(
            select(OrganizePolicyRecord).where(OrganizePolicyRecord.name == "default").limit(1)
        )
        if record is None:
            return OrganizePolicy(
                schedule_mode="MANUAL",
                interval_minutes=None,
                auto_run_on_new=False,
                provider_scope=(),
                overwrite_fields=(),
                rules={},
            )
        return OrganizePolicy(
            schedule_mode=record.schedule_mode,
            interval_minutes=record.interval_minutes,
            auto_run_on_new=record.auto_run_on_new,
            provider_scope=tuple(record.provider_scope),
            overwrite_fields=tuple(record.overwrite_fields),
            rules=record.rules,
        )

    def update_organize_policy(
        self,
        *,
        schedule_mode: str,
        interval_minutes: int | None,
        auto_run_on_new: bool,
        provider_scope: tuple[str, ...],
        overwrite_fields: tuple[str, ...],
        rules: dict[str, object],
    ) -> OrganizePolicy:
        record = self._session.scalar(
            select(OrganizePolicyRecord).where(OrganizePolicyRecord.name == "default").limit(1)
        )
        if record is None:
            record = OrganizePolicyRecord(name="default")
            self._session.add(record)
        record.schedule_mode = schedule_mode
        record.interval_minutes = interval_minutes
        record.auto_run_on_new = auto_run_on_new
        record.provider_scope = list(provider_scope)
        record.overwrite_fields = list(overwrite_fields)
        record.rules = rules
        self._session.flush()
        return self.get_organize_policy()

    def enqueue_organize_job(
        self,
        *,
        work_id: uuid.UUID,
        proposal: dict[str, object],
    ) -> bool:
        existing = self._session.scalar(
            select(OrganizeJobRecord.id)
            .where(
                OrganizeJobRecord.work_id == work_id,
                OrganizeJobRecord.status.in_(("pending", "approved", "running")),
            )
            .limit(1)
        )
        if existing is not None:
            return False
        self._session.add(
            OrganizeJobRecord(
                work_id=work_id,
                status="pending",
                proposal=proposal,
            )
        )
        return True


class MetadataSqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.metadata: MetadataRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.metadata = SqlMetadataRepository(self._session)
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


def metadata_uow_factory(
    session_factory: sessionmaker[Session],
) -> Callable[[], MetadataSqlUnitOfWork]:
    return lambda: MetadataSqlUnitOfWork(session_factory)
