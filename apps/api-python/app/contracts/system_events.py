from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.contracts.http import HttpContractModel

EventScalar = str | int | float | bool | datetime | None


class EventChangeSet(HttpContractModel):
    name: EventScalar = None
    description: EventScalar = None
    enabled: EventScalar = None
    root_path: EventScalar = Field(default=None, alias="rootPath")
    ignore_patterns: EventScalar = Field(default=None, alias="ignorePatterns")
    ignore_hidden: EventScalar = Field(default=None, alias="ignoreHidden")
    min_file_size_bytes: EventScalar = Field(default=None, alias="minFileSizeBytes")
    status: EventScalar = None
    progress: EventScalar = None
    error_message: EventScalar = Field(default=None, alias="errorMessage")


class SystemEventMetadata(HttpContractModel):
    reason: str | None = None
    role: str | None = None
    can_manage_system: bool | None = Field(default=None, alias="canManageSystem")
    keys: list[str] | None = None
    changes: EventChangeSet | None = None
    deleted: int | None = None
    status: str | None = None
    type: str | None = None
    action: str | None = None
    root_path: str | None = Field(default=None, alias="rootPath")
    path: str | None = None
    work_id: str | None = Field(default=None, alias="workId")
    edition_id: str | None = Field(default=None, alias="editionId")
    volume_id: str | None = Field(default=None, alias="volumeId")
    file_id: str | None = Field(default=None, alias="fileId")
    task_id: str | None = Field(default=None, alias="taskId")
    file_name: str | None = Field(default=None, alias="fileName")
    format: str | None = None
    size_bytes: int | None = Field(default=None, alias="sizeBytes")
    recipient_email: str | None = Field(default=None, alias="recipientEmail")
    error_message: str | None = Field(default=None, alias="errorMessage")
    file_path: str | None = Field(default=None, alias="filePath")
    requested_at: datetime | None = Field(default=None, alias="requestedAt")
    monitor_folder_ids: list[str] | None = Field(default=None, alias="monitorFolderIds")
    authorization_invalidated_for: int | None = Field(
        default=None,
        alias="authorizationInvalidatedFor",
    )
    source_path: str | None = Field(default=None, alias="sourcePath")
    target_path: str | None = Field(default=None, alias="targetPath")
    error_code: str | None = Field(default=None, alias="errorCode")
    queued: int | None = None
    saved: int | None = None
    imported: int | None = None
    candidates_found: int | None = Field(default=None, alias="candidatesFound")
    files_scanned: int | None = Field(default=None, alias="filesScanned")
    directories_scanned: int | None = Field(default=None, alias="directoriesScanned")
    skipped: int | None = None


class SystemEvent(HttpContractModel):
    id: str
    level: str
    source: str
    actor_type: str = Field(alias="actorType")
    actor_id: str | None = Field(alias="actorId")
    action: str
    target_type: str | None = Field(alias="targetType")
    target_id: str | None = Field(alias="targetId")
    message: str
    metadata: SystemEventMetadata
    created_at: datetime | None = Field(alias="createdAt")
