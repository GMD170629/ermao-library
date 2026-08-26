package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.Resource
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.servers.domain.ServerProfile

enum class LibraryScope { Books, Series, Authors }

enum class LibrarySort(val wireValue: String) {
    RecentlyAdded("recent_import"),
    RecentlyRead("recent_read"),
    Title("title"),
    Author("author"),
}

enum class LibraryViewMode { Grid, List }

enum class FacetSort(val wireValue: String) {
    SeriesIndex("series_index"),
    RecentlyRead("recent_read"),
}

enum class ReadingStatus(val wireValue: String) {
    Unread("UNREAD"),
    Reading("READING"),
    Finished("FINISHED"),
}

data class LibraryFilters(
    val readingStatus: ReadingStatus? = null,
    val downloadedOnly: Boolean = false,
)

sealed interface OfflineFilterAvailability {
    data object Available : OfflineFilterAvailability

    data class Unavailable(val reasonCode: String) : OfflineFilterAvailability {
        init { require(reasonCode.isNotBlank()) }
    }
}

data class BooksQuery(
    val query: String = "",
    val libraryId: String? = null,
    val sort: LibrarySort = LibrarySort.RecentlyAdded,
    val viewMode: LibraryViewMode = LibraryViewMode.Grid,
    val filters: LibraryFilters = LibraryFilters(),
    val page: Int = 1,
    val pageSize: Int = 24,
) {
    init { require(page > 0 && pageSize in 1..100) }

    fun fingerprint(): String = listOf(
        query.trim(),
        libraryId.orEmpty(),
        sort.name,
        filters.readingStatus?.wireValue.orEmpty(),
        filters.downloadedOnly.toString(),
    ).joinToString("|")
}

data class LibraryOption(
    val id: String,
    val name: String,
) {
    init {
        require(id.isNotBlank())
        require(name.isNotBlank())
    }
}

data class GroupingQuery(
    val kind: FacetKind,
    val query: String = "",
    val page: Int = 1,
    val pageSize: Int = 30,
) {
    init { require(page > 0 && pageSize in 1..100) }
}

data class FacetQuery(
    val kind: FacetKind,
    val facetId: String,
    val sort: FacetSort = if (kind == FacetKind.Series) FacetSort.SeriesIndex else FacetSort.RecentlyRead,
    val page: Int = 1,
    val pageSize: Int = 24,
) {
    init { require(facetId.isNotBlank() && page > 0 && pageSize in 1..100) }
}

data class BookDetailQuery(
    val bookId: String,
    val resourceId: String? = null,
) {
    init { require(bookId.isNotBlank()) }
}

data class BookResourcePageQuery(
    val bookId: String,
    val page: Int,
    val pageSize: Int = 24,
) {
    init { require(bookId.isNotBlank() && page > 0 && pageSize in 1..100) }
}

data class BookResourcePage(
    val bookId: String,
    val resources: List<Resource>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
) {
    val hasNext: Boolean get() = page < totalPages
}

enum class BookContentSort(
    val sortWireValue: String,
    val directionWireValue: String,
) {
    NameAscending("name", "asc"),
    NameDescending("name", "desc"),
    UpdatedDescending("updated", "desc"),
    UpdatedAscending("updated", "asc"),
    TypeAscending("type", "asc"),
    SizeDescending("size", "desc"),
}

enum class BookDetailPresentation { ContentBrowser, ResourceDetail }

data class BookDetailSelection(
    val presentation: BookDetailPresentation,
    val resourceId: String?,
)

/** Shared Web-parity rule used by both native clients when entering Work Detail. */
fun selectBookDetailPresentation(
    resources: List<Resource>,
    requestedResourceId: String? = null,
): BookDetailSelection {
    val readableResources = resources.filter { it.readable && !it.hidden }
    val requestedResource = requestedResourceId
        ?.takeIf(String::isNotBlank)
        ?.let { requestedId -> readableResources.firstOrNull { it.id == requestedId } }
    val detailResource = requestedResource ?: readableResources.singleOrNull()
    return if (detailResource != null) {
        BookDetailSelection(BookDetailPresentation.ResourceDetail, detailResource.id)
    } else {
        BookDetailSelection(BookDetailPresentation.ContentBrowser, null)
    }
}

data class BookContentsQuery(
    val bookId: String,
    val sourceNodeId: String? = null,
    val sort: BookContentSort = BookContentSort.NameAscending,
    val page: Int = 1,
    val pageSize: Int = 100,
) {
    init { require(bookId.isNotBlank() && page > 0 && pageSize in 1..200) }
}

data class BookContentEntry(
    val sourceNodeId: String,
    val parentSourceNodeId: String?,
    val name: String,
    val title: String,
    val description: String?,
    val kind: String,
    val physicalKind: String,
    val sizeBytes: Long?,
    val observedAt: String,
    val hasChildren: Boolean,
    val resourceId: String?,
    val representativeResourceId: String?,
    val coverUrl: String?,
) {
    init {
        require(sourceNodeId.isNotBlank() && title.isNotBlank())
        require(kind == "FOLDER" || kind == "FILE")
        require(sizeBytes == null || sizeBytes >= 0)
    }

    val isDirectResource: Boolean get() = !resourceId.isNullOrBlank()
    val isSourceFolder: Boolean get() = kind == "FOLDER" && !isDirectResource
}

data class BookContentsPage(
    val bookId: String,
    val currentSourceNodeId: String?,
    val currentResourceId: String?,
    val currentNode: BookContentEntry,
    val currentResourceIds: List<String>,
    val parentSourceNodeId: String?,
    val breadcrumbs: List<BookContentEntry>,
    val entries: List<BookContentEntry>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
)

data class ResourceReadingUnitsQuery(
    val bookId: String,
    val resourceId: String,
    val page: Int = 1,
    val pageSize: Int = 50,
) {
    init {
        require(bookId.isNotBlank() && resourceId.isNotBlank())
        require(page > 0 && pageSize in 1..500)
    }
}

data class ResourceReadingUnitsPage(
    val bookId: String,
    val resourceId: String,
    val units: List<ReadingUnit>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
    val currentHref: String?,
    val currentChapterIndex: Int?,
    val currentChapterTitle: String?,
    val currentChapterSortOrder: Int?,
    val currentPageNumber: Int?,
    val progress: Double,
)

data class LibraryPage<T>(
    val items: List<T>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
) {
    val hasNext: Boolean get() = page < totalPages
}

data class GroupingSummary(
    val id: String,
    val name: String,
    val bookCount: Int,
    val updatedAt: String,
    val representativeBooks: List<BookSummary>,
)

data class FacetPage(
    val facet: AppliedFacet,
    val books: LibraryPage<BookSummary>,
)

data class ContinueReadingItem(
    val bookId: String,
    val title: String,
    val author: String?,
    val coverUrl: String,
    val resourceFormat: String,
    val readerType: String,
    val resumeResourceId: String?,
    val progress: Double,
    val chapter: String?,
    val lastReadAt: String?,
    val resourceTitle: String?,
    val narrator: String?,
)

data class HomeSnapshot(
    val continueReading: HomeSection<ContinueReadingItem?>,
    val recentReading: HomeSection<List<BookSummary>>,
    val recentAdded: HomeSection<List<BookSummary>>,
)

sealed interface HomeSection<out T> {
    data class Content<T>(val value: T) : HomeSection<T>
    data class Failure(val error: com.ermao.library.shared.core.network.AppError) : HomeSection<Nothing>
}

data class ContentRequestContext(
    val profile: ServerProfile,
    val namespace: PrivateDataNamespace,
) {
    init { require(profile.serverIdentity == namespace.serverIdentity) }
}

enum class ContentSource { Network }

sealed interface ContentResult<out T> {
    data class Content<T>(
        val value: T,
        val source: ContentSource,
        val cachedAtEpochMillis: Long? = null,
        val isStale: Boolean = false,
    ) : ContentResult<T>

    data class Failure(val error: com.ermao.library.shared.core.network.AppError) : ContentResult<Nothing>
}

interface ContentRepository {
    suspend fun loadHome(context: ContentRequestContext): ContentResult<HomeSnapshot>
    suspend fun loadContinueReading(context: ContentRequestContext): ContentResult<ContinueReadingItem?>
    suspend fun loadRecentReading(context: ContentRequestContext, limit: Int = 10): ContentResult<List<BookSummary>>
    suspend fun loadRecentAdded(context: ContentRequestContext, limit: Int = 10): ContentResult<List<BookSummary>>
    suspend fun loadBooks(context: ContentRequestContext, query: BooksQuery): ContentResult<LibraryPage<BookSummary>>
    suspend fun loadLibraryOptions(context: ContentRequestContext): ContentResult<List<LibraryOption>> =
        ContentResult.Content(emptyList(), ContentSource.Network)
    suspend fun loadGroupings(context: ContentRequestContext, query: GroupingQuery): ContentResult<LibraryPage<GroupingSummary>>
    suspend fun loadFacet(context: ContentRequestContext, query: FacetQuery): ContentResult<FacetPage>
    suspend fun loadBookDetail(context: ContentRequestContext, query: BookDetailQuery): ContentResult<BookDetailSummary>
    suspend fun loadBookResources(
        context: ContentRequestContext,
        query: BookResourcePageQuery,
    ): ContentResult<BookResourcePage> = ContentResult.Failure(
        com.ermao.library.shared.core.network.AppError(
            com.ermao.library.shared.core.network.AppErrorKind.ProtocolViolation,
            "RESOURCE_PAGINATION_UNAVAILABLE",
            "Resource pagination is unavailable",
        ),
    )
    suspend fun loadBookContents(
        context: ContentRequestContext,
        query: BookContentsQuery,
    ): ContentResult<BookContentsPage> = ContentResult.Failure(
        com.ermao.library.shared.core.network.AppError(
            com.ermao.library.shared.core.network.AppErrorKind.ProtocolViolation,
            "BOOK_CONTENTS_UNAVAILABLE",
            "Book contents are unavailable",
        ),
    )
    suspend fun loadResourceReadingUnits(
        context: ContentRequestContext,
        query: ResourceReadingUnitsQuery,
    ): ContentResult<ResourceReadingUnitsPage> = ContentResult.Failure(
        com.ermao.library.shared.core.network.AppError(
            com.ermao.library.shared.core.network.AppErrorKind.ProtocolViolation,
            "READING_UNITS_UNAVAILABLE",
            "Reading units are unavailable",
        ),
    )
    suspend fun loadCover(context: ContentRequestContext, apiPath: String, etag: String? = null): ContentResult<AuthenticatedCover>
    suspend fun invalidate(namespace: PrivateDataNamespace)
}

interface BookResourcePageRepository {
    suspend fun loadBookResources(
        context: ContentRequestContext,
        query: BookResourcePageQuery,
    ): ContentResult<BookResourcePage>
}

data class AuthenticatedCover(
    val bytes: ByteArray,
    val mimeType: String?,
    val etag: String?,
    val notModified: Boolean = false,
)
