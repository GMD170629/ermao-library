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


class ScanImportDirectoryRequest(HttpContractModel):
    path: str = ""


class DeleteImportTaskRequest(HttpContractModel):
    delete_mode: Literal["record", "source"] = Field(
        default="record", alias="deleteMode"
    )
    delete_library_record: bool = Field(default=False, alias="deleteLibraryRecord")


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


class ImportLog(HttpContractModel):
    id: str
    level: str
    message: str
    created_at: datetime | None = Field(alias="createdAt")


class ImportedBook(HttpContractModel):
    id: str
    title: str


class RecognizedImportMetadata(HttpContractModel):
    title: str
    volume_title: str = Field(alias="volumeTitle")
    author: str | None
    volume_index: float | None = Field(alias="volumeIndex")
    fields: list[str]
    field_sources: dict[
        str, Literal["REQUESTED", "SIDECAR_OPF", "EMBEDDED", "PATH"]
    ] = Field(alias="fieldSources")
    source_order: list[Literal["SIDECAR_OPF", "EMBEDDED", "PATH"]] = Field(
        alias="sourceOrder"
    )
    source: Literal["REQUESTED", "SIDECAR_OPF", "EMBEDDED", "PATH"]


class ImportTask(HttpContractModel):
    id: str
    library_id: str | None = Field(alias="libraryId")
    work_id: str | None = Field(alias="workId")
    volume_id: str | None = Field(alias="volumeId")
    origin: str
    media_kind_policy: Literal["MIXED", "EBOOK", "COMIC", "AUDIOBOOK"] = Field(
        alias="mediaKindPolicy"
    )
    status: str
    original_name: str | None = Field(alias="originalName")
    requested_title: str | None = Field(alias="requestedTitle")
    requested_author: str | None = Field(alias="requestedAuthor")
    recognized_metadata: RecognizedImportMetadata | None = Field(
        alias="recognizedMetadata"
    )
    source_path: str = Field(alias="sourcePath")
    task_kind: str = Field(alias="taskKind")
    bundle_key: str | None = Field(alias="bundleKey")
    asset_count: int = Field(alias="assetCount")
    processed_asset_count: int = Field(alias="processedAssetCount")
    progress: int
    duration: int
    error_summary: str | None = Field(alias="errorSummary")
    error_code: str | None = Field(alias="errorCode")
    retryable: bool
    attempts: int
    lease_owner: str | None = Field(alias="leaseOwner")
    lease_expires_at: datetime | None = Field(alias="leaseExpiresAt")
    message: str | None
    started_at: datetime | None = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    source_file_exists: bool = Field(alias="sourceFileExists")
    friendly_error: str | None = Field(alias="friendlyError")
    library: Library | None = Field(alias="library")
    book: ImportedBook | None
    logs: list[ImportLog]


class ImportTaskSummary(HttpContractModel):
    completed: int
    failed: int


class ImportTasksPayload(HttpContractModel):
    tasks: list[ImportTask]
    summary: ImportTaskSummary
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class ImportTaskPayload(HttpContractModel):
    task: ImportTask


class ImportLogsPayload(HttpContractModel):
    logs: list[ImportLog]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class ScanError(HttpContractModel):
    path: str
    error: str
    code: str | None = None
    limit: int | None = None
    observed_count: int | None = Field(default=None, alias="observedCount")


class ImportScanJob(HttpContractModel):
    id: str
    library_id: str | None = Field(alias="libraryId")
    root_path: str = Field(alias="rootPath")
    trigger: str
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    directories_scanned: int = Field(alias="directoriesScanned")
    files_scanned: int = Field(alias="filesScanned")
    candidates_found: int = Field(alias="candidatesFound")
    queued_count: int = Field(alias="queuedCount")
    skipped_count: int = Field(alias="skippedCount")
    error_count: int = Field(alias="errorCount")
    ignored_reason_counts: dict[str, int] = Field(alias="ignoredReasonCounts")
    error_samples: list[ScanError] = Field(alias="errorSamples")
    restart_count: int = Field(alias="restartCount")
    started_at: datetime | None = Field(alias="startedAt")
    heartbeat_at: datetime | None = Field(alias="heartbeatAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ImportScanJobPayload(HttpContractModel):
    job: ImportScanJob


class ImportScanJobMutationPayload(ImportScanJobPayload):
    created: bool


class ImportScanJobsPayload(HttpContractModel):
    jobs: list[ImportScanJob]


class DeletedImportTasksPayload(HttpContractModel):
    deleted: int


class ImportQueueClearOperation(HttpContractModel):
    id: str
    queue_name: Literal["import"] = Field(alias="queueName")
    action: Literal["clear"]
    status: Literal["requested", "waiting", "running", "completed", "failed"]
    actor_user_id: str = Field(alias="actorUserId")
    message_code: str = Field(alias="messageCode")
    requested_at: datetime = Field(alias="requestedAt")
    started_at: datetime | None = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    updated_at: datetime = Field(alias="updatedAt")


class ImportQueueClearPayload(HttpContractModel):
    operation: ImportQueueClearOperation
    created: bool


class RescanImportTasksPayload(HttpContractModel):
    requested_at: datetime = Field(alias="requestedAt")
    jobs: list[ImportScanJob]


ImportTasksResponse = SuccessEnvelope[ImportTasksPayload]
ImportTaskResponse = SuccessEnvelope[ImportTaskPayload]
ImportLogsResponse = SuccessEnvelope[ImportLogsPayload]
ImportDirectoryScanResponse = SuccessEnvelope[ImportScanJobMutationPayload]
ImportScanJobResponse = SuccessEnvelope[ImportScanJobPayload]
ImportScanJobsResponse = SuccessEnvelope[ImportScanJobsPayload]
DeletedImportTasksResponse = SuccessEnvelope[DeletedImportTasksPayload]
ImportQueueClearResponse = SuccessEnvelope[ImportQueueClearPayload]
RescanImportTasksResponse = SuccessEnvelope[RescanImportTasksPayload]


class SavedUploadResult(HttpContractModel):
    source_path: str = Field(alias="sourcePath")
    file: str
    size_bytes: int = Field(alias="sizeBytes")
    monitoring_status: Literal["WATCHING", "NOT_MONITORED"] = Field(
        alias="monitoringStatus"
    )


class ImportUploadPayload(HttpContractModel):
    results: list[SavedUploadResult]
    saved: int
    auto_import: bool = Field(alias="autoImport")


class ImportDeleteFailure(HttpContractModel):
    path: str
    message: str


class ImportDeletionPayload(HttpContractModel):
    deleted: bool
    id: str
    delete_mode: Literal["record", "source"] = Field(alias="deleteMode")
    delete_library_record: bool = Field(alias="deleteLibraryRecord")
    deleted_library_record: bool = Field(alias="deletedLibraryRecord")
    deleted_work_record: bool = Field(alias="deletedWorkRecord")
    deleted_library_database_records: int = Field(alias="deletedLibraryDatabaseRecords")
    library_record_id: str | None = Field(alias="libraryRecordId")
    deleted_files: int = Field(alias="deletedFiles")
    missing_files: list[str] = Field(alias="missingFiles")
    failed_file_deletes: list[ImportDeleteFailure] = Field(alias="failedFileDeletes")


ImportUploadResponse = SuccessEnvelope[ImportUploadPayload]
ImportDeletionResponse = SuccessEnvelope[ImportDeletionPayload]


class ImportFileListDetails(HttpContractModel):
    files: list[str]


class ImportDeletionFailureDetails(HttpContractModel):
    failed_file_deletes: list[ImportDeleteFailure] = Field(alias="failedFileDeletes")


class ImportErrorBody(HttpContractModel):
    message: str
    code: str | None = None
    details: ImportFileListDetails | ImportDeletionFailureDetails | None = None


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
