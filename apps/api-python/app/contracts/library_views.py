"""Stable read-only Library view contracts used across capabilities."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel


class ResourceAssetView(HttpContractModel):
    id: str
    title: str
    resource_id: str = Field(alias="resourceId")
    source_node_id: str = Field(alias="sourceNodeId")
    role: str
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    size: str = "0 B"
    mtime_ms: int = Field(alias="mtimeMs", ge=0)
    duration_ms: int | None = Field(default=None, alias="durationMs")
    codec: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = Field(default=None, alias="sampleRate")
    channels: int | None = None
    disc_number: int | None = Field(default=None, alias="discNumber")
    track_number: int | None = Field(default=None, alias="trackNumber")
    sort_order: int = Field(alias="sortOrder")
    url: str
    download_url: str = Field(alias="downloadUrl")


class ResourceView(HttpContractModel):
    id: str
    book_id: str = Field(alias="bookId")
    source_node_id: str = Field(alias="sourceNodeId")
    title: str
    description: str | None = None
    resource_index: float | None = Field(default=None, alias="resourceIndex")
    sort_order: int = Field(default=0, alias="sortOrder")
    format: str
    reader_type: Literal["reflowable", "comic", "pdf", "audio"] = Field(
        alias="readerType"
    )
    kindle_send_available: bool = Field(alias="kindleSendAvailable")
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    isbn: str | None = None
    identifier: str | None = None
    narrator: str | None = None
    abridged: bool | None = None
    import_status: str = Field(default="READY", alias="importStatus")
    import_error: str | None = Field(default=None, alias="importError")
    size_bytes: int = Field(default=0, alias="sizeBytes", ge=0)
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    track_count: int | None = Field(default=None, alias="trackCount")
    cover_status: str = Field(alias="coverStatus")
    cover_path: str | None = Field(default=None, alias="coverPath")
    cover_url: str = Field(alias="coverUrl")
    progress: float = 0
    last_read_at: datetime | None = Field(default=None, alias="lastReadAt")
    hidden: bool = False
    readable: bool = True
    resource_completed: bool = Field(default=False, alias="resourceCompleted")
    assets: list[ResourceAssetView] = Field(default_factory=list)


class ResourceImportSummary(HttpContractModel):
    ready: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class BookView(HttpContractModel):
    id: str
    library_id: str = Field(alias="libraryId")
    source_node_id: str = Field(alias="sourceNodeId")
    title: str
    author: str | None = None
    description: str | None = None
    series_name: str | None = Field(default=None, alias="seriesName")
    series_index: float | None = Field(default=None, alias="seriesIndex")
    visibility_state: str = Field(alias="visibilityState")
    curation_state: str = Field(alias="curationState")
    publication_status: str = Field(alias="publicationStatus")
    tracking_status: str = Field(alias="trackingStatus")
    metadata_quality: int = Field(alias="metadataQuality")
    cover_status: str = Field(alias="coverStatus")
    cover_path: str | None = Field(default=None, alias="coverPath")
    cover_url: str = Field(alias="coverUrl")
    tags: list[str] = Field(default_factory=list)
    ignored: bool = False
    organized: bool = False
    added_at: datetime | None = Field(default=None, alias="addedAt")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    gradient: str = ""
    resources: list[ResourceView] = Field(default_factory=list)
    resource_import_summary: ResourceImportSummary = Field(
        default_factory=ResourceImportSummary,
        alias="resourceImportSummary",
    )
    completed: bool
    continue_resource_id: str | None = Field(default=None, alias="continueResourceId")
    continue_resource_title: str | None = Field(
        default=None, alias="continueResourceTitle"
    )
    continue_resource_progress: float = Field(
        default=0, alias="continueResourceProgress"
    )
