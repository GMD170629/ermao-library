from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import UploadFile
from pydantic import Field
from typing_extensions import TypeAliasType

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import HttpContractError
from app.contracts.metadata_writeback import MetadataWritebackOperationContract
from app.contracts.system_events import SystemEvent
from app.modules.library.domain.layout import LibraryOrganizationMode

MediaKind = Literal["EBOOK", "COMIC", "AUDIOBOOK"]
ReadingStatus = Literal["UNREAD", "READING", "FINISHED"]
ScalarFilterValue = str | int | float | bool | None
FilterValue = ScalarFilterValue | list[str] | list[float]
MetadataCandidateRawValue = TypeAliasType(
    "MetadataCandidateRawValue",
    str
    | int
    | float
    | bool
    | None
    | list["MetadataCandidateRawValue"]
    | dict[str, "MetadataCandidateRawValue"],
)
RequestScalar = str | int | float | bool | None


class UpdateWorkRequest(HttpContractModel):
    title: RequestScalar = None
    author: RequestScalar = None
    description: RequestScalar = None
    publication_status: RequestScalar = Field(default=None, alias="publicationStatus")
    tracking_status: RequestScalar = Field(default=None, alias="trackingStatus")
    tags: list[RequestScalar] | str | None = None
    series_name: RequestScalar = Field(default=None, alias="seriesName")
    series_index: RequestScalar = Field(default=None, alias="seriesIndex")
    hidden: bool | None = None
    organized: bool | None = None
    metadata_quality: RequestScalar = Field(default=None, alias="metadataQuality")
    ignored: bool | None = None


class BulkFindReplaceRequest(HttpContractModel):
    ids: list[RequestScalar] | None = None
    book_ids: list[RequestScalar] | None = Field(default=None, alias="bookIds")
    field: str | None = None
    find: str | None = None
    replacement: str | None = None
    regex: bool | None = None
    case_sensitive: bool | None = Field(default=None, alias="caseSensitive")
    start_number: int | None = Field(default=None, alias="startNumber")


class BulkWorkRequest(BulkFindReplaceRequest):
    action: str | None = None
    ignored: bool | None = None
    tags: list[RequestScalar] | None = None
    status: str | None = None
    shelf_id: str | None = Field(default=None, alias="shelfId")
    membership: str | None = None
    fields: dict[str, RequestScalar] | None = None
    add_tags: list[RequestScalar] | None = Field(default=None, alias="addTags")
    remove_tags: list[RequestScalar] | None = Field(default=None, alias="removeTags")


class BulkCoverRequest(HttpContractModel):
    ids: str
    action: str
    ratio: str = "2:3"
    max_dimension: int = Field(default=1600, alias="maxDimension")
    quality: int = 82
    cover: UploadFile | None = None


class RenameCategoryRequest(HttpContractModel):
    name: str


class MergeCategoriesRequest(HttpContractModel):
    kind: str = "TAG"
    source_ids: list[str] = Field(alias="sourceIds")
    target_id: str = Field(alias="targetId")


class MetadataSearchRequest(HttpContractModel):
    provider_id: str | None = Field(default=None, alias="providerId")
    source: str | None = None
    query: str | None = None


class ProgressNavigation(HttpContractModel):
    cfi: str | None = None
    current_href: str | None = Field(default=None, alias="currentHref")
    current_section_index: int | None = Field(default=None, alias="currentSectionIndex")
    current_chapter_title: str | None = Field(default=None, alias="currentChapterTitle")
    current_chapter_index: int | None = Field(default=None, alias="currentChapterIndex")
    current_page_number: int | None = Field(default=None, alias="currentPageNumber")
    current_chapter_sort_order: int | None = Field(
        default=None,
        alias="currentChapterSortOrder",
    )
    page_index: int | None = Field(default=None, alias="pageIndex")
    total_pages: int | None = Field(default=None, alias="totalPages")
    file_id: str | None = Field(default=None, alias="fileId")
    chapter_id: str | None = Field(default=None, alias="chapterId")
    position_ms: int | None = Field(default=None, alias="positionMs")
    volume_id: str | None = Field(default=None, alias="volumeId")
    progress_estimated: bool = Field(default=False, alias="progressEstimated")


class ProgressExtra(HttpContractModel):
    cfi: str | None = None
    progression: float | None = None
    navigation_key: str | None = Field(default=None, alias="navigationKey")
    navigation_fingerprint: str | None = Field(
        default=None,
        alias="navigationFingerprint",
    )
    source_format: (
        Literal["epub", "mobi", "azw", "azw3", "prc", "fb2", "txt"] | None
    ) = Field(
        default=None,
        alias="sourceFormat",
    )
    file_id: str | None = Field(default=None, alias="fileId")
    chapter_id: str | None = Field(default=None, alias="chapterId")
    position_ms: int | None = Field(default=None, alias="positionMs")
    volume_id: str | None = Field(default=None, alias="volumeId")
    page_index: int | float | None = Field(default=None, alias="pageIndex")
    chapter_href: str | None = Field(default=None, alias="chapterHref")
    current_href: str | None = Field(default=None, alias="currentHref")
    chapter_section_index: int | float | None = Field(
        default=None,
        alias="chapterSectionIndex",
    )
    section_index: int | float | None = Field(default=None, alias="sectionIndex")
    chapter_index: int | float | None = Field(default=None, alias="chapterIndex")
    chapter_sort_order: int | float | None = Field(
        default=None,
        alias="chapterSortOrder",
    )
    chapter_title: str | None = Field(default=None, alias="chapterTitle")
    section_page: int | float | None = Field(default=None, alias="sectionPage")
    section_total_pages: int | float | None = Field(
        default=None,
        alias="sectionTotalPages",
    )
    section_total: int | float | None = Field(default=None, alias="sectionTotal")
    location_current: int | float | None = Field(default=None, alias="locationCurrent")
    location_next: int | float | None = Field(default=None, alias="locationNext")
    location_total: int | float | None = Field(default=None, alias="locationTotal")
    remaining_section_seconds: int | float | None = Field(
        default=None,
        alias="remainingSectionSeconds",
    )
    remaining_total_seconds: int | float | None = Field(
        default=None,
        alias="remainingTotalSeconds",
    )
    progress_estimated: bool | None = Field(default=None, alias="progressEstimated")


class LibraryFile(HttpContractModel):
    id: str
    volume_id: str = Field(alias="volumeId")
    path: str
    mime_type: str = Field(alias="mimeType")
    kind: str
    sort_order: int = Field(alias="sortOrder")
    size_bytes: int = Field(alias="sizeBytes")
    size: str
    duration_ms: int | None = Field(default=None, alias="durationMs")
    codec: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = Field(default=None, alias="sampleRate")
    channels: int | None = None
    disc_number: int | None = Field(default=None, alias="discNumber")
    track_number: int | None = Field(default=None, alias="trackNumber")
    url: str | None = None


class LibraryFileSummary(HttpContractModel):
    id: str
    path: str
    size_bytes: int = Field(alias="sizeBytes")
    size: str


class VolumeClassification(HttpContractModel):
    source: Literal["AUTO", "MONITOR_FOLDER", "USER", "INHERITED", "LEGACY"]
    reason: str
    suggested_media_kind: MediaKind | None = Field(
        default=None, alias="suggestedMediaKind"
    )


class LibraryVolume(HttpContractModel):
    id: str
    version_id: str = Field(alias="versionId")
    title: str
    volume_index: float | None = Field(default=None, alias="volumeIndex")
    sort_order: int = Field(alias="sortOrder")
    format: str
    reader_type: Literal["reflowable", "comic", "pdf", "audio"] = Field(
        alias="readerType"
    )
    classification: VolumeClassification
    readable: bool
    kindle_send_available: bool = Field(alias="kindleSendAvailable")
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    isbn: str | None = None
    identifier: str | None = None
    narrator: str | None = None
    abridged: bool | None = None
    origin: str
    import_status: str = Field(alias="importStatus")
    import_error: str | None = Field(default=None, alias="importError")
    cover_status: str = Field(alias="coverStatus")
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    track_count: int | None = Field(default=None, alias="trackCount")
    size_bytes: int = Field(alias="sizeBytes")
    cover_url: str = Field(alias="coverUrl")
    progress: float = 0
    completed: bool
    last_read_at: datetime | None = Field(default=None, alias="lastReadAt")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    files: list[LibraryFile]


class WorkDetailVolume(HttpContractModel):
    id: str
    version_id: str = Field(alias="versionId")
    title: str
    volume_index: float | None = Field(default=None, alias="volumeIndex")
    sort_order: int = Field(alias="sortOrder")
    format: str
    reader_type: Literal["reflowable", "comic", "pdf", "audio"] = Field(
        alias="readerType"
    )
    classification: VolumeClassification
    readable: bool
    kindle_send_available: bool = Field(alias="kindleSendAvailable")
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    isbn: str | None = None
    identifier: str | None = None
    narrator: str | None = None
    cover_url: str = Field(alias="coverUrl")
    size_bytes: int = Field(alias="sizeBytes")
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    track_count: int | None = Field(default=None, alias="trackCount")
    progress: float
    files: list[LibraryFileSummary]


class WorkDetailVersion(HttpContractModel):
    id: str
    source_key: str = Field(alias="sourceKey")
    source_name: str | None = Field(default=None, alias="sourceName")
    completed: bool
    volume_count: int = Field(alias="volumeCount")
    size_bytes: int = Field(alias="sizeBytes")
    volumes: list[WorkDetailVolume]


class WorkVersion(HttpContractModel):
    id: str
    source_key: str = Field(alias="sourceKey")
    source_name: str | None = Field(default=None, alias="sourceName")
    completed: bool
    volume_count: int = Field(alias="volumeCount")
    size_bytes: int = Field(alias="sizeBytes")
    volumes: list[LibraryVolume]


class LibraryFacetReferenceView(HttpContractModel):
    id: str
    kind: Literal["AUTHOR", "SERIES"]
    name: str


class WorkDetailBook(HttpContractModel):
    id: str
    title: str
    author: str
    description: str | None = None
    tags: list[str]
    series_name: str | None = Field(default=None, alias="seriesName")
    series_index: float | None = Field(default=None, alias="seriesIndex")
    series_facet: LibraryFacetReferenceView | None = Field(
        default=None, alias="seriesFacet"
    )
    author_facets: list[LibraryFacetReferenceView] = Field(
        default_factory=list, alias="authorFacets"
    )
    cover_status: str = Field(alias="coverStatus")
    cover_url: str = Field(alias="coverUrl")
    continue_volume_id: str | None = Field(alias="continueVolumeId")
    continue_volume_progress: float = Field(alias="continueVolumeProgress")
    completed: bool
    versions: list[WorkDetailVersion]


class WorkView(HttpContractModel):
    id: str
    title: str
    author: str
    description: str | None = None
    publication_status: str = Field(alias="publicationStatus")
    tracking_status: str = Field(alias="trackingStatus")
    tags: list[str]
    series_name: str | None = Field(default=None, alias="seriesName")
    series_index: float | None = Field(default=None, alias="seriesIndex")
    series_facet: LibraryFacetReferenceView | None = Field(
        default=None, alias="seriesFacet"
    )
    author_facets: list[LibraryFacetReferenceView] = Field(
        default_factory=list, alias="authorFacets"
    )
    organized: bool
    organize_status: str = Field(alias="organizeStatus")
    metadata_quality: int = Field(alias="metadataQuality")
    metadata_lookup_status: str | None = Field(
        default=None, alias="metadataLookupStatus"
    )
    metadata_lookup_source: str | None = Field(
        default=None, alias="metadataLookupSource"
    )
    metadata_lookup_error: str | None = Field(default=None, alias="metadataLookupError")
    cover_status: str = Field(alias="coverStatus")
    cover_url: str = Field(alias="coverUrl")
    continue_volume_id: str | None = Field(alias="continueVolumeId")
    continue_volume_title: str | None = Field(alias="continueVolumeTitle")
    continue_volume_progress: float = Field(alias="continueVolumeProgress")
    completed: bool
    last_read_at: datetime | None = Field(alias="lastReadAt")
    added_at: datetime | None = Field(alias="addedAt")
    versions: list[WorkVersion]
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")


class WorkSummary(HttpContractModel):
    id: str
    title: str
    author: str
    cover_url: str = Field(alias="coverUrl")
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    progress: float = Field(ge=0, le=100)


class WorkSearchSummary(WorkSummary):
    pass


class ManagementWorkSummary(HttpContractModel):
    id: str
    title: str
    author: str
    library_id: str | None = Field(alias="libraryId")
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    series_name: str | None = Field(alias="seriesName")
    organize_status: str | None = Field(alias="organizeStatus")
    hidden: bool
    updated_at: datetime | None = Field(alias="updatedAt")
    size_bytes: int = Field(default=0, alias="sizeBytes")
    volume_count: int = Field(default=0, alias="volumeCount")


class ManagementListWorkSummary(HttpContractModel):
    id: str
    title: str
    author: str
    gradient: str
    cover_status: str = Field(alias="coverStatus")
    cover_url: str = Field(alias="coverUrl")
    series_name: str | None = Field(alias="seriesName")
    tags: list[str]
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    status_value: ReadingStatus = Field(alias="statusValue")
    last_read_at: datetime | None = Field(alias="lastReadAt")
    imported_at: datetime | None = Field(alias="importedAt")


WorkListItem = WorkView | WorkSummary | WorkSearchSummary | ManagementListWorkSummary


class DashboardSummaryPayload(HttpContractModel):
    total_books: int = Field(alias="totalBooks")
    ebook_books: int = Field(alias="ebookBooks")
    comic_books: int = Field(alias="comicBooks")
    audiobook_books: int = Field(alias="audiobookBooks")
    storage_used_bytes: int = Field(alias="storageUsedBytes")
    library_count: int = Field(alias="libraryCount")
    last_import_at: datetime | None = Field(alias="lastImportAt")
    latest_sync_at: datetime | None = Field(alias="latestSyncAt")


class WorkSummariesPayload(HttpContractModel):
    books: list[WorkSummary]


class ContinueReadingItem(HttpContractModel):
    work_id: str = Field(alias="workId")
    title: str
    author: str
    cover_url: str = Field(alias="coverUrl")
    media_kind: MediaKind = Field(alias="mediaKind")
    volume_format: str = Field(alias="volumeFormat")
    reader_type: Literal["reflowable", "comic", "pdf", "audio"] = Field(
        alias="readerType"
    )
    resume_volume_id: str | None = Field(alias="resumeVolumeId")
    progress: float
    chapter: str | None
    last_read_at: datetime | None = Field(alias="lastReadAt")
    volume_title: str | None = Field(alias="volumeTitle")
    narrator: str | None


class ContinueReadingPayload(HttpContractModel):
    item: ContinueReadingItem | None


class ManagementCards(HttpContractModel):
    failed_imports: int = Field(alias="failedImports")
    failed_downloads: int = Field(alias="failedDownloads")
    orphan_files: int = Field(alias="orphanFiles")
    pending_organize: int = Field(alias="pendingOrganize")
    managed_storage_bytes: int = Field(alias="managedStorageBytes")
    event_log_size_bytes: int = Field(alias="eventLogSizeBytes")
    event_log_max_bytes: int = Field(alias="eventLogMaxBytes")


class ManagementCheck(HttpContractModel):
    name: str | None = None
    status: str
    message: str


class ManagementChecks(HttpContractModel):
    database: ManagementCheck
    monitor_root_readable: ManagementCheck = Field(alias="monitorRootReadable")
    storage_writable: ManagementCheck = Field(alias="storageWritable")


class ManagementOverviewPayload(HttpContractModel):
    cards: ManagementCards
    checks: ManagementChecks
    recent_events: list[SystemEvent] = Field(alias="recentEvents")


class SourceFolderChild(HttpContractModel):
    name: str
    path: str
    type: Literal["folder", "file", "unknown"]
    size_bytes: int = Field(alias="sizeBytes")
    mtime_ms: int | None = Field(default=None, alias="mtimeMs")
    error: str | None = None


class SourceFolderNode(HttpContractModel):
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
    readable: bool
    writable: bool
    children: list[SourceFolderChild]


class LogicalFolderGroup(HttpContractModel):
    name: str
    count: int
    size_bytes: int = Field(alias="sizeBytes")
    items: list[ManagementWorkSummary]


class LogicalFolders(HttpContractModel):
    series: list[LogicalFolderGroup]
    authors: list[LogicalFolderGroup]
    formats: list[LogicalFolderGroup]
    sources: list[LogicalFolderGroup]


class PathTreeNode(HttpContractModel):
    name: str
    type: Literal["folder", "file"]
    path: str
    children: list[PathTreeNode] = Field(default_factory=list)
    file_count: int = Field(alias="fileCount")
    size_bytes: int = Field(alias="sizeBytes")


class ManagedDiskTree(HttpContractModel):
    root_path: str = Field(alias="rootPath")
    tree: PathTreeNode


class DiskFolders(HttpContractModel):
    sources: list[SourceFolderNode]
    managed: ManagedDiskTree


class ManagementFoldersPayload(HttpContractModel):
    logical: LogicalFolders
    disk: DiskFolders
    works: list[ManagementWorkSummary]


class SeriesSummary(HttpContractModel):
    name: str
    book_count: int = Field(alias="bookCount")
    latest_updated_at: datetime | None = Field(alias="latestUpdatedAt")


class SeriesPayload(HttpContractModel):
    series: list[SeriesSummary]
    total: int


class LibraryRepresentativeWork(HttpContractModel):
    id: str
    title: str
    author: str
    cover_url: str = Field(alias="coverUrl")


class LibraryGroupingSummary(HttpContractModel):
    id: str
    name: str
    book_count: int = Field(alias="bookCount")
    updated_at: datetime = Field(alias="updatedAt")
    representative_works: list[LibraryRepresentativeWork] = Field(
        default_factory=list, alias="representativeWorks"
    )


class LibraryGroupingsPayload(HttpContractModel):
    kind: Literal["SERIES", "AUTHOR"]
    groups: list[LibraryGroupingSummary]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class WorksPayload(HttpContractModel):
    books: list[WorkListItem]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")
    applied_facet: LibraryFacetReferenceView | None = Field(
        default=None, alias="appliedFacet"
    )


class ReadingUnitMetadata(HttpContractModel):
    exact_navigation: bool | None = Field(default=None, alias="exactNavigation")
    level: int | None = Field(default=None, ge=0)
    path: list[int] | None = None
    navigation_key: str | None = Field(default=None, alias="navigationKey")
    zip_entry_name: str | None = Field(default=None, alias="zipEntryName")
    idref: str | None = None
    linear: bool | None = None
    properties: list[str] | None = None
    volume_index: float | None = Field(default=None, alias="volumeIndex")
    track_index: int | None = Field(default=None, alias="trackIndex")
    page_number: int | None = Field(default=None, alias="pageNumber")
    original_name: str | None = Field(default=None, alias="originalName")
    page_in_volume: int | None = Field(default=None, ge=1, alias="pageInVolume")
    page_in_section: int | None = Field(default=None, ge=1, alias="pageInSection")
    source_file_name: str | None = Field(default=None, alias="sourceFileName")
    href_base: Literal["publication-root"] | None = Field(
        default=None,
        alias="hrefBase",
    )
    recovered: bool | None = None
    reading_order_position: int | None = Field(
        default=None,
        ge=1,
        alias="readingOrderPosition",
    )


class ReadingUnit(HttpContractModel):
    id: str
    volume_id: str = Field(alias="volumeId")
    file_id: str | None = Field(alias="fileId")
    unit_type: str = Field(alias="unitType")
    title: str | None
    href: str | None
    media_type: str | None = Field(alias="mediaType")
    sort_order: int = Field(alias="sortOrder")
    start_ms: int | None = Field(default=None, alias="startMs")
    end_ms: int | None = Field(default=None, alias="endMs")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    width: int | None = None
    height: int | None = None
    size: int | None = None
    metadata_json: ReadingUnitMetadata = Field(alias="metadataJson")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class ReadingUnitsPage(HttpContractModel):
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class VolumeSection(HttpContractModel):
    id: str
    version_id: str = Field(alias="versionId")
    title: str
    index: float
    file_id: str = Field(alias="fileId")
    page_count: int = Field(alias="pageCount")
    cover_url: str = Field(alias="coverUrl")
    progress: float
    last_read_at: datetime | None = Field(alias="lastReadAt")
    position: str | None
    current_page: int | None = Field(alias="currentPage")
    current_href: str | None = Field(default=None, alias="currentHref")
    current_section_index: int | None = Field(default=None, alias="currentSectionIndex")
    current_chapter_title: str | None = Field(default=None, alias="currentChapterTitle")
    current_chapter_index: int | None = Field(default=None, alias="currentChapterIndex")
    current_chapter_sort_order: int | None = Field(
        default=None,
        alias="currentChapterSortOrder",
    )
    progress_extra: ProgressExtra = Field(alias="progressExtra")
    progress_estimated: bool = Field(default=False, alias="progressEstimated")


class WorkPayload(HttpContractModel):
    book: WorkView | None


class WorkDetailSummaryPayload(HttpContractModel):
    book: WorkDetailBook


class WorkVolumePagePayload(HttpContractModel):
    version_id: str = Field(alias="versionId")
    source_key: str = Field(alias="sourceKey")
    source_name: str | None = Field(default=None, alias="sourceName")
    volumes: list[WorkDetailVolume]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class WorkReadingUnitsPayload(HttpContractModel):
    units: list[ReadingUnit]
    page: ReadingUnitsPage
    progress: float
    current_href: str | None = Field(default=None, alias="currentHref")
    current_chapter_index: int | None = Field(default=None, alias="currentChapterIndex")
    current_chapter_title: str | None = Field(
        default=None,
        alias="currentChapterTitle",
    )
    current_chapter_sort_order: int | None = Field(
        default=None, alias="currentChapterSortOrder"
    )
    current_page_number: int | float | None = Field(
        default=None, alias="currentPageNumber"
    )


class BulkUpdatePayload(HttpContractModel):
    updated: int
    ids: list[str]
    changed_values: int | None = Field(default=None, alias="changedValues")
    status: str | None = None


class BulkCoverPayload(HttpContractModel):
    updated: int
    ids: list[str]
    skipped: list[str]


BulkMutationPayload = BulkUpdatePayload | BulkCoverPayload


class FindReplacePreviewItem(HttpContractModel):
    work_id: str = Field(alias="workId")
    title: str
    target_id: str = Field(alias="targetId")
    table: str
    column: str
    before: str | list[str]
    after: str | list[str]


class FindReplacePreviewPayload(HttpContractModel):
    changed_works: int = Field(alias="changedWorks")
    changed_values: int = Field(alias="changedValues")
    items: list[FindReplacePreviewItem]


class CoverMutationPayload(HttpContractModel):
    book_id: str = Field(alias="bookId")
    cover_url: str = Field(alias="coverUrl")


class NamedCount(HttpContractModel):
    value: str
    label: str
    count: int


class FilterCondition(HttpContractModel):
    field: str
    operator: str
    value: FilterValue = None


class FilterOption(HttpContractModel):
    value: str
    label: str
    count: int | None = None
    root_path: str | None = Field(default=None, alias="rootPath")


class FilterSuggestionOption(HttpContractModel):
    value: str
    label: str
    count: int


class FilterFieldDefinition(HttpContractModel):
    key: str
    label: str
    group: str
    type: Literal["text", "select", "number", "date", "boolean"]
    operators: list[str]
    option_source: str | None = Field(default=None, alias="optionSource")
    allow_custom: bool | None = Field(default=None, alias="allowCustom")
    unit: str | None = None
    value_scale: int | None = Field(default=None, alias="valueScale")
    options: list[FilterOption] = Field(default_factory=list)


class FilterSchemaPayload(HttpContractModel):
    fields: list[FilterFieldDefinition]
    max_conditions: int = Field(alias="maxConditions")


class FilterOptionsPayload(HttpContractModel):
    source: Literal["authors", "tags", "series"]
    query: str
    options: list[FilterSuggestionOption]
    has_more: bool = Field(alias="hasMore")
    index_ready: bool = Field(alias="indexReady")


class LibraryCategory(HttpContractModel):
    id: str
    kind: str
    name: str
    normalized_name: str = Field(alias="normalizedName")
    aliases: list[str]
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    book_count: int = Field(alias="bookCount")


class FacetGroups(HttpContractModel):
    author: list[LibraryCategory]
    tag: list[LibraryCategory]
    series: list[LibraryCategory]


class FacetsPayload(HttpContractModel):
    facets: FacetGroups
    statuses: list[NamedCount]
    media_kinds: list[NamedCount] = Field(alias="mediaKinds")


class CategoriesPayload(HttpContractModel):
    categories: list[LibraryCategory]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class LibraryOperationSummary(HttpContractModel):
    id: str
    action: str
    status: str
    summary: str
    target_type: str | None = Field(default=None, alias="targetType")
    target_id: str | None = Field(default=None, alias="targetId")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    undone_at: datetime | None = Field(default=None, alias="undoneAt")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    undo_available: bool = Field(alias="undoAvailable")


class RenameCategoryPayload(HttpContractModel):
    facet_id: str = Field(alias="facetId")
    name: str
    operation: LibraryOperationSummary


class MergeCategoriesPayload(HttpContractModel):
    target_id: str = Field(alias="targetId")
    merged_ids: list[str] = Field(alias="mergedIds")
    operation: LibraryOperationSummary


class DeleteCategoryPayload(HttpContractModel):
    facet_id: str = Field(alias="facetId")
    kind: str
    name: str
    affected_book_count: int = Field(alias="affectedBookCount")
    operation: LibraryOperationSummary


class OperationsPayload(HttpContractModel):
    operations: list[LibraryOperationSummary]


class UndoOperationPayload(HttpContractModel):
    operation: LibraryOperationSummary
    restored: bool


class MetadataCandidateVolume(HttpContractModel):
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    isbn: str | None = None


class MetadataCandidate(HttpContractModel):
    id: str
    source: str
    external_id: str | None = Field(default=None, alias="externalId")
    title: str | None
    title_aliases: list[str] | None = Field(default=None, alias="titleAliases")
    author: str | None = None
    volume_metadata: MetadataCandidateVolume | None = Field(
        default=None, alias="volumeMetadata"
    )
    description: str | None = None
    cover_url: str | None = Field(default=None, alias="coverUrl")
    score: float | None = None
    tags: list[str] | None = None
    series_name: str | None = Field(default=None, alias="seriesName")
    series_index: float | None = Field(default=None, alias="seriesIndex")
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    isbn: str | None = None
    confidence: float
    raw: dict[str, MetadataCandidateRawValue]


class MetadataSearchPayload(HttpContractModel):
    candidates: list[MetadataCandidate]
    results: list[MetadataCandidate]
    query: str
    source: str | None
    message: str | None


MetadataApplyField = Literal[
    "coverUrl",
    "title",
    "author",
    "description",
    "tags",
    "seriesName",
    "seriesIndex",
    "publisher",
    "publishedAt",
    "language",
    "isbn",
]


class MetadataApplyCandidate(HttpContractModel):
    id: str | None = None
    source: str | None = None
    external_id: str | None = Field(default=None, alias="externalId")
    title: str | None = None
    title_aliases: list[str] | None = Field(default=None, alias="titleAliases")
    author: str | None = None
    volume_metadata: MetadataCandidateVolume | None = Field(
        default=None, alias="volumeMetadata"
    )
    description: str | None = None
    cover_url: str | None = Field(default=None, alias="coverUrl")
    score: float | None = None
    tags: list[str] | None = None
    series_name: str | None = Field(default=None, alias="seriesName")
    series_index: float | None = Field(default=None, alias="seriesIndex")
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    isbn: str | None = None
    confidence: float | None = None
    raw: dict[str, MetadataCandidateRawValue] | None = None


class MetadataApplyRequest(HttpContractModel):
    source: str | None = None
    candidate: MetadataApplyCandidate
    fields: list[MetadataApplyField] = Field(min_length=1)
    version_id: str | None = Field(default=None, alias="versionId")
    volume_id: str | None = Field(default=None, alias="volumeId")
    write_metadata_to_files: bool = Field(default=False, alias="writeMetadataToFiles")


class UpdateVolumeRequest(HttpContractModel):
    description: str | None = None
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    identifier: str | None = None
    isbn: str | None = None
    narrator: str | None = None
    abridged: bool | None = None


class ReclassifyVolumeRequest(HttpContractModel):
    target_media_kind: str = Field(alias="targetMediaKind", min_length=1)
    apply_to: Literal["VOLUME", "SAME_MEDIA_KIND"] = Field(alias="applyTo")


class BatchSetMediaKindRequest(HttpContractModel):
    action: Literal["SET_MEDIA_KIND"]
    volume_ids: list[str] = Field(alias="volumeIds", min_length=1)
    target_media_kind: MediaKind = Field(alias="targetMediaKind")


BatchVolumeRequest = BatchSetMediaKindRequest


class BatchVolumeMutationPayload(HttpContractModel):
    book: WorkView | None
    work_id: str = Field(alias="workId")
    affected_volume_ids: list[str] = Field(alias="affectedVolumeIds")
    operation_ids: list[str] = Field(alias="operationIds")


class VolumeMetadataMutationPayload(HttpContractModel):
    book: WorkView | None
    work_id: str = Field(alias="workId")
    volume_id: str = Field(alias="volumeId")


class ReclassifyVolumePayload(HttpContractModel):
    moved_volume_ids: list[str] = Field(alias="movedVolumeIds")
    operation: LibraryOperationSummary


class MetadataApplyPayload(HttpContractModel):
    book: WorkView
    applied_fields: list[str] = Field(alias="appliedFields")
    finished_organize_job_ids: list[str] = Field(alias="finishedOrganizeJobIds")
    metadata_writeback: MetadataWritebackOperationContract | None = Field(
        default=None, alias="metadataWriteback"
    )


DashboardSummaryResponse = SuccessEnvelope[DashboardSummaryPayload]
WorkSummariesResponse = SuccessEnvelope[WorkSummariesPayload]
ContinueReadingResponse = SuccessEnvelope[ContinueReadingPayload]
ManagementOverviewResponse = SuccessEnvelope[ManagementOverviewPayload]
ManagementFoldersResponse = SuccessEnvelope[ManagementFoldersPayload]
SeriesResponse = SuccessEnvelope[SeriesPayload]
LibraryGroupingsResponse = SuccessEnvelope[LibraryGroupingsPayload]
WorksResponse = SuccessEnvelope[WorksPayload]
WorkResponse = SuccessEnvelope[WorkPayload]
WorkDetailSummaryResponse = SuccessEnvelope[WorkDetailSummaryPayload]
WorkVolumePageResponse = SuccessEnvelope[WorkVolumePagePayload]
WorkReadingUnitsResponse = SuccessEnvelope[WorkReadingUnitsPayload]
BulkMutationResponse = SuccessEnvelope[BulkMutationPayload]
FindReplacePreviewResponse = SuccessEnvelope[FindReplacePreviewPayload]
CoverMutationResponse = SuccessEnvelope[CoverMutationPayload]
FacetsResponse = SuccessEnvelope[FacetsPayload]
FilterSchemaResponse = SuccessEnvelope[FilterSchemaPayload]
FilterOptionsResponse = SuccessEnvelope[FilterOptionsPayload]
CategoriesResponse = SuccessEnvelope[CategoriesPayload]
RenameCategoryResponse = SuccessEnvelope[RenameCategoryPayload]
MergeCategoriesResponse = SuccessEnvelope[MergeCategoriesPayload]
DeleteCategoryResponse = SuccessEnvelope[DeleteCategoryPayload]
OperationsResponse = SuccessEnvelope[OperationsPayload]
UndoOperationResponse = SuccessEnvelope[UndoOperationPayload]
MetadataSearchResponse = SuccessEnvelope[MetadataSearchPayload]
MetadataApplyResponse = SuccessEnvelope[MetadataApplyPayload]
VolumeMetadataMutationResponse = SuccessEnvelope[VolumeMetadataMutationPayload]
ReclassifyVolumeResponse = SuccessEnvelope[ReclassifyVolumePayload]
BatchVolumeMutationResponse = SuccessEnvelope[BatchVolumeMutationPayload]


class LibraryErrorBody(HttpContractModel):
    message: str
    code: str | None = None


class LibraryBadRequestError(HttpContractError[LibraryErrorBody]):
    status_code = 400
    body_model = LibraryErrorBody


class LibraryForbiddenError(HttpContractError[LibraryErrorBody]):
    status_code = 403
    body_model = LibraryErrorBody


class LibraryNotFoundError(HttpContractError[LibraryErrorBody]):
    status_code = 404
    body_model = LibraryErrorBody


class LibraryConflictError(HttpContractError[LibraryErrorBody]):
    status_code = 409
    body_model = LibraryErrorBody


class LibraryGoneError(HttpContractError[LibraryErrorBody]):
    status_code = 410
    body_model = LibraryErrorBody


class LibraryUnprocessableError(HttpContractError[LibraryErrorBody]):
    status_code = 422
    body_model = LibraryErrorBody


class LibraryUnavailableError(HttpContractError[LibraryErrorBody]):
    status_code = 503
    body_model = LibraryErrorBody
