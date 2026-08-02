from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi.responses import Response
from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.system_events import SystemEvent

SystemSettingValue = str | int | float | bool | list[str] | None


class BackupArchiveResponse(Response):
    media_type = "application/zip"


class AppConfigPayload(HttpContractModel):
    language: Literal["zh-CN", "en-US"]
    supported_locales: list[Literal["zh-CN", "en-US"]] = Field(alias="supportedLocales")


class SystemSettingsPayload(HttpContractModel):
    settings: dict[str, SystemSettingValue]


class Backup(HttpContractModel):
    id: str
    kind: str | None = None
    name: str
    filename: str | None = None
    size_bytes: int = Field(alias="sizeBytes")
    created_at: datetime = Field(alias="createdAt")
    counts: dict[str, int] | None = None


class BackupsPayload(HttpContractModel):
    backups: list[Backup]


class BackupPayload(HttpContractModel):
    backup: Backup


class BackupRestorePayload(HttpContractModel):
    id: str
    restored: Literal[True]
    restored_at: datetime = Field(alias="restoredAt")
    counts: dict[str, int] | None
    restored_counts: dict[str, int] = Field(alias="restoredCounts")
    actual_counts: dict[str, int] = Field(alias="actualCounts")


class BackupDeletePayload(HttpContractModel):
    deleted: bool
    id: str


class SystemStatusCheck(HttpContractModel):
    name: str | None = None
    status: str
    message: str


class EnabledMonitorFolder(HttpContractModel):
    id: str
    name: str
    root_path: str = Field(alias="rootPath")
    shelf_id: str | None = Field(alias="shelfId")
    enabled: bool
    ignore_patterns: str | None = Field(alias="ignorePatterns")
    ignore_hidden: bool = Field(alias="ignoreHidden")
    min_file_size_bytes: int = Field(alias="minFileSizeBytes")
    description: str | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class SystemImportTaskSummary(HttpContractModel):
    id: str
    monitor_folder_id: str | None = Field(alias="monitorFolderId")
    work_id: str | None = Field(alias="workId")
    volume_id: str | None = Field(alias="volumeId")
    origin: str
    status: str
    original_name: str | None = Field(alias="originalName")
    requested_title: str | None = Field(alias="requestedTitle")
    requested_author: str | None = Field(alias="requestedAuthor")
    source_path: str = Field(alias="sourcePath")
    content_hash: str | None = Field(alias="contentHash")
    task_kind: str = Field(alias="taskKind")
    bundle_key: str | None = Field(alias="bundleKey")
    asset_count: int = Field(alias="assetCount")
    processed_asset_count: int = Field(alias="processedAssetCount")
    progress: int
    duplicate: bool
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


class DashboardSystemStatusPayload(HttpContractModel):
    database: SystemStatusCheck
    worker: SystemStatusCheck
    enabled_monitor_folders: list[EnabledMonitorFolder] = Field(
        alias="enabledMonitorFolders"
    )
    current_import_task: SystemImportTaskSummary | None = Field(
        alias="currentImportTask"
    )
    latest_import_task: SystemImportTaskSummary | None = Field(alias="latestImportTask")
    error_file_count: int = Field(alias="errorFileCount")
    monitor_root_readable: SystemStatusCheck = Field(alias="monitorRootReadable")
    storage_writable: SystemStatusCheck = Field(alias="storageWritable")


class EventSourceFacet(HttpContractModel):
    source: str
    count: int


class EventLevelFacet(HttpContractModel):
    level: str
    count: int


class EventFacets(HttpContractModel):
    sources: list[EventSourceFacet]
    levels: list[EventLevelFacet]


class EventPruneStorage(HttpContractModel):
    deleted: int
    size_bytes: int = Field(alias="sizeBytes")
    max_bytes: int = Field(alias="maxBytes")


class ManagementEventsPayload(HttpContractModel):
    events: list[SystemEvent]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")
    storage: EventPruneStorage
    facets: EventFacets


class ClearedEventsPayload(HttpContractModel):
    deleted: int
    storage: EventPruneStorage | None = None


AppConfigResponse = SuccessEnvelope[AppConfigPayload]
SystemSettingsResponse = SuccessEnvelope[SystemSettingsPayload]
BackupsResponse = SuccessEnvelope[BackupsPayload]
BackupResponse = SuccessEnvelope[BackupPayload]
BackupRestoreResponse = SuccessEnvelope[BackupRestorePayload]
BackupDeleteResponse = SuccessEnvelope[BackupDeletePayload]
DashboardSystemStatusResponse = SuccessEnvelope[DashboardSystemStatusPayload]
ManagementEventsResponse = SuccessEnvelope[ManagementEventsPayload]
ClearedEventsResponse = SuccessEnvelope[ClearedEventsPayload]
