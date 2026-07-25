import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import Field
from starlette.responses import StreamingResponse

from appv2.modules.accounts.contracts import AccessScope, AccountView, CurrentAccount
from appv2.modules.operations.application import OperationsNotFound, OperationsService
from appv2.modules.operations.contracts import (
    BackupView,
    EventView,
    HealthStatus,
    SettingView,
)
from appv2.platform.http import AppProblem, CamelModel, Page


class HealthItem(CamelModel):
    name: str
    status: str
    checked_at: datetime
    detail: dict[str, object]

    @classmethod
    def from_view(cls, value: HealthStatus) -> "HealthItem":
        return cls.model_validate(value)


class HealthResponse(CamelModel):
    status: str
    version: str
    contributors: list[HealthItem]


class SettingsResponse(CamelModel):
    values: dict[str, dict[str, object]]
    updated_at: dict[str, datetime]

    @classmethod
    def from_views(cls, values: list[SettingView]) -> "SettingsResponse":
        return cls(
            values={value.key: value.value for value in values},
            updated_at={value.key: value.updated_at for value in values},
        )


class SettingsRequest(CamelModel):
    values: dict[str, dict[str, object]] = Field(default_factory=dict)


class EventResponse(CamelModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    kind: str
    severity: str
    message_key: str
    params: dict[str, object]
    trace_id: str | None
    created_at: datetime

    @classmethod
    def from_view(cls, value: EventView) -> "EventResponse":
        return cls.model_validate(value)


class BackupResponse(CamelModel):
    id: uuid.UUID
    status: str
    archive_name: str
    app_version: str
    postgres_major: int
    alembic_revision: str
    checksum: str | None
    size_bytes: int | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, value: BackupView) -> "BackupResponse":
        return cls.model_validate(value)


class RestoreAccepted(CamelModel):
    request_id: str
    status: str = "requested"


def create_router(
    service: OperationsService,
    current_account: CurrentAccount,
    app_version: str,
) -> APIRouter:
    router = APIRouter(prefix="/operations")
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

    def missing(error: OperationsNotFound) -> AppProblem:
        return AppProblem(
            status=404,
            code="OPERATIONS_RESOURCE_NOT_FOUND",
            title="Operations resource not found",
            message_key="not_found",
        )

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        contributors = service.health()
        aggregate = (
            "healthy" if all(value.status == "healthy" for value in contributors) else "degraded"
        )
        return HealthResponse(
            status=aggregate,
            version=app_version,
            contributors=[HealthItem.from_view(value) for value in contributors],
        )

    @router.get("/settings", response_model=SettingsResponse)
    def settings(actor: Actor) -> SettingsResponse:
        require(actor, AccessScope.OPERATIONS_READ)
        return SettingsResponse.from_views(service.list_settings())

    @router.put("/settings", response_model=SettingsResponse)
    def save_settings(payload: SettingsRequest, actor: Actor) -> SettingsResponse:
        require(actor, AccessScope.OPERATIONS_WRITE)
        return SettingsResponse.from_views(service.save_settings(payload.values, actor.id))

    @router.get("/events", response_model=Page[EventResponse])
    def events(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        kind: str | None = None,
    ) -> Page[EventResponse]:
        require(actor, AccessScope.OPERATIONS_READ)
        size = min(max(page_size, 1), 200)
        values, total = service.list_events(page=max(page, 1), page_size=size, kind=kind)
        return Page(
            items=[EventResponse.from_view(value) for value in values],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    @router.get("/backups", response_model=Page[BackupResponse])
    def backups(actor: Actor) -> Page[BackupResponse]:
        require(actor, AccessScope.OPERATIONS_READ)
        values = service.list_backups()
        return Page(
            items=[BackupResponse.from_view(value) for value in values],
            page=1,
            page_size=max(len(values), 1),
            total=len(values),
        )

    @router.post(
        "/backups",
        response_model=BackupResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def request_backup(actor: Actor) -> BackupResponse:
        require(actor, AccessScope.OPERATIONS_WRITE)
        return BackupResponse.from_view(service.request_backup(actor.id))

    @router.get("/backups/{backup_id}", response_model=BackupResponse)
    def backup(backup_id: uuid.UUID, actor: Actor) -> BackupResponse:
        require(actor, AccessScope.OPERATIONS_READ)
        try:
            value = service.get_backup(backup_id)
        except OperationsNotFound as error:
            raise missing(error) from error
        return BackupResponse.from_view(value)

    @router.get("/backups/{backup_id}/download")
    def download_backup(backup_id: uuid.UUID, actor: Actor) -> StreamingResponse:
        require(actor, AccessScope.OPERATIONS_READ)
        try:
            archive = service.download_backup(backup_id)
        except OperationsNotFound as error:
            raise missing(error) from error
        return StreamingResponse(
            archive.body,
            media_type="application/vnd.postgresql.custom-dump",
            headers={
                "Content-Length": str(archive.size_bytes),
                "Content-Disposition": f'attachment; filename="{archive.filename}"',
                "ETag": f'"{archive.checksum}"',
                "Cache-Control": "private, no-store",
            },
        )

    @router.post(
        "/backups/{backup_id}/restore",
        response_model=RestoreAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def restore(backup_id: uuid.UUID, actor: Actor) -> RestoreAccepted:
        require(actor, AccessScope.OPERATIONS_WRITE)
        try:
            request_id = service.request_restore(backup_id, actor.id)
        except OperationsNotFound as error:
            raise missing(error) from error
        return RestoreAccepted(request_id=request_id)

    @router.delete("/backups/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_backup(backup_id: uuid.UUID, actor: Actor) -> None:
        require(actor, AccessScope.OPERATIONS_WRITE)
        try:
            service.delete_backup(backup_id)
        except OperationsNotFound as error:
            raise missing(error) from error

    return router
