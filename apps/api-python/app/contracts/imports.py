"""Stable HTTP contract for import-task summaries."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.modules.imports.application.dto import ImportTaskDTO


class ImportTaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    source_path: str = Field(alias="sourcePath")
    origin: str
    media_kind_policy: str = Field(default="MIXED", alias="mediaKindPolicy")
    status: str
    original_name: str | None = Field(default=None, alias="originalName")
    requested_title: str | None = Field(default=None, alias="requestedTitle")
    requested_author: str | None = Field(default=None, alias="requestedAuthor")
    monitor_folder_id: str | None = Field(default=None, alias="monitorFolderId")
    work_id: str | None = Field(default=None, alias="workId")
    volume_id: str | None = Field(default=None, alias="volumeId")
    task_kind: str = Field(alias="taskKind")
    bundle_key: str | None = Field(default=None, alias="bundleKey")
    asset_count: int = Field(alias="assetCount")
    processed_asset_count: int = Field(alias="processedAssetCount")
    progress: int
    duplicate: bool
    duration: int
    error_summary: str | None = Field(default=None, alias="errorSummary")
    error_code: str | None = Field(default=None, alias="errorCode")
    retryable: bool
    attempts: int
    lease_owner: str | None = Field(default=None, alias="leaseOwner")
    message: str | None = None

    @classmethod
    def from_dto(cls, task: ImportTaskDTO) -> ImportTaskContract:
        return cls.model_validate(task, from_attributes=True)

    def to_wire(self) -> dict[str, object]:
        return self.model_dump(by_alias=True)

    def to_dto(self) -> ImportTaskDTO:
        return ImportTaskDTO(**self.model_dump())
