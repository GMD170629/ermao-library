import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import Field

from appv2.modules.accounts.contracts import AccessScope, AccountView, CurrentAccount
from appv2.modules.discovery.application import DiscoveryNotFound, DiscoveryService
from appv2.modules.discovery.contracts import DownloadJob, SearchResultView, SourceView
from appv2.platform.http import AppProblem, CamelModel, Page


class SourceResponse(CamelModel):
    id: uuid.UUID
    name: str
    kind: str
    base_url: str
    enabled: bool
    config: dict[str, object]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, value: SourceView) -> "SourceResponse":
        return cls.model_validate(value)


class SourceRequest(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["json-http"] = "json-http"
    base_url: str
    enabled: bool = True
    config: dict[str, object] = Field(default_factory=dict)


class SourceUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = None
    enabled: bool | None = None
    config: dict[str, object] | None = None


class SearchRequest(CamelModel):
    query: str = Field(min_length=1, max_length=1000)


class ResultResponse(CamelModel):
    id: uuid.UUID
    source_id: uuid.UUID
    external_id: str
    title: str
    author: str | None
    download_url: str | None
    info_url: str | None
    payload: dict[str, object]
    state: str
    created_at: datetime

    @classmethod
    def from_view(cls, value: SearchResultView) -> "ResultResponse":
        return cls.model_validate(value)


class DownloadResponse(CamelModel):
    id: uuid.UUID
    result_id: uuid.UUID
    status: str
    attempt: int
    next_attempt_at: datetime
    destination_path: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, value: DownloadJob) -> "DownloadResponse":
        return cls.model_validate(value)


def create_router(service: DiscoveryService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/discovery")

    def authorized(
        actor: Annotated[AccountView, Depends(current_account)],
    ) -> AccountView:
        if AccessScope.DISCOVERY_WRITE not in actor.scopes:
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
                params={"scope": AccessScope.DISCOVERY_WRITE.value},
            )
        return actor

    Actor = Annotated[AccountView, Depends(authorized)]

    def missing(error: DiscoveryNotFound) -> AppProblem:
        return AppProblem(
            status=404,
            code="DISCOVERY_RESOURCE_NOT_FOUND",
            title="Discovery resource not found",
            message_key="not_found",
        )

    @router.get("/sources", response_model=Page[SourceResponse])
    def sources(actor: Actor) -> Page[SourceResponse]:
        del actor
        values = service.list_sources()
        return Page(
            items=[SourceResponse.from_view(value) for value in values],
            page=1,
            page_size=max(len(values), 1),
            total=len(values),
        )

    @router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
    def add_source(payload: SourceRequest, actor: Actor) -> SourceResponse:
        del actor
        return SourceResponse.from_view(
            service.add_source(
                name=payload.name,
                kind=payload.kind,
                base_url=payload.base_url,
                enabled=payload.enabled,
                config=payload.config,
            )
        )

    @router.patch("/sources/{source_id}", response_model=SourceResponse)
    def update_source(source_id: uuid.UUID, payload: SourceUpdate, actor: Actor) -> SourceResponse:
        del actor
        try:
            value = service.update_source(
                source_id,
                name=payload.name,
                base_url=payload.base_url,
                enabled=payload.enabled,
                config=payload.config,
            )
        except DiscoveryNotFound as error:
            raise missing(error) from error
        return SourceResponse.from_view(value)

    @router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_source(source_id: uuid.UUID, actor: Actor) -> None:
        del actor
        try:
            service.delete_source(source_id)
        except DiscoveryNotFound as error:
            raise missing(error) from error

    @router.post("/sources/{source_id}/search", response_model=Page[ResultResponse])
    def search(source_id: uuid.UUID, payload: SearchRequest, actor: Actor) -> Page[ResultResponse]:
        del actor
        try:
            values = service.search(source_id, payload.query)
        except DiscoveryNotFound as error:
            raise missing(error) from error
        return Page(
            items=[ResultResponse.from_view(value) for value in values],
            page=1,
            page_size=max(len(values), 1),
            total=len(values),
        )

    @router.get("/results", response_model=Page[ResultResponse])
    def results(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        state: str | None = None,
    ) -> Page[ResultResponse]:
        del actor
        size = min(max(page_size, 1), 200)
        values, total = service.list_results(page=max(page, 1), page_size=size, state=state)
        return Page(
            items=[ResultResponse.from_view(value) for value in values],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    @router.post(
        "/downloads/{result_id}",
        response_model=DownloadResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue_download(
        result_id: uuid.UUID,
        actor: Actor,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> DownloadResponse:
        try:
            value = service.enqueue_download(
                result_id=result_id,
                requested_by=actor.id,
                idempotency_key=idempotency_key,
            )
        except DiscoveryNotFound as error:
            raise missing(error) from error
        return DownloadResponse.from_view(value)

    @router.get("/downloads", response_model=Page[DownloadResponse])
    def downloads(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        job_status: Annotated[str | None, Query(alias="status")] = None,
    ) -> Page[DownloadResponse]:
        del actor
        size = min(max(page_size, 1), 200)
        values, total = service.list_downloads(page=max(page, 1), page_size=size, status=job_status)
        return Page(
            items=[DownloadResponse.from_view(value) for value in values],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    return router
