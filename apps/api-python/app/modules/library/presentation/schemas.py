"""Validated HTTP contracts for the Book/Resource/Asset library surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope

MediaKind = Literal["EBOOK", "COMIC", "AUDIOBOOK"]


class FilterOption(HttpContractModel):
    value: str
    label: str
    count: int | None = None
    root_path: str | None = Field(default=None, alias="rootPath")


class FilterFieldDefinition(HttpContractModel):
    key: str
    label: str
    group: str
    type: str
    operators: list[str]
    option_source: str | None = Field(default=None, alias="optionSource")
    allow_custom: bool = Field(default=False, alias="allowCustom")
    unit: str | None = None
    value_scale: int | None = Field(default=None, alias="valueScale")
    options: list[FilterOption] = Field(default_factory=list)


class FilterSchemaPayload(HttpContractModel):
    fields: list[FilterFieldDefinition]
    max_conditions: int = Field(alias="maxConditions")


class FilterSuggestionOption(HttpContractModel):
    value: str
    label: str
    count: int = 0


class FilterOptionsPayload(HttpContractModel):
    source: str
    query: str
    options: list[FilterSuggestionOption]
    has_more: bool = Field(alias="hasMore")
    index_ready: bool = Field(alias="indexReady")


class ResourceAssetView(HttpContractModel):
    id: str
    resource_id: str = Field(alias="resourceId")
    source_node_id: str = Field(alias="sourceNodeId")
    role: str
    mime_type: str = Field(alias="mimeType")
    path: str = ""
    kind: str = ""
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


class ResourceView(HttpContractModel):
    id: str
    book_id: str = Field(alias="bookId")
    source_node_id: str = Field(alias="sourceNodeId")
    title: str
    resource_index: float | None = Field(default=None, alias="resourceIndex")
    sort_order: int = Field(default=0, alias="sortOrder")
    format: str
    media_kind: MediaKind = Field(alias="mediaKind")
    reader_type: Literal["reflowable", "comic", "pdf", "audio"] = Field(
        alias="readerType"
    )
    classification: dict[str, str | None] = Field(default_factory=dict)
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
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    completed: bool
    continue_resource_id: str | None = Field(default=None, alias="continueResourceId")
    continue_resource_title: str | None = Field(
        default=None, alias="continueResourceTitle"
    )
    continue_resource_progress: float = Field(
        default=0, alias="continueResourceProgress"
    )


class BookSummary(HttpContractModel):
    id: str
    title: str
    author: str | None = None
    cover_url: str = Field(alias="coverUrl")
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    progress: float = Field(ge=0, le=100)


class BookSearchSummary(BookSummary):
    pass


class ManagementBookSummary(HttpContractModel):
    id: str
    title: str
    author: str | None = None
    library_id: str = Field(alias="libraryId")
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    series_name: str | None = Field(alias="seriesName")
    curation_state: str = Field(alias="curationState")
    visibility_state: str = Field(alias="visibilityState")
    updated_at: datetime = Field(alias="updatedAt")


class BookshelfBookSummary(HttpContractModel):
    """The lightweight projection used by the Web bookshelf grid."""

    id: str
    title: str
    author: str | None = None
    cover_url: str = Field(alias="coverUrl")
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    progress: float = Field(ge=0, le=100)


class ManagementBookListSummary(HttpContractModel):
    """The metadata/progress projection used by the Web management table."""

    id: str
    title: str
    author: str | None = None
    gradient: str = ""
    cover_status: str = Field(alias="coverStatus")
    cover_url: str = Field(alias="coverUrl")
    series_name: str | None = Field(default=None, alias="seriesName")
    tags: list[str] = Field(default_factory=list)
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    status_value: Literal["UNREAD", "READING", "FINISHED"] = Field(alias="statusValue")
    last_read_at: datetime | None = Field(default=None, alias="lastReadAt")
    imported_at: datetime | None = Field(default=None, alias="importedAt")


class DashboardSummaryPayload(HttpContractModel):
    total_books: int = Field(alias="totalBooks")
    ebook_books: int = Field(alias="ebookBooks")
    comic_books: int = Field(alias="comicBooks")
    audiobook_books: int = Field(alias="audiobookBooks")
    storage_used_bytes: int = Field(alias="storageUsedBytes")
    library_count: int = Field(alias="libraryCount")
    last_import_at: datetime | None = Field(alias="lastImportAt")
    latest_sync_at: datetime | None = Field(alias="latestSyncAt")


class ContinueReadingItem(HttpContractModel):
    book_id: str = Field(alias="bookId")
    title: str
    author: str | None = None
    cover_url: str = Field(alias="coverUrl")
    media_kind: MediaKind = Field(alias="mediaKind")
    resource_format: str = Field(alias="resourceFormat")
    reader_type: Literal["reflowable", "comic", "pdf", "audio"] = Field(
        alias="readerType"
    )
    resource_id: str = Field(alias="resourceId")
    resource_title: str = Field(alias="resourceTitle")
    percent: float = Field(ge=0, le=100)
    updated_at: datetime | None = Field(alias="updatedAt")


class UpdateBookRequest(HttpContractModel):
    title: str | None = None
    author: str | None = None
    description: str | None = None
    series_name: str | None = Field(default=None, alias="seriesName")
    series_index: float | None = Field(default=None, alias="seriesIndex")
    visibility_state: str | None = Field(default=None, alias="visibilityState")
    curation_state: str | None = Field(default=None, alias="curationState")
    publication_status: str | None = Field(default=None, alias="publicationStatus")
    tracking_status: str | None = Field(default=None, alias="trackingStatus")


class UpdateResourceRequest(HttpContractModel):
    title: str | None = None
    description: str | None = None
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    identifier: str | None = None
    isbn: str | None = None
    narrator: str | None = None
    abridged: bool | None = None
    resource_index: float | None = Field(default=None, alias="resourceIndex")


class ResourceSourceDeleteRequest(HttpContractModel):
    confirmation: str


class ReclassifyResourceRequest(HttpContractModel):
    target_media_kind: MediaKind = Field(alias="targetMediaKind")
    apply_to: Literal["RESOURCE", "SAME_MEDIA_KIND"] = Field(alias="applyTo")


class ResourceBatchRequest(HttpContractModel):
    action: Literal["SET_MEDIA_KIND"]
    resource_ids: list[str] = Field(alias="resourceIds", min_length=1)
    target_media_kind: MediaKind = Field(alias="targetMediaKind")


class BooksPayload(HttpContractModel):
    books: list[BookView | BookshelfBookSummary | ManagementBookListSummary]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class BookPayload(HttpContractModel):
    book: BookView


class ResourcesPayload(HttpContractModel):
    book_id: str = Field(alias="bookId")
    resources: list[ResourceView]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class ResourcePayload(HttpContractModel):
    resource: ResourceView


class AssetsPayload(HttpContractModel):
    resource_id: str = Field(alias="resourceId")
    assets: list[ResourceAssetView]
    page: int = 1
    page_size: int = Field(default=500, alias="pageSize")
    total: int = 0
    total_pages: int = Field(default=1, alias="totalPages")


class ResourceImportAcceptedPayload(HttpContractModel):
    resource_id: str = Field(alias="resourceId")
    accepted: Literal[True] = True
    task_id: str = Field(alias="taskId")


class ResourceDeletedPayload(HttpContractModel):
    resource_id: str = Field(alias="resourceId")
    deleted: Literal[True] = True


class AssetDeletedPayload(HttpContractModel):
    asset_id: str = Field(alias="assetId")
    deleted: Literal[True] = True


class ResourceOperationSummary(HttpContractModel):
    id: str
    action: str
    status: str
    summary: str
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    undo_available: bool = Field(alias="undoAvailable")


class ResourceReclassifyPayload(HttpContractModel):
    affected_resource_ids: list[str] = Field(alias="affectedResourceIds")
    operation: ResourceOperationSummary


class ResourceBatchPayload(HttpContractModel):
    affected_resource_ids: list[str] = Field(alias="affectedResourceIds")
    operation_ids: list[str] = Field(alias="operationIds")


class ReadingUnitView(HttpContractModel):
    id: str
    title: str
    href: str
    sort_order: int = Field(alias="sortOrder")
    unit_type: str = Field(alias="unitType")
    asset_id: str | None = Field(default=None, alias="assetId")
    metadata_json: str = Field(alias="metadataJson")


class ReadingUnitsPage(HttpContractModel):
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class ReadingUnitsPayload(HttpContractModel):
    book_id: str = Field(alias="bookId")
    resource_id: str = Field(alias="resourceId")
    units: list[ReadingUnitView]
    page: ReadingUnitsPage
    current_href: str | None = Field(default=None, alias="currentHref")
    current_chapter_index: int | None = Field(default=None, alias="currentChapterIndex")
    current_chapter_title: str | None = Field(default=None, alias="currentChapterTitle")
    current_chapter_sort_order: int | None = Field(
        default=None,
        alias="currentChapterSortOrder",
    )
    current_page_number: int | None = Field(default=None, alias="currentPageNumber")
    progress: float = Field(ge=0, le=100)


class BooksResponse(SuccessEnvelope[BooksPayload]):
    pass


class BookResponse(SuccessEnvelope[BookPayload]):
    pass


class ResourcesResponse(SuccessEnvelope[ResourcesPayload]):
    pass


class ResourceResponse(SuccessEnvelope[ResourcePayload]):
    pass


class AssetsResponse(SuccessEnvelope[AssetsPayload]):
    pass


class ResourceImportAcceptedResponse(SuccessEnvelope[ResourceImportAcceptedPayload]):
    pass


class ResourceDeletedResponse(SuccessEnvelope[ResourceDeletedPayload]):
    pass


class AssetDeletedResponse(SuccessEnvelope[AssetDeletedPayload]):
    pass


class ResourceReclassifyResponse(SuccessEnvelope[ResourceReclassifyPayload]):
    pass


class ResourceBatchResponse(SuccessEnvelope[ResourceBatchPayload]):
    pass


class ReadingUnitsResponse(SuccessEnvelope[ReadingUnitsPayload]):
    pass


class FilterSchemaResponse(SuccessEnvelope[FilterSchemaPayload]):
    pass


class FilterOptionsResponse(SuccessEnvelope[FilterOptionsPayload]):
    pass


class DashboardSummaryResponse(SuccessEnvelope[DashboardSummaryPayload]):
    pass


class ContinueReadingPayload(HttpContractModel):
    item: ContinueReadingItem | None


class ContinueReadingResponse(SuccessEnvelope[ContinueReadingPayload]):
    pass


__all__ = [name for name in globals() if not name.startswith("_")]
