import uuid
from datetime import datetime
from typing import Annotated, Self

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile, status
from pydantic import Field

from appv2.modules.accounts.contracts import AccessScope, AccountView, CurrentAccount
from appv2.modules.ingestion.application import (
    IngestionNotFound,
    IngestionService,
    IngestionSourceMissing,
)
from appv2.modules.ingestion.contracts import (
    SUPPORTED_IMPORT_EXTENSIONS,
    DirectoryNode,
    ImportResult,
    IngestionJob,
    IngestionPolicy,
    JobLog,
    MonitorFolder,
    ScanRun,
)
from appv2.platform.http import AppProblem, CamelModel, Page


class JobResponse(CamelModel):
    id: uuid.UUID
    kind: str
    origin: str
    status: str
    stage: str
    progress: int
    source_path: str
    requested_by: uuid.UUID | None
    monitor_folder_id: uuid.UUID | None
    triggered_by: str
    attempt: int
    max_attempts: int
    next_attempt_at: datetime
    lease_expires_at: datetime | None
    cancel_requested: bool
    retryable: bool
    result_work_id: uuid.UUID | None
    result_edition_id: uuid.UUID | None
    result_volume_ids: tuple[uuid.UUID, ...]
    error_code: str | None
    error_detail: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, job: IngestionJob) -> Self:
        return cls.model_validate(job)


class EnqueueRequest(CamelModel):
    source_path: str


class ConversionRequest(CamelModel):
    edition_id: uuid.UUID


class JobAccepted(CamelModel):
    id: uuid.UUID
    status: str
    duplicate: bool
    work_id: uuid.UUID | None
    edition_id: uuid.UUID | None
    volume_ids: tuple[uuid.UUID, ...]

    @classmethod
    def from_result(cls, result: ImportResult) -> Self:
        return cls(
            id=result.job_id,
            status=result.status,
            duplicate=result.duplicate,
            work_id=result.work_id,
            edition_id=result.edition_id,
            volume_ids=result.volume_ids,
        )


class JobLogResponse(CamelModel):
    id: uuid.UUID
    level: str
    message_key: str
    params: dict[str, object]
    created_at: datetime

    @classmethod
    def from_view(cls, log: JobLog) -> Self:
        return cls.model_validate(log)


class JobDetailResponse(CamelModel):
    job: JobResponse
    logs: list[JobLogResponse]


class FolderRequest(CamelModel):
    path: str
    recursive: bool = True
    options: dict[str, object] = Field(default_factory=dict)


class FolderUpdate(CamelModel):
    enabled: bool | None = None
    recursive: bool | None = None
    options: dict[str, object] | None = None


class FolderResponse(CamelModel):
    id: uuid.UUID
    path: str
    enabled: bool
    recursive: bool
    options: dict[str, object]
    last_scan_at: datetime | None
    created_at: datetime

    @classmethod
    def from_view(cls, folder: MonitorFolder) -> Self:
        return cls.model_validate(folder)


class FolderCreatedResponse(FolderResponse):
    scan_run_id: uuid.UUID

    @classmethod
    def from_views(cls, folder: MonitorFolder, scan: ScanRun) -> Self:
        return cls(
            **FolderResponse.from_view(folder).model_dump(),
            scan_run_id=scan.id,
        )


class ScanRunResponse(CamelModel):
    id: uuid.UUID
    trigger: str
    status: str
    monitor_folder_id: uuid.UUID | None
    requested_by: uuid.UUID | None
    directories_scanned: int
    files_scanned: int
    candidates_found: int
    queued: int
    ignored: int
    errors: tuple[dict[str, str], ...]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, scan: ScanRun) -> Self:
        return cls.model_validate(scan)


class IngestionPolicyResponse(CamelModel):
    allowed_extensions: tuple[str, ...]
    ignore_patterns: tuple[str, ...]
    stability_check_enabled: bool
    stability_check_seconds: int
    auto_convert_to_epub: bool
    updated_at: datetime

    @classmethod
    def from_view(cls, policy: IngestionPolicy) -> Self:
        return cls.model_validate(policy)


class IngestionPolicyRequest(CamelModel):
    allowed_extensions: tuple[str, ...] = SUPPORTED_IMPORT_EXTENSIONS
    ignore_patterns: tuple[str, ...] = ()
    stability_check_enabled: bool = True
    stability_check_seconds: int = Field(default=2, ge=0, le=300)
    auto_convert_to_epub: bool = True


class DeletedJobsResponse(CamelModel):
    deleted: int


class DirectoryNodeResponse(CamelModel):
    name: str
    path: str
    readable: bool
    error: str | None
    children: list["DirectoryNodeResponse"]

    @classmethod
    def from_view(cls, value: DirectoryNode) -> "DirectoryNodeResponse":
        return cls(
            name=value.name,
            path=value.path,
            readable=value.readable,
            error=value.error,
            children=[cls.from_view(child) for child in value.children],
        )


class DirectoryTreeResponse(CamelModel):
    node: DirectoryNodeResponse
    monitor_root: str


class ScanDirectoryRequest(CamelModel):
    path: str = Field(min_length=1)


class ScanDirectoryResponse(CamelModel):
    path: str
    directories_scanned: int
    files_scanned: int
    candidates_found: int
    queued: int
    skipped: int
    errors: list[dict[str, str]]


def create_router(service: IngestionService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/ingestion")

    def authorized(
        actor: Annotated[AccountView, Depends(current_account)],
    ) -> AccountView:
        if AccessScope.INGESTION_WRITE not in actor.scopes:
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
                params={"scope": AccessScope.INGESTION_WRITE.value},
            )
        return actor

    Actor = Annotated[AccountView, Depends(authorized)]

    def require_admin(actor: AccountView) -> None:
        if actor.role != "admin":
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
                params={"role": "admin"},
            )

    def missing(error: IngestionNotFound) -> AppProblem:
        if isinstance(error, IngestionSourceMissing):
            return AppProblem(
                status=404,
                code="SOURCE_FILE_MISSING",
                title="Source file missing",
                message_key="source_file_missing",
            )
        return AppProblem(
            status=404,
            code="INGESTION_RESOURCE_NOT_FOUND",
            title="Ingestion resource not found",
            message_key="not_found",
        )

    def can_access_job(actor: AccountView, job: IngestionJob) -> bool:
        return (
            actor.role == "admin"
            or job.requested_by == actor.id
            or (
                job.monitor_folder_id is not None
                and job.monitor_folder_id in actor.monitor_folder_ids
            )
        )

    def require_job_access(actor: AccountView, job: IngestionJob) -> None:
        if not can_access_job(actor, job):
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
                params={"resource": "ingestionJob"},
            )

    def scoped_job(job_id: uuid.UUID, actor: AccountView) -> tuple[IngestionJob, list[JobLog]]:
        try:
            job, logs = service.get_job(job_id)
        except IngestionNotFound as error:
            raise missing(error) from error
        require_job_access(actor, job)
        return job, logs

    def invalid_monitor_path() -> AppProblem:
        return AppProblem(
            status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_MONITOR_PATH",
            title="Invalid monitor path",
            message_key="invalid_request",
        )

    @router.get("/imports", response_model=Page[JobResponse])
    def imports(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        job_status: Annotated[str | None, Query(alias="status")] = None,
        origin: str | None = None,
        keyword: str | None = None,
        monitor_folder_id: Annotated[uuid.UUID | None, Query(alias="monitorFolderId")] = None,
    ) -> Page[JobResponse]:
        folder_scope: tuple[uuid.UUID, ...] | None
        if monitor_folder_id is not None and actor.role != "admin":
            if monitor_folder_id not in actor.monitor_folder_ids:
                raise AppProblem(
                    status=403,
                    code="PERMISSION_DENIED",
                    title="Permission denied",
                    message_key="permission_denied",
                    params={"resource": "monitorFolder"},
                )
            folder_scope = (monitor_folder_id,)
        elif actor.role == "admin":
            folder_scope = None if monitor_folder_id is None else (monitor_folder_id,)
        else:
            folder_scope = actor.monitor_folder_ids
        size = min(max(page_size, 1), 200)
        items, total = service.list_jobs(
            page=max(page, 1),
            page_size=size,
            status=job_status,
            origin=origin,
            keyword=keyword,
            monitor_folder_ids=folder_scope,
            requested_by=None if actor.role == "admin" else actor.id,
        )
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
        try:
            return JobAccepted.from_result(
                service.enqueue_monitored(
                    source_path=payload.source_path,
                    requested_by=actor.id,
                    idempotency_key=idempotency_key,
                    monitor_folder_ids=(
                        None if actor.role == "admin" else actor.monitor_folder_ids
                    ),
                )
            )
        except ValueError as error:
            raise invalid_monitor_path() from error

    @router.get("/policy", response_model=IngestionPolicyResponse)
    def policy(actor: Actor) -> IngestionPolicyResponse:
        require_admin(actor)
        return IngestionPolicyResponse.from_view(service.policy())

    @router.put("/policy", response_model=IngestionPolicyResponse)
    def update_policy(
        payload: IngestionPolicyRequest,
        actor: Actor,
    ) -> IngestionPolicyResponse:
        require_admin(actor)
        try:
            updated = service.update_policy(
                allowed_extensions=payload.allowed_extensions,
                ignore_patterns=payload.ignore_patterns,
                stability_check_enabled=payload.stability_check_enabled,
                stability_check_seconds=payload.stability_check_seconds,
                auto_convert_to_epub=payload.auto_convert_to_epub,
            )
        except ValueError as error:
            raise AppProblem(
                status=422,
                code="INVALID_INGESTION_POLICY",
                title="Invalid ingestion policy",
                message_key="invalid_request",
            ) from error
        return IngestionPolicyResponse.from_view(updated)

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
        scoped_job(job_id, actor)
        try:
            service.retry(job_id)
        except IngestionNotFound as error:
            raise missing(error) from error
        job, _logs = service.get_job(job_id)
        return JobAccepted(
            id=job.id,
            status=job.status,
            duplicate=False,
            work_id=job.result_work_id,
            edition_id=job.result_edition_id,
            volume_ids=job.result_volume_ids,
        )

    @router.post("/imports/{job_id}/cancel", response_model=JobResponse)
    def cancel(job_id: uuid.UUID, actor: Actor) -> JobResponse:
        scoped_job(job_id, actor)
        try:
            service.cancel(job_id)
        except IngestionNotFound as error:
            raise missing(error) from error
        job, _logs = service.get_job(job_id)
        return JobResponse.from_view(job)

    @router.get("/imports/{job_id}", response_model=JobDetailResponse)
    def import_detail(job_id: uuid.UUID, actor: Actor) -> JobDetailResponse:
        job, logs = scoped_job(job_id, actor)
        return JobDetailResponse(
            job=JobResponse.from_view(job),
            logs=[JobLogResponse.from_view(log) for log in logs],
        )

    @router.post(
        "/imports/rescan",
        response_model=ScanRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def rescan(actor: Actor) -> ScanRunResponse:
        require_admin(actor)
        return ScanRunResponse.from_view(
            service.request_scan(
                trigger="manual",
                monitor_folder_id=None,
                requested_by=actor.id,
            )
        )

    @router.get("/scans/{scan_run_id}", response_model=ScanRunResponse)
    def scan_status(scan_run_id: uuid.UUID, actor: Actor) -> ScanRunResponse:
        try:
            scan = service.get_scan(scan_run_id)
        except IngestionNotFound as error:
            raise missing(error) from error
        if (
            actor.role != "admin"
            and scan.requested_by != actor.id
            and (
                scan.monitor_folder_id is None
                or scan.monitor_folder_id not in actor.monitor_folder_ids
            )
        ):
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
            )
        return ScanRunResponse.from_view(scan)

    @router.delete("/imports", response_model=DeletedJobsResponse)
    def clear_finished(actor: Actor) -> DeletedJobsResponse:
        require_admin(actor)
        return DeletedJobsResponse(deleted=service.clear_finished())

    @router.post(
        "/imports/scan-directory",
        response_model=ScanDirectoryResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def scan_directory(
        payload: ScanDirectoryRequest,
        actor: Actor,
    ) -> ScanDirectoryResponse:
        require_admin(actor)
        try:
            results = service.scan_directory(payload.path, actor.id)
        except ValueError as error:
            raise invalid_monitor_path() from error
        return ScanDirectoryResponse(
            path=payload.path,
            directories_scanned=1,
            files_scanned=len(results),
            candidates_found=len(results),
            queued=sum(not result.duplicate for result in results),
            skipped=sum(result.duplicate for result in results),
            errors=[],
        )

    @router.delete("/imports/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_job(job_id: uuid.UUID, actor: Actor) -> None:
        scoped_job(job_id, actor)
        try:
            service.delete_job(job_id)
        except IngestionNotFound as error:
            raise missing(error) from error

    @router.get("/folders", response_model=Page[FolderResponse])
    def folders(actor: Actor) -> Page[FolderResponse]:
        values = service.list_folders()
        if actor.role != "admin":
            values = [value for value in values if value.id in actor.monitor_folder_ids]
        return Page(
            items=[FolderResponse.from_view(value) for value in values],
            page=1,
            page_size=max(len(values), 1),
            total=len(values),
        )

    @router.get("/folders/tree", response_model=DirectoryTreeResponse)
    def folder_tree(actor: Actor, path: str | None = None) -> DirectoryTreeResponse:
        require_admin(actor)
        try:
            node, monitor_root = service.directory_tree(path)
        except ValueError as error:
            raise invalid_monitor_path() from error
        return DirectoryTreeResponse(
            node=DirectoryNodeResponse.from_view(node),
            monitor_root=monitor_root,
        )

    @router.post(
        "/folders",
        response_model=FolderCreatedResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_folder(payload: FolderRequest, actor: Actor) -> FolderCreatedResponse:
        require_admin(actor)
        try:
            folder, scan = service.add_folder(
                path=payload.path,
                recursive=payload.recursive,
                options=payload.options,
                requested_by=actor.id,
            )
            return FolderCreatedResponse.from_views(folder, scan)
        except ValueError as error:
            raise invalid_monitor_path() from error

    @router.patch("/folders/{folder_id}", response_model=FolderResponse)
    def update_folder(folder_id: uuid.UUID, payload: FolderUpdate, actor: Actor) -> FolderResponse:
        require_admin(actor)
        try:
            folder = service.update_folder(
                folder_id,
                enabled=payload.enabled,
                recursive=payload.recursive,
                options=payload.options,
            )
        except IngestionNotFound as error:
            raise missing(error) from error
        return FolderResponse.from_view(folder)

    @router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_folder(folder_id: uuid.UUID, actor: Actor) -> None:
        require_admin(actor)
        try:
            service.delete_folder(folder_id)
        except IngestionNotFound as error:
            raise missing(error) from error

    @router.post(
        "/folders/{folder_id}/scan",
        response_model=ScanRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def scan(folder_id: uuid.UUID, actor: Actor) -> ScanRunResponse:
        if actor.role != "admin" and folder_id not in actor.monitor_folder_ids:
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
            )
        try:
            scan_run = service.request_scan(
                trigger="manual",
                monitor_folder_id=folder_id,
                requested_by=actor.id,
            )
        except IngestionNotFound as error:
            raise missing(error) from error
        return ScanRunResponse.from_view(scan_run)

    @router.get("/conversions", response_model=Page[JobResponse])
    def conversions(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
    ) -> Page[JobResponse]:
        size = min(max(page_size, 1), 200)
        items, total = service.list_jobs(
            page=max(page, 1),
            page_size=size,
            status=None,
            kind="conversion",
            monitor_folder_ids=None if actor.role == "admin" else (),
            requested_by=None if actor.role == "admin" else actor.id,
        )
        return Page(
            items=[JobResponse.from_view(item) for item in items],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    @router.post(
        "/conversions",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def convert(
        payload: ConversionRequest,
        actor: Actor,
    ) -> JobAccepted:
        try:
            result = service.enqueue_conversion(
                edition_id=payload.edition_id,
                requested_by=actor.id,
            )
        except IngestionNotFound as error:
            raise missing(error) from error
        except ValueError as error:
            raise AppProblem(
                status=422,
                code="UNSUPPORTED_CONVERSION",
                title="Unsupported conversion",
                message_key="invalid_request",
            ) from error
        return JobAccepted.from_result(result)

    return router
