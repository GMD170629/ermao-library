from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import HttpContractError
from app.contracts.imports import ImportTaskContract
from app.contracts.system_events import SystemEvent

MediaKind = Literal["EBOOK", "COMIC", "AUDIOBOOK"]
ReadingStatus = Literal["UNREAD", "READING", "FINISHED"]
DetailTabKey = Literal["EBOOK", "COMIC", "AUDIOBOOK", "STRUCTURE"]
ScalarFilterValue = str | int | float | bool | None
FilterValue = ScalarFilterValue | list[str] | list[float]


class ProgressNavigation(HttpContractModel):
    cfi: str | None = None
    current_href: str | None = Field(default=None, alias="currentHref")
    current_section_index: int | None = Field(default=None, alias="currentSectionIndex")
    current_chapter_title: str | None = Field(default=None, alias="currentChapterTitle")
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


class ProgressExtra(HttpContractModel):
    cfi: str | None = None
    progression: float | None = None
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


class LibraryFile(HttpContractModel):
    id: str
    edition_id: str = Field(alias="editionId")
    volume_id: str | None = Field(default=None, alias="volumeId")
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


class LibraryVolume(HttpContractModel):
    id: str
    edition_id: str = Field(alias="editionId")
    title: str
    volume_index: float | None = Field(default=None, alias="volumeIndex")
    sort_order: int = Field(alias="sortOrder")
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    cover_url: str = Field(alias="coverUrl")
    progress: float = 0
    last_read_at: datetime | None = Field(default=None, alias="lastReadAt")
    position: str | None = None
    current_page: int | None = Field(default=None, alias="currentPage")
    current_href: str | None = Field(default=None, alias="currentHref")
    current_section_index: int | None = Field(default=None, alias="currentSectionIndex")
    current_chapter_title: str | None = Field(default=None, alias="currentChapterTitle")
    current_chapter_sort_order: int | None = Field(
        default=None,
        alias="currentChapterSortOrder",
    )
    progress_extra: ProgressExtra = Field(
        default_factory=ProgressExtra, alias="progressExtra"
    )
    duration_ms: int | None = Field(default=None, alias="durationMs")


class EditionConversion(HttpContractModel):
    source_format: str = Field(alias="sourceFormat")
    target_format: str = Field(alias="targetFormat")
    converter: str
    converter_version: str | None = Field(default=None, alias="converterVersion")
    cached: bool


class LibraryEdition(HttpContractModel):
    id: str
    work_id: str = Field(alias="workId")
    media_kind: MediaKind = Field(alias="mediaKind")
    format_value: str = Field(alias="formatValue")
    format: str
    version_name: str = Field(alias="versionName")
    description: str | None = None
    publisher: str | None = None
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    language: str | None = None
    identifier: str | None = None
    isbn: str | None = None
    origin: str | None = None
    source_path: str | None = Field(default=None, alias="sourcePath")
    primary: bool
    hidden: bool
    readable: bool
    conversion_available: bool = Field(alias="conversionAvailable")
    size: str
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    narrator: str | None = None
    track_count: int | None = Field(default=None, alias="trackCount")
    abridged: bool | None = None
    progress: float
    last_read_at: datetime | None = Field(default=None, alias="lastReadAt")
    cover_url: str = Field(alias="coverUrl")
    conversion: EditionConversion | None
    files: list[LibraryFile]
    volumes: list[LibraryVolume]


class WorkDetailTab(HttpContractModel):
    key: DetailTabKey
    label: str
    sort_order: int = Field(alias="sortOrder")


class WorkMediaGroup(HttpContractModel):
    kind: MediaKind
    primary_edition_id: str | None = Field(alias="primaryEditionId")
    recent_edition_id: str | None = Field(alias="recentEditionId")
    recent_volume_id: str | None = Field(alias="recentVolumeId")
    status: ReadingStatus
    progress: float
    position_label: str = Field(alias="positionLabel")
    duration_ms: int | None = Field(alias="durationMs")
    chapter_count: int | None = Field(alias="chapterCount")
    volume_count: int = Field(alias="volumeCount")
    editions: list[LibraryEdition]


class WorkView(HttpContractModel):
    id: str
    work_id: str = Field(alias="workId")
    edition_id: str | None = Field(alias="editionId")
    monitor_folder_id: str | None = Field(alias="monitorFolderId")
    title: str
    author: str
    publisher: str | None
    type: Literal["ebook", "comic", "audiobook"]
    format_value: str = Field(alias="formatValue")
    format: str
    size: str
    progress: float
    progress_extra: ProgressExtra = Field(alias="progressExtra")
    cfi: str | None = None
    current_href: str | None = Field(default=None, alias="currentHref")
    current_section_index: int | None = Field(default=None, alias="currentSectionIndex")
    current_chapter_title: str | None = Field(default=None, alias="currentChapterTitle")
    current_chapter_sort_order: int | None = Field(
        default=None,
        alias="currentChapterSortOrder",
    )
    status_value: ReadingStatus = Field(alias="statusValue")
    status: str
    publication_status_value: str = Field(alias="publicationStatusValue")
    publication_status: str = Field(alias="publicationStatus")
    tracking_status_value: str = Field(alias="trackingStatusValue")
    tracking_status: str = Field(alias="trackingStatus")
    local_latest_volume: float | None = Field(alias="localLatestVolume")
    local_latest_chapter: float | None = Field(alias="localLatestChapter")
    local_latest_title: str | None = Field(alias="localLatestTitle")
    local_latest_at: datetime | None = Field(alias="localLatestAt")
    ignored: bool
    organized: bool
    organize_status: str = Field(alias="organizeStatus")
    metadata_quality: int = Field(alias="metadataQuality")
    metadata_lookup_status: str | None = Field(alias="metadataLookupStatus")
    metadata_lookup_source: str | None = Field(alias="metadataLookupSource")
    metadata_lookup_error: str | None = Field(alias="metadataLookupError")
    tags: list[str]
    series_name: str | None = Field(alias="seriesName")
    series_index: float | None = Field(alias="seriesIndex")
    published_year: int | None = Field(alias="publishedYear")
    added: str
    last_read: str = Field(alias="lastRead")
    last_read_at: datetime | None = Field(alias="lastReadAt")
    chapter: str
    chapter_count: int | None = Field(alias="chapterCount")
    page_count: int | None = Field(alias="pageCount")
    desc: str
    path: str
    file_hash: str | None = Field(alias="fileHash")
    gradient: str
    cover_status: str = Field(alias="coverStatus")
    cover_url: str = Field(alias="coverUrl")
    total_units: int | None = Field(alias="totalUnits")
    reading_progress: float = Field(alias="readingProgress")
    import_status: str = Field(alias="importStatus")
    import_error: str | None = Field(alias="importError")
    imported_at: datetime | None = Field(alias="importedAt")
    files: list[LibraryFile]
    version_count: int = Field(alias="versionCount")
    volume_count: int = Field(alias="volumeCount")
    primary_edition_id: str | None = Field(alias="primaryEditionId")
    primary_edition_name: str | None = Field(alias="primaryEditionName")
    recent_edition_id: str | None = Field(alias="recentEditionId")
    recent_volume_id: str | None = Field(alias="recentVolumeId")
    volumes: list[LibraryVolume]
    editions: list[LibraryEdition]
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    default_media_kind: MediaKind | None = Field(alias="defaultMediaKind")
    media_groups: list[WorkMediaGroup] = Field(alias="mediaGroups")
    detail_tabs: list[WorkDetailTab] = Field(alias="detailTabs")
    selected_detail_tab: DetailTabKey = Field(alias="selectedDetailTab")


class WorkSummary(HttpContractModel):
    id: str
    title: str
    author: str
    cover_url: str = Field(alias="coverUrl")


class WorkSearchSummary(WorkSummary):
    format: str


class ManagementWorkSummary(HttpContractModel):
    id: str
    title: str
    author: str
    monitor_folder_id: str | None = Field(alias="monitorFolderId")
    work_type: str = Field(alias="workType")
    series_name: str | None = Field(alias="seriesName")
    organize_status: str | None = Field(alias="organizeStatus")
    hidden: bool
    updated_at: datetime | None = Field(alias="updatedAt")
    size_bytes: int = Field(default=0, alias="sizeBytes")
    edition_count: int = Field(default=0, alias="editionCount")


class ManagementListWorkSummary(HttpContractModel):
    id: str
    title: str
    author: str
    format: str
    gradient: str
    cover_status: str = Field(alias="coverStatus")
    cover_url: str = Field(alias="coverUrl")
    publisher: str | None
    series_name: str | None = Field(alias="seriesName")
    tags: list[str]
    type: Literal["ebook", "comic", "audiobook"]
    available_media_kinds: list[MediaKind] = Field(alias="availableMediaKinds")
    status_value: ReadingStatus = Field(alias="statusValue")
    last_read_at: datetime | None = Field(alias="lastReadAt")
    imported_at: datetime | None = Field(alias="importedAt")


WorkListItem = WorkView | WorkSummary | WorkSearchSummary | ManagementListWorkSummary


class DashboardSummaryPayload(HttpContractModel):
    total_books: int = Field(alias="totalBooks")
    comic_books: int = Field(alias="comicBooks")
    novel_books: int = Field(alias="novelBooks")
    storage_used_bytes: int = Field(alias="storageUsedBytes")
    monitor_folder_count: int = Field(alias="monitorFolderCount")
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
    resume_edition_id: str | None = Field(alias="resumeEditionId")
    resume_volume_id: str | None = Field(alias="resumeVolumeId")
    progress: float
    chapter: str | None
    last_read_at: datetime | None = Field(alias="lastReadAt")
    version_name: str | None = Field(alias="versionName")
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
    shelf_id: str | None = Field(alias="shelfId")
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


class WorksPayload(HttpContractModel):
    books: list[WorkListItem]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")


class ReadingUnitMetadata(HttpContractModel):
    zip_entry_name: str | None = Field(default=None, alias="zipEntryName")
    idref: str | None = None
    linear: bool | None = None
    properties: list[str] | None = None
    volume_index: float | None = Field(default=None, alias="volumeIndex")
    track_index: int | None = Field(default=None, alias="trackIndex")
    page_number: int | None = Field(default=None, alias="pageNumber")
    source_file_name: str | None = Field(default=None, alias="sourceFileName")


class ReadingUnit(HttpContractModel):
    id: str
    edition_id: str = Field(alias="editionId")
    volume_id: str | None = Field(alias="volumeId")
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
    edition_id: str | None = Field(alias="editionId")
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
    current_chapter_sort_order: int | None = Field(
        default=None,
        alias="currentChapterSortOrder",
    )
    progress_extra: ProgressExtra = Field(alias="progressExtra")


class PrimaryAction(HttpContractModel):
    label: str
    href: str


class ActiveMedia(HttpContractModel):
    key: MediaKind
    format_label: str = Field(alias="formatLabel")
    selected_edition_id: str = Field(alias="selectedEditionId")
    selected_edition_name: str = Field(alias="selectedEditionName")
    status: ReadingStatus
    progress_status: ReadingStatus = Field(alias="progressStatus")
    progress: float
    position_label: str = Field(alias="positionLabel")
    duration_ms: int | None = Field(alias="durationMs")
    narrator: str | None
    primary_action: PrimaryAction | None = Field(alias="primaryAction")
    units: list[ReadingUnit]
    volumes: list[LibraryVolume]
    tracks: list[LibraryFile]


class WorkDetailPayload(HttpContractModel):
    book: WorkView
    active_media: ActiveMedia | None = Field(alias="activeMedia")
    reading_units: list[ReadingUnit] = Field(alias="readingUnits")
    volume_sections: list[VolumeSection] = Field(alias="volumeSections")
    reading_units_page: ReadingUnitsPage = Field(alias="readingUnitsPage")


class WorkPayload(HttpContractModel):
    book: WorkView | None


class DetailPreferencePayload(HttpContractModel):
    selected_detail_tab: DetailTabKey = Field(alias="selectedDetailTab")
    detail_tabs: list[WorkDetailTab] = Field(alias="detailTabs")


class DeletedPathFailure(HttpContractModel):
    path: str
    message: str


class DeletedWorkPayload(HttpContractModel):
    deleted: bool
    id: str
    delete_source: bool = Field(alias="deleteSource")
    deleted_database_records: int = Field(alias="deletedDatabaseRecords")
    deleted_files: int = Field(alias="deletedFiles")
    deleted_source_files: int = Field(alias="deletedSourceFiles")
    missing_source_files: list[str] = Field(alias="missingSourceFiles")
    failed_file_deletes: list[DeletedPathFailure] = Field(
        default_factory=list,
        alias="failedFileDeletes",
    )


class BulkUpdatePayload(HttpContractModel):
    updated: int
    ids: list[str]
    changed_values: int | None = Field(default=None, alias="changedValues")
    status: str | None = None


class BulkDeletePayload(HttpContractModel):
    updated: int
    deleted: int
    delete_source: bool = Field(alias="deleteSource")
    deleted_files: int = Field(alias="deletedFiles")
    deleted_source_files: int = Field(alias="deletedSourceFiles")
    missing_source_files: list[str] = Field(alias="missingSourceFiles")
    failed_file_deletes: list[DeletedPathFailure] = Field(alias="failedFileDeletes")
    ids: list[str]


class BulkCoverPayload(HttpContractModel):
    updated: int
    ids: list[str]
    skipped: list[str]


BulkMutationPayload = BulkUpdatePayload | BulkDeletePayload | BulkCoverPayload


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
    publisher: list[LibraryCategory]


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


class DuplicateGroup(HttpContractModel):
    id: str
    confidence: float
    reasons: list[str]
    works: list[WorkView]


class DuplicatesPayload(HttpContractModel):
    groups: list[DuplicateGroup]
    total: int


class MergeDuplicatesPayload(HttpContractModel):
    target_work_id: str = Field(alias="targetWorkId")
    source_work_ids: list[str] = Field(alias="sourceWorkIds")
    operation: LibraryOperationSummary


class OperationsPayload(HttpContractModel):
    operations: list[LibraryOperationSummary]


class UndoOperationPayload(HttpContractModel):
    operation: LibraryOperationSummary
    restored: bool


class MetadataImageSet(HttpContractModel):
    large: str | None = None
    common: str | None = None
    medium: str | None = None
    small: str | None = None
    grid: str | None = None


class MetadataTag(HttpContractModel):
    name: str
    count: int | None = None


class MetadataInfoboxValue(HttpContractModel):
    v: str
    k: str | None = None


class MetadataInfoboxEntry(HttpContractModel):
    key: str
    value: str | int | float | list[str] | list[MetadataInfoboxValue]


class DoubanCandidateRaw(HttpContractModel):
    id: str | int | None = None
    tpl_name: str | None = None
    title: str | None = None
    subtitle: str | None = None
    url: str | None = None
    abstract: str | None = None
    abstract_2: str | None = None
    cover_url: str | None = None
    cover_url_cdn: str | None = None
    coverUrl: str | None = None
    image: str | None = None
    author: str | list[str] | None = None
    authors: list[str] | None = None
    publisher: str | None = None
    pubdate: str | None = None
    date: str | None = None
    isbn: str | None = None
    isbn13: str | None = None
    isbn10: str | None = None
    series: str | None = None
    seriesName: str | None = None
    series_name: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    tag: list[str] | str | None = None
    publishedAt: str | None = None
    publishedYear: int | None = None
    images: MetadataImageSet | None = None


class BangumiCandidateRaw(HttpContractModel):
    id: str | int | None = None
    url: str | None = None
    name: str | None = None
    name_cn: str | None = None
    summary: str | None = None
    date: str | None = None
    air_date: str | None = None
    image: str | None = None
    images: MetadataImageSet | None = None
    tags: list[str | MetadataTag] | None = None
    infobox: list[MetadataInfoboxEntry] | None = None


class MetadataCandidate(HttpContractModel):
    id: str
    source: str
    external_id: str | None = Field(default=None, alias="externalId")
    title: str | None
    title_aliases: list[str] | None = Field(default=None, alias="titleAliases")
    author: str | None = None
    publisher: str | None = None
    published_year: int | None = Field(default=None, alias="publishedYear")
    isbn: str | None = None
    description: str | None = None
    cover_url: str | None = Field(default=None, alias="coverUrl")
    score: float | None = None
    tags: list[str] | None = None
    series_name: str | None = Field(default=None, alias="seriesName")
    series_index: float | None = Field(default=None, alias="seriesIndex")
    confidence: float
    raw: DoubanCandidateRaw | BangumiCandidateRaw


class MetadataSearchPayload(HttpContractModel):
    candidates: list[MetadataCandidate]
    results: list[MetadataCandidate]
    query: str
    source: str | None
    message: str | None


class EditionMutationPayload(HttpContractModel):
    edition: LibraryEdition
    book: WorkView | None


class ConversionPayload(HttpContractModel):
    task: ImportTaskContract
    created: bool


class WorkStructureMutationPayload(HttpContractModel):
    book: WorkView | None
    target_book: WorkView | None = Field(default=None, alias="targetBook")
    work_id: str = Field(alias="workId")
    edition_id: str | None = Field(default=None, alias="editionId")
    volume_id: str | None = Field(default=None, alias="volumeId")
    target_work_id: str | None = Field(default=None, alias="targetWorkId")
    target_edition_id: str | None = Field(default=None, alias="targetEditionId")
    applied_fields: list[str] | None = Field(default=None, alias="appliedFields")
    finished_organize_job_ids: list[str] | None = Field(
        default=None,
        alias="finishedOrganizeJobIds",
    )
    transfer_mode: str | None = Field(default=None, alias="transferMode")


class OperationSummary(HttpContractModel):
    id: str
    action: str
    status: str
    summary: str
    expires_at: datetime = Field(alias="expiresAt")
    undo_available: bool = Field(alias="undoAvailable")


class SplitEditionPayload(HttpContractModel):
    source_work_id: str = Field(alias="sourceWorkId")
    new_work_id: str = Field(alias="newWorkId")
    edition_id: str = Field(alias="editionId")
    operation: OperationSummary


class MetadataApplyPayload(HttpContractModel):
    book: WorkView
    applied_fields: list[str] = Field(alias="appliedFields")
    finished_organize_job_ids: list[str] = Field(alias="finishedOrganizeJobIds")


WorkStructurePayload = (
    WorkStructureMutationPayload | SplitEditionPayload | MetadataApplyPayload
)


DashboardSummaryResponse = SuccessEnvelope[DashboardSummaryPayload]
WorkSummariesResponse = SuccessEnvelope[WorkSummariesPayload]
ContinueReadingResponse = SuccessEnvelope[ContinueReadingPayload]
ManagementOverviewResponse = SuccessEnvelope[ManagementOverviewPayload]
ManagementFoldersResponse = SuccessEnvelope[ManagementFoldersPayload]
SeriesResponse = SuccessEnvelope[SeriesPayload]
WorksResponse = SuccessEnvelope[WorksPayload]
WorkResponse = SuccessEnvelope[WorkPayload]
WorkDetailResponse = SuccessEnvelope[WorkDetailPayload]
DetailPreferenceResponse = SuccessEnvelope[DetailPreferencePayload]
DeletedWorkResponse = SuccessEnvelope[DeletedWorkPayload]
BulkMutationResponse = SuccessEnvelope[BulkMutationPayload]
FindReplacePreviewResponse = SuccessEnvelope[FindReplacePreviewPayload]
CoverMutationResponse = SuccessEnvelope[CoverMutationPayload]
FacetsResponse = SuccessEnvelope[FacetsPayload]
FilterSchemaResponse = SuccessEnvelope[FilterSchemaPayload]
CategoriesResponse = SuccessEnvelope[CategoriesPayload]
RenameCategoryResponse = SuccessEnvelope[RenameCategoryPayload]
MergeCategoriesResponse = SuccessEnvelope[MergeCategoriesPayload]
DeleteCategoryResponse = SuccessEnvelope[DeleteCategoryPayload]
DuplicatesResponse = SuccessEnvelope[DuplicatesPayload]
MergeDuplicatesResponse = SuccessEnvelope[MergeDuplicatesPayload]
OperationsResponse = SuccessEnvelope[OperationsPayload]
UndoOperationResponse = SuccessEnvelope[UndoOperationPayload]
MetadataSearchResponse = SuccessEnvelope[MetadataSearchPayload]
EditionMutationResponse = SuccessEnvelope[EditionMutationPayload]
ConversionResponse = SuccessEnvelope[ConversionPayload]
WorkStructureMutationResponse = SuccessEnvelope[WorkStructurePayload]


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


class LibraryUnprocessableError(HttpContractError[LibraryErrorBody]):
    status_code = 422
    body_model = LibraryErrorBody


class LibraryUnavailableError(HttpContractError[LibraryErrorBody]):
    status_code = 503
    body_model = LibraryErrorBody
