import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from appv2.modules.accounts.contracts import AccessScope, AccountView, CurrentAccount
from appv2.modules.reporting.application import ReportingService
from appv2.modules.reporting.contracts import LibraryWorkProjection
from appv2.platform.http import AppProblem, CamelModel, Page


class LibraryWorkResponse(CamelModel):
    id: uuid.UUID
    title: str
    author: str | None
    media_type: str
    status: str
    cover_url: str | None
    summary: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_projection(cls, work: LibraryWorkProjection) -> "LibraryWorkResponse":
        return cls(
            id=work.id,
            title=work.title,
            author=work.author,
            media_type=work.media_type,
            status=work.status,
            cover_url=(f"/api/v2/catalog/works/{work.id}/cover" if work.cover_key else None),
            summary=work.summary,
            metadata=work.metadata,
            created_at=work.created_at,
            updated_at=work.updated_at,
        )


class FilterFieldResponse(CamelModel):
    key: str
    label: str
    group: str
    type: Literal["text", "select", "number", "date", "boolean"]
    operators: list[str]
    options: list[dict[str, object]] = Field(default_factory=list)
    allow_custom: bool = False
    unit: str | None = None


class LibraryFilterSchemaResponse(CamelModel):
    fields: list[FilterFieldResponse]
    max_conditions: int


class DashboardResponse(CamelModel):
    work_count: int
    edition_count: int
    active_readers: int
    queued_jobs: int
    continue_item: dict[str, object] | None
    recent_reading: list[dict[str, object]]
    recent_items: list[dict[str, object]]


class ManagementResponse(CamelModel):
    users: int
    works: int
    files: int
    queued_imports: int
    queued_downloads: int
    queued_deliveries: int
    failed_jobs: int


def create_router(service: ReportingService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/reporting")
    Actor = Annotated[AccountView, Depends(current_account)]

    def require(actor: AccountView, scope: AccessScope) -> None:
        if scope not in actor.scopes:
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
                params={"scope": scope.value},
            )

    @router.get("/library", response_model=Page[LibraryWorkResponse])
    def library(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        query: str | None = None,
        media_type: Annotated[str | None, Query(alias="mediaType")] = None,
        series_name: Annotated[str | None, Query(alias="seriesName")] = None,
        reading_status: Annotated[str | None, Query(alias="readingStatus")] = None,
        filters: str | None = None,
        sort: Literal[
            "recent_read",
            "recent_import",
            "title",
            "author",
            "publisher",
            "series",
        ] = "recent_read",
        sort_direction: Annotated[Literal["asc", "desc"], Query(alias="sortDirection")] = "desc",
    ) -> Page[LibraryWorkResponse]:
        require(actor, AccessScope.CATALOG_READ)
        try:
            items, total = service.library(
                actor.id,
                page=page,
                page_size=page_size,
                query=query,
                media_type=media_type,
                series_name=series_name,
                reading_status=reading_status,
                sort=sort,
                sort_direction=sort_direction,
                filters=filters,
            )
        except ValueError as error:
            raise AppProblem(
                status=422,
                code="INVALID_LIBRARY_FILTER",
                title="Invalid library filter",
                message_key="invalid_request",
            ) from error
        return Page(
            items=[LibraryWorkResponse.from_projection(item) for item in items],
            page=max(page, 1),
            page_size=min(max(page_size, 1), 200),
            total=total,
        )

    @router.get("/library/filter-schema", response_model=LibraryFilterSchemaResponse)
    def library_filter_schema(actor: Actor) -> LibraryFilterSchemaResponse:
        require(actor, AccessScope.CATALOG_READ)
        projection = service.library_filter_schema(actor.id)
        return LibraryFilterSchemaResponse(
            fields=[FilterFieldResponse.model_validate(field) for field in projection.fields],
            max_conditions=projection.max_conditions,
        )

    @router.get("/dashboard", response_model=DashboardResponse)
    def dashboard(actor: Actor) -> DashboardResponse:
        require(actor, AccessScope.CATALOG_READ)
        projection = service.dashboard(actor.id)
        return DashboardResponse(
            work_count=projection.work_count,
            edition_count=projection.edition_count,
            active_readers=projection.active_readers,
            queued_jobs=projection.queued_jobs,
            continue_item=projection.continue_item,
            recent_reading=list(projection.recent_reading),
            recent_items=list(projection.recent_items),
        )

    @router.get("/management", response_model=ManagementResponse)
    def management(actor: Actor) -> ManagementResponse:
        require(actor, AccessScope.OPERATIONS_READ)
        return ManagementResponse.model_validate(service.management())

    return router
