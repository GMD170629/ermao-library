package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary
import com.ermao.library.shared.modules.servers.domain.ServerProfile

enum class LibraryScope { Works, Series, Authors }

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
        init {
            require(reasonCode.isNotBlank())
        }
    }
}

data class WorksQuery(
    val query: String = "",
    val sort: LibrarySort = LibrarySort.RecentlyAdded,
    val viewMode: LibraryViewMode = LibraryViewMode.Grid,
    val filters: LibraryFilters = LibraryFilters(),
    val page: Int = 1,
    val pageSize: Int = 24,
) {
    init {
        require(page > 0 && pageSize in 1..100)
    }

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
    init {
        require(page > 0 && pageSize in 1..100)
    }
}

data class FacetQuery(
    val kind: FacetKind,
    val facetId: String,
    val sort: FacetSort = if (kind == FacetKind.Series) FacetSort.SeriesIndex else FacetSort.RecentlyRead,
    val page: Int = 1,
    val pageSize: Int = 24,
) {
    init {
        require(facetId.isNotBlank() && page > 0 && pageSize in 1..100)
    }
}

data class WorkDetailQuery(
    val workId: String,
    val mediaKind: MediaKind? = null,
    val volumeId: String? = null,
) {
    init { require(workId.isNotBlank()) }
}

data class WorkVolumePageQuery(
    val workId: String,
    val mediaVersionId: String,
    val page: Int,
    val pageSize: Int = 24,
) {
    init { require(workId.isNotBlank() && mediaVersionId.isNotBlank() && page > 0 && pageSize in 1..100) }
}

data class WorkVolumePage(
    val mediaVersionId: String,
    val mediaKind: MediaKind,
    val volumes: List<com.ermao.library.shared.modules.library.domain.Volume>,
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
    val representativeWorks: List<WorkSummary>,
)

data class FacetPage(
    val facet: AppliedFacet,
    val works: LibraryPage<WorkSummary>,
)

data class ContinueReadingItem(
    val workId: String,
    val title: String,
    val author: String,
    val coverUrl: String,
    val mediaKind: MediaKind,
    val resumeVolumeId: String?,
    val progress: Double,
    val lastReadAt: String?,
    val volumeTitle: String?,
    val narrator: String?,
)

data class HomeSnapshot(
    val continueReading: HomeSection<ContinueReadingItem?>,
    val recentReading: HomeSection<List<WorkSummary>>,
    val recentAdded: HomeSection<List<WorkSummary>>,
)

sealed interface HomeSection<out T> {
    data class Content<T>(val value: T) : HomeSection<T>
    data class Failure(val error: com.ermao.library.shared.core.network.AppError) : HomeSection<Nothing>
}

data class ContentRequestContext(
    val profile: ServerProfile,
    val namespace: PrivateDataNamespace,
) {
    init {
        require(profile.serverIdentity == namespace.serverIdentity)
    }
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
    suspend fun loadRecentReading(context: ContentRequestContext, limit: Int = 10): ContentResult<List<WorkSummary>>
    suspend fun loadRecentAdded(context: ContentRequestContext, limit: Int = 10): ContentResult<List<WorkSummary>>
    suspend fun loadWorks(context: ContentRequestContext, query: WorksQuery): ContentResult<LibraryPage<WorkSummary>>
    suspend fun loadGroupings(context: ContentRequestContext, query: GroupingQuery): ContentResult<LibraryPage<GroupingSummary>>
    suspend fun loadFacet(context: ContentRequestContext, query: FacetQuery): ContentResult<FacetPage>
    suspend fun loadWorkDetail(context: ContentRequestContext, query: WorkDetailQuery): ContentResult<WorkDetailSummary>
    suspend fun loadWorkVolumes(
        context: ContentRequestContext,
        query: WorkVolumePageQuery,
    ): ContentResult<WorkVolumePage> = ContentResult.Failure(
        com.ermao.library.shared.core.network.AppError(
            com.ermao.library.shared.core.network.AppErrorKind.ProtocolViolation,
            "VOLUME_PAGINATION_UNAVAILABLE",
            "Volume pagination is unavailable",
        ),
    )
    suspend fun loadCover(context: ContentRequestContext, apiPath: String, etag: String? = null): ContentResult<AuthenticatedCover>
    suspend fun invalidate(namespace: PrivateDataNamespace)
}

interface WorkVolumePageRepository {
    suspend fun loadWorkVolumes(
        context: ContentRequestContext,
        query: WorkVolumePageQuery,
    ): ContentResult<WorkVolumePage>
}

data class AuthenticatedCover(
    val bytes: ByteArray,
    val mimeType: String?,
    val etag: String?,
    val notModified: Boolean = false,
)
