from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope


class DownloadReferenceDetails(HttpContractModel):
    kind: str | None = None
    type: str | None = None
    source: str | None = None
    download_url: str | None = Field(default=None, alias="downloadUrl")
    torrent_url: str | None = Field(default=None, alias="torrentUrl")
    magnet_url: str | None = Field(default=None, alias="magnetUrl")
    blackhole_path: str | None = Field(default=None, alias="blackholePath")
    filename: str | None = None
    enclosure_type: str | None = Field(default=None, alias="enclosureType")
    enclosure_length: str | None = Field(default=None, alias="enclosureLength")
    ref_hash: str | None = Field(default=None, alias="refHash")


class DownloadReference(DownloadReferenceDetails):
    provider_type: str | None = Field(default=None, alias="providerType")
    external_id: str | None = Field(default=None, alias="externalId")
    external_url: str | None = Field(default=None, alias="externalUrl")
    format: str | None = None
    size: str | None = None
    download_meta: DownloadReferenceDetails | None = Field(
        default=None,
        alias="downloadMeta",
    )


class CreateDownloadTaskRequest(HttpContractModel):
    source_id: str | None = Field(default=None, alias="sourceId")
    search_record_id: str | None = Field(default=None, alias="searchRecordId")
    book_id: str | None = Field(default=None, alias="bookId")
    type: str = "manual"
    status: str = "queued"
    display_name: str | None = Field(default=None, alias="displayName")
    name: str | None = None
    remote_ref: DownloadReference | str | None = Field(default=None, alias="remoteRef")
    target_path: str | None = Field(default=None, alias="targetPath")
    file_path: str | None = Field(default=None, alias="filePath")
    error_message: str | None = Field(default=None, alias="errorMessage")
    progress: float | int | None = None


class UpdateDownloadTaskRequest(HttpContractModel):
    type: str | None = None
    status: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    save_path: str | None = Field(default=None, alias="savePath")
    file_path: str | None = Field(default=None, alias="filePath")
    error_message: str | None = Field(default=None, alias="errorMessage")
    progress: float | int | None = None
    remote_ref: DownloadReference | str | None = Field(default=None, alias="remoteRef")


class DownloadTask(HttpContractModel):
    id: str
    source_id: str | None = Field(default=None, alias="sourceId")
    search_record_id: str | None = Field(default=None, alias="searchRecordId")
    book_id: str | None = Field(default=None, alias="bookId")
    type: str
    status: str
    display_name: str = Field(alias="displayName")
    remote_ref: DownloadReference | str | None = Field(alias="remoteRef")
    save_path: str | None = Field(default=None, alias="savePath")
    file_path: str | None = Field(default=None, alias="filePath")
    error_message: str | None = Field(default=None, alias="errorMessage")
    progress: float | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    source_name: str | None = Field(
        default=None,
        alias="sourceName",
        exclude_if=lambda value: value is None,
    )
    auto_import: bool | None = Field(
        default=None,
        alias="autoImport",
        exclude_if=lambda value: value is None,
    )


class DownloadTasksPayload(HttpContractModel):
    tasks: list[DownloadTask]


class DownloadTaskPayload(HttpContractModel):
    task: DownloadTask
    auto_import: bool | None = Field(
        default=None,
        alias="autoImport",
        exclude_if=lambda value: value is None,
    )
    action: Literal["start", "retry", "cancel"] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class DeletedDownloadTaskPayload(HttpContractModel):
    deleted: bool
    id: str


DownloadTasksResponse = SuccessEnvelope[DownloadTasksPayload]
DownloadTaskResponse = SuccessEnvelope[DownloadTaskPayload]
DeletedDownloadTaskResponse = SuccessEnvelope[DeletedDownloadTaskPayload]
