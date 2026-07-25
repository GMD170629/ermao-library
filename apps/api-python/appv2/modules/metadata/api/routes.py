import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import Field

from appv2.modules.accounts.contracts import AccessScope, AccountView, CurrentAccount
from appv2.modules.metadata.application import (
    MetadataConflict,
    MetadataNotFound,
    MetadataService,
)
from appv2.modules.metadata.contracts import (
    MetadataCandidate,
    MetadataJob,
    MetadataPatch,
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
    provider_id: uuid.UUID | None
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
    provider_id: uuid.UUID | None = None
    query: str = Field(min_length=1, max_length=1000)


class CandidateResponse(CamelModel):
    id: uuid.UUID
    job_id: uuid.UUID
    provider_id: uuid.UUID
    external_id: str
    title: str
    author: str | None
    confidence: float
    cover_url: str | None
    raw_payload: dict[str, object]

    @classmethod
    def from_view(cls, value: MetadataCandidate) -> "CandidateResponse":
        if value.id is None or value.job_id is None:
            raise RuntimeError("persisted metadata candidate has no identity")
        return cls.model_validate(value)


MetadataField = Literal[
    "coverUrl",
    "title",
    "author",
    "publisher",
    "description",
    "tags",
    "seriesName",
    "seriesIndex",
    "publishedYear",
]
MetadataJobStatus = Literal[
    "queued",
    "running",
    "retry",
    "completed",
    "failed",
    "cancelled",
]


class ApplyCandidateRequest(CamelModel):
    fields: list[MetadataField] = Field(min_length=1)


def _candidate_patch(
    candidate: MetadataCandidate,
    fields: list[MetadataField],
) -> MetadataPatch:
    selected = set(fields)
    raw = candidate.raw_payload
    extra: dict[str, object] = {}
    for key in ("publisher", "tags", "seriesName", "seriesIndex", "publishedYear"):
        if key in selected and key in raw:
            extra[key] = raw[key]
    description = raw.get("description")
    series = raw.get("seriesName")
    return MetadataPatch(
        title=candidate.title if "title" in selected else None,
        author=candidate.author if "author" in selected else None,
        series=series if isinstance(series, str) and "seriesName" in selected else None,
        summary=(
            description if isinstance(description, str) and "description" in selected else None
        ),
        cover_url=candidate.cover_url if "coverUrl" in selected else None,
        extra=extra,
    )


def create_router(service: MetadataService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/metadata")

    def authorized(
        actor: Annotated[AccountView, Depends(current_account)],
    ) -> AccountView:
        if AccessScope.METADATA_WRITE not in actor.scopes:
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
                params={"scope": AccessScope.METADATA_WRITE.value},
            )
        return actor

    Actor = Annotated[AccountView, Depends(authorized)]

    def missing(error: MetadataNotFound) -> AppProblem:
        return AppProblem(
            status=404,
            code="METADATA_RESOURCE_NOT_FOUND",
            title="Metadata resource not found",
            message_key="not_found",
        )

    def conflict(error: MetadataConflict) -> AppProblem:
        return AppProblem(
            status=409,
            code="METADATA_JOB_RUNNING",
            title="Metadata job is running",
            message_key="conflict",
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
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        job_status: Annotated[MetadataJobStatus | None, Query(alias="status")] = None,
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
        try:
            return MetadataJobResponse.from_view(
                service.enqueue(
                    work_id=payload.work_id,
                    provider_id=payload.provider_id,
                    requested_by=actor.id,
                    query=payload.query,
                    idempotency_key=idempotency_key,
                )
            )
        except MetadataNotFound as error:
            raise missing(error) from error

    @router.get("/jobs/{job_id}", response_model=MetadataJobResponse)
    def job(job_id: uuid.UUID, actor: Actor) -> MetadataJobResponse:
        del actor
        try:
            return MetadataJobResponse.from_view(service.get_job(job_id))
        except MetadataNotFound as error:
            raise missing(error) from error

    @router.post(
        "/jobs/{job_id}/retry",
        response_model=MetadataJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_job(job_id: uuid.UUID, actor: Actor) -> MetadataJobResponse:
        del actor
        try:
            return MetadataJobResponse.from_view(service.retry_job(job_id))
        except MetadataNotFound as error:
            raise missing(error) from error
        except MetadataConflict as error:
            raise conflict(error) from error

    @router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_job(job_id: uuid.UUID, actor: Actor) -> Response:
        del actor
        try:
            service.delete_job(job_id)
        except MetadataNotFound as error:
            raise missing(error) from error
        except MetadataConflict as error:
            raise conflict(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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

    @router.post(
        "/jobs/{job_id}/candidates/{candidate_id}/apply",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def apply_candidate(
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        payload: ApplyCandidateRequest,
        actor: Actor,
    ) -> Response:
        del actor
        try:
            candidates = service.list_candidates(job_id)
            candidate = next(
                (value for value in candidates if value.id == candidate_id),
                None,
            )
            if candidate is None:
                raise MetadataNotFound
            service.apply_candidate(
                job_id=job_id,
                candidate_id=candidate_id,
                patch=_candidate_patch(candidate, payload.fields),
            )
        except MetadataNotFound as error:
            raise missing(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
