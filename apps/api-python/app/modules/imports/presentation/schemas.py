"""Validated HTTP contracts for library management and ContinueImport."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import HttpContractError
from app.modules.library.domain.layout import LibraryOrganizationMode


class Library(HttpContractModel):
    id: str
    name: str
    root_path: str = Field(alias="rootPath")
    organization_mode: LibraryOrganizationMode = Field(alias="organizationMode")
    enabled: bool
    ignore_patterns: str | None = Field(default=None, alias="ignorePatterns")
    ignore_hidden: bool = Field(alias="ignoreHidden")
    min_file_size_bytes: int = Field(alias="minFileSizeBytes")
    description: str | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class CreateLibraryRequest(HttpContractModel):
    root_path: str = Field(alias="rootPath", min_length=1)
    name: str | None = None
    organization_mode: LibraryOrganizationMode = Field(alias="organizationMode")
    enabled: bool = True
    ignore_patterns: str | None = Field(default=None, alias="ignorePatterns")
    ignore_hidden: bool = Field(default=True, alias="ignoreHidden")
    min_file_size_bytes: int = Field(default=10240, ge=0, alias="minFileSizeBytes")
    description: str | None = None


class UpdateLibraryRequest(HttpContractModel):
    root_path: str | None = Field(default=None, alias="rootPath")
    name: str | None = None
    organization_mode: LibraryOrganizationMode | None = Field(
        default=None, alias="organizationMode"
    )
    enabled: bool | None = None
    ignore_patterns: str | None = Field(default=None, alias="ignorePatterns")
    ignore_hidden: bool | None = Field(default=None, alias="ignoreHidden")
    min_file_size_bytes: int | None = Field(
        default=None, ge=0, alias="minFileSizeBytes"
    )
    description: str | None = None


class ParseReleaseTitleRequest(HttpContractModel):
    title: str = ""


class LibrariesPayload(HttpContractModel):
    libraries: list[Library]
    last_upload_target_path: str | None = Field(alias="lastUploadTargetPath")
    last_download_target_path: str | None = Field(alias="lastDownloadTargetPath")


class LibraryPayload(HttpContractModel):
    library: Library


class LibraryDirectoryChild(HttpContractModel):
    name: str
    path: str
    readable: bool


class LibraryDirectoryNode(LibraryDirectoryChild):
    error: str | None
    children: list[LibraryDirectoryChild]


class LibraryDirectoryPayload(HttpContractModel):
    node: LibraryDirectoryNode


class DeletedLibraryPayload(HttpContractModel):
    deleted: bool
    id: str


class ParsedReleaseTitle(HttpContractModel):
    title: str
    volume: float | None
    chapter: float | None


class ParsedReleaseTitlePayload(HttpContractModel):
    parsed: ParsedReleaseTitle


LibrariesResponse = SuccessEnvelope[LibrariesPayload]
LibraryResponse = SuccessEnvelope[LibraryPayload]
LibraryDirectoryResponse = SuccessEnvelope[LibraryDirectoryPayload]
DeletedLibraryResponse = SuccessEnvelope[DeletedLibraryPayload]
ParsedReleaseTitleResponse = SuccessEnvelope[ParsedReleaseTitlePayload]


class ContinueImportPayload(HttpContractModel):
    task_id: str | None = Field(default=None, alias="taskId")
    library_id: str = Field(alias="libraryId")
    source_node_id: str | None = Field(default=None, alias="sourceNodeId")
    requeued_failed: int = Field(alias="requeuedFailed")
    enqueued: bool


ContinueImportResponse = SuccessEnvelope[ContinueImportPayload]


class LibraryImportTaskView(HttpContractModel):
    """The public, read-only projection of one canonical import task."""

    id: str
    kind: Literal["SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_ASSET"]
    library_id: str = Field(alias="libraryId")
    library_name: str | None = Field(default=None, alias="libraryName")
    resource_id: str | None = Field(default=None, alias="resourceId")
    resource_title: str | None = Field(default=None, alias="resourceTitle")
    source_node_id: str | None = Field(default=None, alias="sourceNodeId")
    source_name: str | None = Field(default=None, alias="sourceName")
    source_relative_path: str | None = Field(default=None, alias="sourceRelativePath")
    book_title: str | None = Field(default=None, alias="bookTitle")
    role: Literal["PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT"] | None = None
    state: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    error_summary: str | None = Field(default=None, alias="errorSummary")
    created_at: datetime = Field(alias="createdAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")


class LibraryImportTaskListPayload(HttpContractModel):
    tasks: list[LibraryImportTaskView]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")
    queued: int
    running: int
    completed: int
    failed: int


class LibraryImportTaskDetailPayload(HttpContractModel):
    task: LibraryImportTaskView


LibraryImportTaskListResponse = SuccessEnvelope[LibraryImportTaskListPayload]
LibraryImportTaskDetailResponse = SuccessEnvelope[LibraryImportTaskDetailPayload]


class SavedUploadResult(HttpContractModel):
    source_path: str = Field(alias="sourcePath")
    file: str
    size_bytes: int = Field(alias="sizeBytes")


class ImportUploadPayload(HttpContractModel):
    results: list[SavedUploadResult]
    saved: int
    task_id: str | None = Field(default=None, alias="taskId")


ImportUploadResponse = SuccessEnvelope[ImportUploadPayload]


class ImportFileListDetails(HttpContractModel):
    files: list[str]


class ImportErrorBody(HttpContractModel):
    message: str
    code: str | None = None
    details: ImportFileListDetails | None = None


class ImportBadRequestError(HttpContractError[ImportErrorBody]):
    status_code = 400
    body_model = ImportErrorBody


class ImportForbiddenError(HttpContractError[ImportErrorBody]):
    status_code = 403
    body_model = ImportErrorBody


class ImportNotFoundError(HttpContractError[ImportErrorBody]):
    status_code = 404
    body_model = ImportErrorBody


class ImportConflictError(HttpContractError[ImportErrorBody]):
    status_code = 409
    body_model = ImportErrorBody


class ImportInternalError(HttpContractError[ImportErrorBody]):
    status_code = 500
    body_model = ImportErrorBody


__all__ = [name for name in globals() if not name.startswith("_")]
