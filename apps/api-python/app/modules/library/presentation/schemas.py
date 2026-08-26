"""Validated HTTP contracts for the Book/Resource/Asset library surface."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.library_views import (
    BookView,
    ResourceAssetView,
    ResourceImportSummary,
    ResourceView,
)
from app.modules.library.application.recognized_metadata import (
    MetadataTargetScope,
    RecognizedMetadataField,
)

FacetKind = Literal["AUTHOR", "TAG", "SERIES"]


class LibraryFacetView(HttpContractModel):
    id: str
    kind: FacetKind
    name: str
    normalized_name: str = Field(alias="normalizedName")
    aliases: list[str] = Field(default_factory=list)
    book_count: int = Field(alias="bookCount", ge=0)
    updated_at: datetime = Field(alias="updatedAt")


class LibraryFacetPagePayload(HttpContractModel):
    facets: list[LibraryFacetView]
    page: int = Field(ge=1)
    page_size: int = Field(alias="pageSize", ge=1)
    total: int = Field(ge=0)
    total_pages: int = Field(alias="totalPages", ge=1)


class LibraryOperationView(HttpContractModel):
    id: str
    action: str
    status: str
    summary: str
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    undo_available: bool = Field(alias="undoAvailable")


class MergeLibraryFacetsRequest(HttpContractModel):
    kind: FacetKind
    target_id: str = Field(alias="targetId", min_length=1)
    source_ids: list[str] = Field(alias="sourceIds", min_length=1)


class RenameLibraryFacetRequest(HttpContractModel):
    name: str = Field(min_length=1, max_length=500)


class LibraryFacetMergePayload(HttpContractModel):
    target_id: str = Field(alias="targetId")
    merged_ids: list[str] = Field(alias="mergedIds")
    operation: LibraryOperationView


class LibraryFacetRenamePayload(HttpContractModel):
    facet_id: str = Field(alias="facetId")
    name: str
    operation: LibraryOperationView


class LibraryFacetDeletePayload(HttpContractModel):
    facet_id: str = Field(alias="facetId")
    deleted: Literal[True] = True
    operation: LibraryOperationView


class LibraryOperationUndoPayload(HttpContractModel):
    operation: LibraryOperationView
    restored: Literal[True] = True


class LibraryGroupingBookView(HttpContractModel):
    id: str
    title: str
    author: str
    cover_url: str = Field(alias="coverUrl")
    updated_at: datetime = Field(alias="updatedAt")


class LibraryGroupingView(HttpContractModel):
    id: str
    name: str
    book_count: int = Field(alias="bookCount", ge=1)
    updated_at: datetime = Field(alias="updatedAt")
    representative_books: list[LibraryGroupingBookView] = Field(
        default_factory=list,
        alias="representativeBooks",
    )


class LibraryGroupingPagePayload(HttpContractModel):
    groups: list[LibraryGroupingView]
    page: int = Field(ge=1)
    page_size: int = Field(alias="pageSize", ge=1)
    total: int = Field(ge=0)
    total_pages: int = Field(alias="totalPages", ge=1)


class BulkBookMetadataRequest(HttpContractModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    fields: dict[str, str] = Field(default_factory=dict)
    add_tags: list[str] = Field(default_factory=list, alias="addTags")
    remove_tags: list[str] = Field(default_factory=list, alias="removeTags")


class BulkBookFindReplaceRequest(HttpContractModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    field: Literal[
        "title",
        "author",
        "description",
        "seriesName",
        "tags",
        "resourceTitle",
    ]
    find: str = Field(min_length=1, max_length=500)
    replacement: str = Field(max_length=10_000)
    regex: bool = False
    case_sensitive: bool = Field(default=False, alias="caseSensitive")
    start_number: int = Field(default=1, alias="startNumber", ge=1, le=1_000_000)


class BulkBookShelfMembershipRequest(HttpContractModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    shelf_id: str = Field(alias="shelfId", min_length=1)
    membership: Literal["ADD", "REMOVE"]


class BulkBookReadingStatusRequest(HttpContractModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    status: Literal["UNREAD", "FINISHED"]


class BulkBookSourceDeleteRequest(HttpContractModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    confirmation: Literal["DELETE_SOURCE_FILES"]


class BulkBookSourceDeletePayload(HttpContractModel):
    deleted: int = Field(ge=0)
    deleted_book_ids: list[str] = Field(alias="deletedBookIds")


class BulkBookOperationPayload(HttpContractModel):
    updated: int = Field(ge=0)
    changed_values: int = Field(alias="changedValues", ge=0)
    operation: LibraryOperationView


class BulkBookCoverSkipped(HttpContractModel):
    book_id: str = Field(alias="bookId")
    reason: str


class BulkBookCoverPayload(HttpContractModel):
    updated: int = Field(ge=0)
    skipped: list[BulkBookCoverSkipped]
    operation: LibraryOperationView


class BulkBookFindReplacePreviewItem(HttpContractModel):
    book_id: str = Field(alias="bookId")
    title: str
    before: str | list[str]
    after: str | list[str]
    resource_id: str | None = Field(default=None, alias="resourceId")


class BulkBookFindReplacePreviewPayload(HttpContractModel):
    changed_books: int = Field(alias="changedBooks", ge=0)
    changed_values: int = Field(alias="changedValues", ge=0)
    items: list[BulkBookFindReplacePreviewItem]


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


class BookSummary(HttpContractModel):
    id: str
    title: str
    author: str | None = None
    cover_url: str = Field(alias="coverUrl")
    progress: float = Field(ge=0, le=100)


class BookSearchSummary(BookSummary):
    pass


class ManagementBookSummary(HttpContractModel):
    id: str
    title: str
    author: str | None = None
    library_id: str = Field(alias="libraryId")
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
    resource_import_summary: ResourceImportSummary = Field(
        default_factory=ResourceImportSummary,
        alias="resourceImportSummary",
    )
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
    resource_import_summary: ResourceImportSummary = Field(
        default_factory=ResourceImportSummary,
        alias="resourceImportSummary",
    )
    status_value: Literal["UNREAD", "READING", "FINISHED"] = Field(alias="statusValue")
    last_read_at: datetime | None = Field(default=None, alias="lastReadAt")
    imported_at: datetime | None = Field(default=None, alias="importedAt")


class DashboardSummaryPayload(HttpContractModel):
    total_books: int = Field(alias="totalBooks")
    storage_used_bytes: int = Field(alias="storageUsedBytes")
    library_count: int = Field(alias="libraryCount")
    last_import_at: datetime | None = Field(alias="lastImportAt")
    latest_sync_at: datetime | None = Field(alias="latestSyncAt")


class ContinueReadingItem(HttpContractModel):
    book_id: str = Field(alias="bookId")
    title: str
    author: str | None = None
    cover_url: str = Field(alias="coverUrl")
    resource_format: str = Field(alias="resourceFormat")
    reader_type: Literal["reflowable", "comic", "pdf", "audio"] = Field(
        alias="readerType"
    )
    resume_resource_id: str = Field(alias="resumeResourceId")
    progress: float = Field(ge=0, le=100)
    last_read_at: datetime | None = Field(alias="lastReadAt")
    chapter: str | None = None
    resource_title: str | None = Field(default=None, alias="resourceTitle")
    narrator: str | None = None


class DashboardBooksPayload(HttpContractModel):
    books: list[BookshelfBookSummary]


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


class BookContentEntryView(HttpContractModel):
    source_node_id: str = Field(alias="sourceNodeId")
    parent_source_node_id: str | None = Field(alias="parentSourceNodeId")
    name: str
    title: str
    description: str | None = None
    kind: Literal["FOLDER", "FILE"]
    physical_kind: Literal["REGULAR_FILE", "DIRECTORY", "SYMLINK", "OTHER"] = Field(
        alias="physicalKind"
    )
    size_bytes: int | None = Field(default=None, alias="sizeBytes", ge=0)
    observed_at: datetime = Field(alias="observedAt")
    has_children: bool = Field(alias="hasChildren")
    resource_id: str | None = Field(default=None, alias="resourceId")
    representative_resource_id: str | None = Field(
        default=None,
        alias="representativeResourceId",
    )
    cover_url: str | None = Field(default=None, alias="coverUrl")


class BookContentsPayload(HttpContractModel):
    book_id: str = Field(alias="bookId")
    current_source_node_id: str | None = Field(alias="currentSourceNodeId")
    current_resource_id: str | None = Field(alias="currentResourceId")
    current_node: BookContentEntryView = Field(alias="currentNode")
    current_resource_ids: list[str] = Field(alias="currentResourceIds")
    parent_source_node_id: str | None = Field(alias="parentSourceNodeId")
    breadcrumbs: list[BookContentEntryView]
    entries: list[BookContentEntryView]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class UpdateSourceNodeMetadataRequest(HttpContractModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10_000)


class SourceNodeMetadataUpdatedPayload(HttpContractModel):
    source_node_id: str = Field(alias="sourceNodeId")
    updated: Literal[True] = True


class SourceNodeMetadataSearchRequest(HttpContractModel):
    provider_id: str = Field(alias="providerId", min_length=1, max_length=100)
    query: str | None = Field(default=None, max_length=500)


class SourceNodeMetadataCandidateView(HttpContractModel):
    id: str
    source: str
    title: str | None = None
    author: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    series_name: str | None = Field(default=None, alias="seriesName")
    series_index: float | None = Field(default=None, alias="seriesIndex")
    publisher: str | None = None
    published_at: str | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    isbn: str | None = None
    identifier: str | None = None
    narrator: str | None = None
    abridged: bool | None = None
    resource_index: float | None = Field(default=None, alias="resourceIndex")
    cover_url: str | None = Field(default=None, alias="coverUrl")
    confidence: float = 0


class SourceNodeMetadataSearchPayload(HttpContractModel):
    source_node_id: str = Field(alias="sourceNodeId")
    provider_id: str = Field(alias="providerId")
    query: str
    message: str | None = None
    candidates: list[SourceNodeMetadataCandidateView]


class RecognizedMetadataCandidateInput(HttpContractModel):
    id: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=1_000)
    description: str | None = Field(default=None, max_length=10_000)
    tags: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=100
    )
    series_name: str | None = Field(default=None, alias="seriesName", max_length=500)
    series_index: float | None = Field(
        default=None, alias="seriesIndex", allow_inf_nan=False
    )
    publisher: str | None = Field(default=None, max_length=1_000)
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = Field(default=None, max_length=64)
    isbn: str | None = Field(default=None, max_length=64)
    identifier: str | None = Field(default=None, max_length=1_000)
    narrator: str | None = Field(default=None, max_length=1_000)
    abridged: bool | None = Field(default=None, strict=True)
    resource_index: float | None = Field(
        default=None, alias="resourceIndex", allow_inf_nan=False
    )
    cover_url: str | None = Field(default=None, alias="coverUrl", max_length=2_000)
    confidence: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)


class ApplyRecognizedMetadataRequest(HttpContractModel):
    scope: MetadataTargetScope
    resource_id: str | None = Field(default=None, alias="resourceId", max_length=191)
    candidate: RecognizedMetadataCandidateInput
    fields: list[RecognizedMetadataField] = Field(min_length=1, max_length=18)


class ApplyRecognizedMetadataPayload(HttpContractModel):
    applied_fields: list[RecognizedMetadataField] = Field(alias="appliedFields")
    skipped_fields: list[RecognizedMetadataField] = Field(alias="skippedFields")
    cover_status: Literal["notSelected", "applied", "failed"] = Field(
        alias="coverStatus"
    )


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
    href: str | None = None
    sort_order: int = Field(alias="sortOrder")
    unit_type: str = Field(alias="unitType")
    asset_id: str | None = Field(default=None, alias="assetId")
    page_number: int | None = Field(default=None, alias="pageNumber")
    media_type: str | None = Field(default=None, alias="mediaType")
    preview_url: str | None = Field(default=None, alias="previewUrl")
    level: int | None = None
    duration_ms: int | None = Field(default=None, alias="durationMs")
    disc_number: int | None = Field(default=None, alias="discNumber")
    track_number: int | None = Field(default=None, alias="trackNumber")
    metadata_json: str = Field(default="{}", alias="metadataJson")


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


class BookContentsResponse(SuccessEnvelope[BookContentsPayload]):
    pass


class SourceNodeMetadataUpdatedResponse(
    SuccessEnvelope[SourceNodeMetadataUpdatedPayload]
):
    pass


class SourceNodeMetadataSearchResponse(
    SuccessEnvelope[SourceNodeMetadataSearchPayload]
):
    pass


class ApplyRecognizedMetadataResponse(SuccessEnvelope[ApplyRecognizedMetadataPayload]):
    pass


class ResourceResponse(SuccessEnvelope[ResourcePayload]):
    pass


class AssetsResponse(SuccessEnvelope[AssetsPayload]):
    pass


class ResourceImportAcceptedResponse(SuccessEnvelope[ResourceImportAcceptedPayload]):
    pass


class ResourceDeletedResponse(SuccessEnvelope[ResourceDeletedPayload]):
    pass


class BulkBookSourceDeleteResponse(SuccessEnvelope[BulkBookSourceDeletePayload]):
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


class DashboardBooksResponse(SuccessEnvelope[DashboardBooksPayload]):
    pass


class LibraryFacetPageResponse(SuccessEnvelope[LibraryFacetPagePayload]):
    pass


class LibraryFacetMergeResponse(SuccessEnvelope[LibraryFacetMergePayload]):
    pass


class LibraryFacetRenameResponse(SuccessEnvelope[LibraryFacetRenamePayload]):
    pass


class LibraryFacetDeleteResponse(SuccessEnvelope[LibraryFacetDeletePayload]):
    pass


class LibraryOperationUndoResponse(SuccessEnvelope[LibraryOperationUndoPayload]):
    pass


class LibraryGroupingPageResponse(SuccessEnvelope[LibraryGroupingPagePayload]):
    pass


class BulkBookOperationResponse(SuccessEnvelope[BulkBookOperationPayload]):
    pass


class BulkBookCoverResponse(SuccessEnvelope[BulkBookCoverPayload]):
    pass


class BulkBookFindReplacePreviewResponse(
    SuccessEnvelope[BulkBookFindReplacePreviewPayload]
):
    pass


__all__ = [name for name in globals() if not name.startswith("_")]
