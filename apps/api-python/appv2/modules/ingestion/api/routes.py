import uuid
from datetime import datetime
from typing import Annotated, Self

from fastapi import APIRouter, Depends, File, Header, UploadFile, status
from pydantic import Field

from appv2.modules.accounts.contracts import AccountView, CurrentAccount
from appv2.modules.ingestion.application import IngestionNotFound, IngestionService
from appv2.modules.ingestion.contracts import ImportResult, IngestionJob, MonitorFolder
from appv2.platform.http import AppProblem, CamelModel, Page


class JobResponse(CamelModel):
    id: uuid.UUID
    kind: str
    status: str
    source_path: str
    attempt: int
    next_attempt_at: datetime
    lease_expires_at: datetime | None
    result_id: uuid.UUID | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, job: IngestionJob) -> Self:
        return cls.model_validate(job)


class EnqueueRequest(CamelModel):
    source_path: str
    move_source: bool = False


class JobAccepted(CamelModel):
    id: uuid.UUID
    status: str
    duplicate: bool
    result_id: uuid.UUID | None

    @classmethod
    def from_result(cls, result: ImportResult) -> Self:
        return cls(
            id=result.job_id,
            status=result.status,
            duplicate=result.duplicate,
            result_id=result.edition_id,
        )


class FolderRequest(CamelModel):
    path: str
    recursive: bool = True
    move_source: bool = False
    options: dict[str, object] = Field(default_factory=dict)


class FolderUpdate(CamelModel):
    enabled: bool | None = None
    recursive: bool | None = None
    move_source: bool | None = None
    options: dict[str, object] | None = None


class FolderResponse(CamelModel):
    id: uuid.UUID
    path: str
    enabled: bool
    recursive: bool
    move_source: bool
    options: dict[str, object]
    last_scan_at: datetime | None
    created_at: datetime

    @classmethod
    def from_view(cls, folder: MonitorFolder) -> Self:
        return cls.model_validate(folder)


def create_router(service: IngestionService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/ingestion")
    Actor = Annotated[AccountView, Depends(current_account)]

    def missing(error: IngestionNotFound) -> AppProblem:
        return AppProblem(
            status=404,
            code="INGESTION_RESOURCE_NOT_FOUND",
            title="Ingestion resource not found",
            message_key="not_found",
        )

    @router.get("/imports", response_model=Page[JobResponse])
    def imports(
        actor: Actor,
        page: int = 1,
        page_size: int = 24,
        job_status: str | None = None,
    ) -> Page[JobResponse]:
        del actor
        size = min(max(page_size, 1), 200)
        items, total = service.list_jobs(page=max(page, 1), page_size=size, status=job_status)
        return Page(
            items=[JobResponse.from_view(item) for item in items],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    @router.post("/imports", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
    def enqueue(
        payload: EnqueueRequest,
        actor: Actor,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JobAccepted:
        return JobAccepted.from_result(
            service.enqueue(
                source_path=payload.source_path,
                requested_by=actor.id,
                idempotency_key=idempotency_key,
                move_source=payload.move_source,
            )
        )

    @router.post(
        "/imports/upload",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def upload(
        actor: Actor,
        file: Annotated[UploadFile, File()],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JobAccepted:
        return JobAccepted.from_result(
            service.upload(
                name=file.filename or "upload",
                stream=file.file,
                requested_by=actor.id,
                idempotency_key=idempotency_key,
            )
        )

    @router.post("/imports/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
    def retry(job_id: uuid.UUID, actor: Actor) -> JobAccepted:
        del actor
        try:
            service.retry(job_id)
        except IngestionNotFound as error:
            raise missing(error) from error
        return JobAccepted(id=job_id, status="queued", duplicate=False, result_id=None)

    @router.delete("/imports/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    def cancel(job_id: uuid.UUID, actor: Actor) -> None:
        del actor
        try:
            service.cancel(job_id)
        except IngestionNotFound as error:
            raise missing(error) from error

    @router.get("/folders", response_model=Page[FolderResponse])
    def folders(actor: Actor) -> Page[FolderResponse]:
        del actor
        values = service.list_folders()
        return Page(
            items=[FolderResponse.from_view(value) for value in values],
            page=1,
            page_size=max(len(values), 1),
            total=len(values),
        )

    @router.post("/folders", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
    def add_folder(payload: FolderRequest, actor: Actor) -> FolderResponse:
        del actor
        return FolderResponse.from_view(
            service.add_folder(
                path=payload.path,
                recursive=payload.recursive,
                move_source=payload.move_source,
                options=payload.options,
            )
        )

    @router.patch("/folders/{folder_id}", response_model=FolderResponse)
    def update_folder(folder_id: uuid.UUID, payload: FolderUpdate, actor: Actor) -> FolderResponse:
        del actor
        try:
            folder = service.update_folder(
                folder_id,
                enabled=payload.enabled,
                recursive=payload.recursive,
                move_source=payload.move_source,
                options=payload.options,
            )
        except IngestionNotFound as error:
            raise missing(error) from error
        return FolderResponse.from_view(folder)

    @router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_folder(folder_id: uuid.UUID, actor: Actor) -> None:
        del actor
        try:
            service.delete_folder(folder_id)
        except IngestionNotFound as error:
            raise missing(error) from error

    @router.post(
        "/folders/{folder_id}/scan",
        response_model=Page[JobAccepted],
        status_code=status.HTTP_202_ACCEPTED,
    )
    def scan(folder_id: uuid.UUID, actor: Actor) -> Page[JobAccepted]:
        try:
            results = service.scan_folder(folder_id, actor.id)
        except IngestionNotFound as error:
            raise missing(error) from error
        return Page(
            items=[JobAccepted.from_result(result) for result in results],
            page=1,
            page_size=max(len(results), 1),
            total=len(results),
        )

    @router.get("/conversions", response_model=Page[JobResponse])
    def conversions(actor: Actor, page: int = 1, page_size: int = 24) -> Page[JobResponse]:
        del actor
        size = min(max(page_size, 1), 200)
        items, total = service.list_jobs(page=max(page, 1), page_size=size, status=None)
        items = [item for item in items if item.kind == "conversion"]
        return Page(
            items=[JobResponse.from_view(item) for item in items],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    return router
