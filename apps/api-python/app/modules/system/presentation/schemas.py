from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.system_events import SystemEvent
from app.modules.library.public import LibraryOrganizationMode

SystemSettingValue = str | int | float | bool | list[str] | None


class FrontendResources(HttpContractModel):
    latest_version: str = Field(alias="latestVersion")
    update_required: bool = Field(alias="updateRequired")


class AppConfigPayload(HttpContractModel):
    language: Literal["zh-CN", "en-US"]
    supported_locales: list[Literal["zh-CN", "en-US"]] = Field(alias="supportedLocales")
    frontend_resources: FrontendResources = Field(alias="frontendResources")


class SystemSettingsPayload(HttpContractModel):
    settings: dict[str, SystemSettingValue]


class UpdateSystemSettingsRequest(HttpContractModel):
    settings: dict[str, SystemSettingValue]
    clear_sensitive_keys: list[str] = Field(
        default_factory=list,
        alias="clearSensitiveKeys",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_flat_settings(cls, value: object) -> object:
        """Keep the established flat request shape while documenting one DTO."""

        if not isinstance(value, dict):
            return value
        clear_sensitive_keys = value.get("clearSensitiveKeys", [])
        if "settings" in value:
            return {
                "settings": value.get("settings"),
                "clearSensitiveKeys": clear_sensitive_keys,
            }
        return {
            "settings": {
                str(key): setting_value
                for key, setting_value in value.items()
                if key != "clearSensitiveKeys"
            },
            "clearSensitiveKeys": clear_sensitive_keys,
        }


class LibraryScanSystemSettingsPayload(HttpContractModel):
    watch_enabled: bool = Field(alias="watchEnabled")
    interval_minutes: int = Field(alias="intervalMinutes", ge=5, le=1440)


class UpdateLibraryScanSystemSettingsRequest(HttpContractModel):
    watch_enabled: bool = Field(alias="watchEnabled")
    interval_minutes: int = Field(alias="intervalMinutes", ge=5, le=1440)


class SystemStatusCheck(HttpContractModel):
    name: str | None = None
    status: str
    message: str


class EnabledLibrary(HttpContractModel):
    id: str
    name: str
    root_path: str = Field(alias="rootPath")
    organization_mode: LibraryOrganizationMode = Field(alias="organizationMode")
    enabled: bool
    ignore_patterns: str | None = Field(alias="ignorePatterns")
    ignore_hidden: bool = Field(alias="ignoreHidden")
    min_file_size_bytes: int = Field(alias="minFileSizeBytes")
    description: str | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class SystemImportTaskSummary(HttpContractModel):
    id: str
    kind: str
    library_id: str = Field(alias="libraryId")
    resource_id: str | None = Field(alias="resourceId")
    source_node_id: str | None = Field(alias="sourceNodeId")
    role: str | None = None
    state: str
    error_summary: str | None = Field(alias="errorSummary")
    started_at: datetime | None = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    created_at: datetime = Field(alias="createdAt")


class DashboardSystemStatusPayload(HttpContractModel):
    database: SystemStatusCheck
    worker: SystemStatusCheck
    enabled_libraries: list[EnabledLibrary] = Field(alias="enabledLibraries")
    current_import_task: SystemImportTaskSummary | None = Field(
        alias="currentImportTask"
    )
    latest_import_task: SystemImportTaskSummary | None = Field(alias="latestImportTask")
    error_file_count: int = Field(alias="errorFileCount")
    library_roots_readable: SystemStatusCheck = Field(alias="libraryRootsReadable")
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


class ManagementOverviewCheck(HttpContractModel):
    status: str
    message: str


class ManagementOverviewPayload(HttpContractModel):
    cards: dict[str, int]
    checks: dict[str, ManagementOverviewCheck]
    recent_events: list[SystemEvent] = Field(alias="recentEvents")


AppConfigResponse = SuccessEnvelope[AppConfigPayload]
SystemSettingsResponse = SuccessEnvelope[SystemSettingsPayload]
LibraryScanSystemSettingsResponse = SuccessEnvelope[LibraryScanSystemSettingsPayload]
DashboardSystemStatusResponse = SuccessEnvelope[DashboardSystemStatusPayload]
ManagementEventsResponse = SuccessEnvelope[ManagementEventsPayload]
ClearedEventsResponse = SuccessEnvelope[ClearedEventsPayload]
ManagementOverviewResponse = SuccessEnvelope[ManagementOverviewPayload]
