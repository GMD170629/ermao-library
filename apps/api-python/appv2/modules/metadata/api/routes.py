import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from pydantic import Field

from appv2.modules.accounts.contracts import AccountView, CurrentAccount
from appv2.modules.metadata.application import MetadataNotFound, MetadataService
from appv2.modules.metadata.contracts import (
    MetadataCandidate,
    MetadataJob,
    ProviderView,
)
from appv2.platform.http import AppProblem, CamelModel, Page


class ProviderResponse(CamelModel):
    id: uuid.UUID
    slug: str
    name: str
    enabled: bool
    priority: int
    config: dict[str, object]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, value: ProviderView) -> "ProviderResponse":
        return cls.model_validate(value)


class ProviderRequest(CamelModel):
    slug: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    config: dict[str, object] = Field(default_factory=dict)


class ProviderUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    config: dict[str, object] | None = None


class MetadataJobResponse(CamelModel):
    id: uuid.UUID
    work_id: uuid.UUID
    status: str
    query: str
    attempt: int
    next_attempt_at: datetime
    lease_expires_at: datetime | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, value: MetadataJob) -> "MetadataJobResponse":
        return cls.model_validate(value)


class MetadataJobRequest(CamelModel):
    work_id: uuid.UUID
    query: str = Field(min_length=1, max_length=1000)


class CandidateResponse(CamelModel):
    provider_id: uuid.UUID
    external_id: str
    title: str
    author: str | None
    confidence: float
    cover_url: str | None
    raw_payload: dict[str, object]

    @classmethod
    def from_view(cls, value: MetadataCandidate) -> "CandidateResponse":
        return cls.model_validate(value)


def create_router(service: MetadataService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/metadata")
    Actor = Annotated[AccountView, Depends(current_account)]

    def missing(error: MetadataNotFound) -> AppProblem:
        return AppProblem(
            status=404,
            code="METADATA_RESOURCE_NOT_FOUND",
            title="Metadata resource not found",
            message_key="not_found",
        )

    @router.get("/providers", response_model=Page[ProviderResponse])
    def providers(actor: Actor) -> Page[ProviderResponse]:
        del actor
        values = service.list_providers()
        return Page(
            items=[ProviderResponse.from_view(value) for value in values],
            page=1,
            page_size=max(len(values), 1),
            total=len(values),
        )

    @router.post(
        "/providers",
        response_model=ProviderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_provider(payload: ProviderRequest, actor: Actor) -> ProviderResponse:
        del actor
        return ProviderResponse.from_view(
            service.add_provider(
                slug=payload.slug,
                name=payload.name,
                enabled=payload.enabled,
                priority=payload.priority,
                config=payload.config,
            )
        )

    @router.patch("/providers/{provider_id}", response_model=ProviderResponse)
    def update_provider(
        provider_id: uuid.UUID, payload: ProviderUpdate, actor: Actor
    ) -> ProviderResponse:
        del actor
        try:
            value = service.update_provider(
                provider_id,
                name=payload.name,
                enabled=payload.enabled,
                priority=payload.priority,
                config=payload.config,
            )
        except MetadataNotFound as error:
            raise missing(error) from error
        return ProviderResponse.from_view(value)

    @router.get("/jobs", response_model=Page[MetadataJobResponse])
    def jobs(
        actor: Actor,
        page: int = 1,
        page_size: int = 24,
        job_status: str | None = None,
    ) -> Page[MetadataJobResponse]:
        del actor
        size = min(max(page_size, 1), 200)
        values, total = service.list_jobs(page=max(page, 1), page_size=size, status=job_status)
        return Page(
            items=[MetadataJobResponse.from_view(value) for value in values],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    @router.post(
        "/jobs",
        response_model=MetadataJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue(
        payload: MetadataJobRequest,
        actor: Actor,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> MetadataJobResponse:
        return MetadataJobResponse.from_view(
            service.enqueue(
                work_id=payload.work_id,
                requested_by=actor.id,
                query=payload.query,
                idempotency_key=idempotency_key,
            )
        )

    @router.get("/jobs/{job_id}/candidates", response_model=Page[CandidateResponse])
    def candidates(job_id: uuid.UUID, actor: Actor) -> Page[CandidateResponse]:
        del actor
        try:
            values = service.list_candidates(job_id)
        except MetadataNotFound as error:
            raise missing(error) from error
        return Page(
            items=[CandidateResponse.from_view(value) for value in values],
            page=1,
            page_size=max(len(values), 1),
            total=len(values),
        )

    return router
