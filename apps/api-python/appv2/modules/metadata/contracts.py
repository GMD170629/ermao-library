from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from appv2.platform.database.contracts import UnitOfWork


@dataclass(frozen=True, slots=True)
class MetadataCandidate:
    provider_id: uuid.UUID
    external_id: str
    title: str
    author: str | None
    confidence: float
    cover_url: str | None
    raw_payload: dict[str, object]
    id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class MetadataPatch:
    title: str | None = None
    author: str | None = None
    series: str | None = None
    summary: str | None = None
    cover_url: str | None = None
    extra: dict[str, object] | None = None


class MetadataProvider(Protocol):
    provider_id: str

    def search(self, query: str) -> list[MetadataCandidate]: ...


@dataclass(frozen=True, slots=True)
class ProviderView:
    id: uuid.UUID
    slug: str
    name: str
    enabled: bool
    priority: int
    config: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MetadataJob:
    id: uuid.UUID
    work_id: uuid.UUID
    provider_id: uuid.UUID | None
    status: str
    query: str
    attempt: int
    next_attempt_at: datetime
    lease_expires_at: datetime | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class MetadataRepository(Protocol):
    def list_providers(self) -> list[ProviderView]: ...

    def get_provider(self, provider_id: uuid.UUID) -> ProviderView | None: ...

    def add_provider(
        self,
        *,
        slug: str,
        name: str,
        enabled: bool,
        priority: int,
        config: dict[str, object],
    ) -> ProviderView: ...

    def update_provider(
        self,
        provider_id: uuid.UUID,
        *,
        name: str | None,
        enabled: bool | None,
        priority: int | None,
        config: dict[str, object] | None,
    ) -> ProviderView | None: ...

    def enqueue_job(
        self,
        *,
        work_id: uuid.UUID,
        provider_id: uuid.UUID | None,
        requested_by: uuid.UUID,
        query: str,
        idempotency_key: str,
        now: datetime,
    ) -> MetadataJob: ...

    def list_jobs(
        self, *, offset: int, limit: int, status: str | None
    ) -> tuple[list[MetadataJob], int]: ...

    def get_job(self, job_id: uuid.UUID) -> MetadataJob | None: ...

    def list_candidates(self, job_id: uuid.UUID) -> list[MetadataCandidate]: ...

    def get_candidate(
        self, job_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> MetadataCandidate | None: ...

    def retry_job(self, job_id: uuid.UUID, *, now: datetime) -> MetadataJob | None: ...

    def delete_job(self, job_id: uuid.UUID) -> str: ...

    def claim_next(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> MetadataJob | None: ...

    def save_candidates(self, job_id: uuid.UUID, candidates: list[MetadataCandidate]) -> None: ...

    def fail_job(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> None: ...


class MetadataUnitOfWork(UnitOfWork, Protocol):
    metadata: MetadataRepository


class ProviderRegistry(Protocol):
    def search_all(self, query: str, providers: list[ProviderView]) -> list[MetadataCandidate]: ...
