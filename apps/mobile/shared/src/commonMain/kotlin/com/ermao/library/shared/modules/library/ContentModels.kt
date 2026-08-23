package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.domain.Resource
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
    val mediaKinds: Set<MediaKind> = emptySet(),
    val readingStatuses: Set<ReadingStatus> = emptySet(),
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
    val sort: LibrarySort = LibrarySort.RecentlyAdded,
    val viewMode: LibraryViewMode = LibraryViewMode.Grid,
    val filters: LibraryFilters = LibraryFilters(),
    val page: Int = 1,
    val pageSize: Int = 24,
) {
    init { require(page > 0 && pageSize in 1..100) }

    fun fingerprint(): String = listOf(
        query.trim(),
        sort.name,
        filters.mediaKinds.map { it.wireValue }.sorted().joinToString(","),
        filters.readingStatuses.map { it.wireValue }.sorted().joinToString(","),
        filters.downloadedOnly.toString(),
    ).joinToString("|")
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
    val mediaKind: MediaKind,
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
