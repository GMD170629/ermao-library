package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.AuthenticatedCover
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.ContentSource
import com.ermao.library.shared.modules.library.FacetPage
import com.ermao.library.shared.modules.library.FacetQuery
import com.ermao.library.shared.modules.library.GroupingQuery
import com.ermao.library.shared.modules.library.GroupingSummary
import com.ermao.library.shared.modules.library.HomeSection
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.LibraryPage
import com.ermao.library.shared.modules.library.WorkDetailQuery
import com.ermao.library.shared.modules.library.WorkVolumePageQuery
import com.ermao.library.shared.modules.library.WorkVolumePageRepository
import com.ermao.library.shared.modules.library.WorksQuery
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.WorkDetail
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope

class KtorContentRepository(
    private val clients: ApiClientFactory,
) : ContentRepository, WorkVolumePageRepository {
    override suspend fun loadHome(context: ContentRequestContext): ContentResult<HomeSnapshot> = coroutineScope {
        val continueReading = async { requestContinueReading(context) }
        val recentReading = async { requestWorksSection(context, "/api/dashboard/recent-reading") }
        val recentAdded = async { requestWorksSection(context, "/api/dashboard/recent-books") }
        val snapshot = HomeSnapshot(continueReading.await(), recentReading.await(), recentAdded.await())
        val hasNetworkContent = listOf(snapshot.continueReading, snapshot.recentReading, snapshot.recentAdded)
            .any { it is HomeSection.Content<*> }
        if (hasNetworkContent) ContentResult.Content(snapshot, ContentSource.Network)
        else ContentResult.Failure(firstHomeError(snapshot))
    }

    override suspend fun loadContinueReading(
        context: ContentRequestContext,
    ): ContentResult<com.ermao.library.shared.modules.library.ContinueReadingItem?> =
        when (val section = requestContinueReading(context)) {
            is HomeSection.Content -> ContentResult.Content(section.value, ContentSource.Network)
            is HomeSection.Failure -> ContentResult.Failure(section.error)
        }

    override suspend fun loadRecentReading(
        context: ContentRequestContext,
        limit: Int,
    ): ContentResult<List<WorkSummary>> = requestWorksContent(context, "/api/dashboard/recent-reading", limit)

    override suspend fun loadRecentAdded(
        context: ContentRequestContext,
        limit: Int,
    ): ContentResult<List<WorkSummary>> = requestWorksContent(context, "/api/dashboard/recent-books", limit)

    override suspend fun loadWorks(
        context: ContentRequestContext,
        query: WorksQuery,
    ): ContentResult<LibraryPage<WorkSummary>> {
        if (query.filters.downloadedOnly) {
            return ContentResult.Failure(
                com.ermao.library.shared.core.network.AppError(
                    com.ermao.library.shared.core.network.AppErrorKind.Validation,
                    "MANAGED_DOWNLOADS_UNAVAILABLE",
                    "The managed download manifest is not available for this server capability.",
                ),
            )
        }
        return when (val result = withClient(context) { client ->
            client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    "/api/works",
                    WorkPageWire.serializer(),
                    queryParameters = worksParameters(query),
                ),
            )
        }) {
            is ApiResult.Success -> ContentResult.Content(result.value.toPage(), ContentSource.Network)
            is ApiResult.Failure -> ContentResult.Failure(result.error)
        }
    }

    override suspend fun loadGroupings(
        context: ContentRequestContext,
        query: GroupingQuery,
    ): ContentResult<LibraryPage<GroupingSummary>> {
        return when (val result = withClient(context) { client ->
            client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    "/api/library/groupings",
                    GroupingPageWire.serializer(),
                    queryParameters = mapOf(
                        "kind" to listOf(facetKindWire(query.kind)),
                        "search" to listOf(query.query.trim()),
                        "page" to listOf(query.page.toString()),
                        "pageSize" to listOf(query.pageSize.toString()),
                    ),
                ),
            )
        }) {
            is ApiResult.Success -> ContentResult.Content(result.value.toPage(), ContentSource.Network)
            is ApiResult.Failure -> ContentResult.Failure(result.error)
        }
    }

    override suspend fun loadFacet(context: ContentRequestContext, query: FacetQuery): ContentResult<FacetPage> {
        return when (val result = withClient(context) { client ->
            client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    "/api/works",
                    WorkPageWire.serializer(),
                    queryParameters = mapOf(
                        "view" to listOf("search"),
                        "visibility" to listOf("active"),
                        "facetKind" to listOf(facetKindWire(query.kind)),
                        "facetId" to listOf(query.facetId),
                        "sort" to listOf(query.sort.wireValue),
                        "page" to listOf(query.page.toString()),
                        "pageSize" to listOf(query.pageSize.toString()),
                    ),
                ),
            )
        }) {
            is ApiResult.Success -> result.value.toFacetPage()?.let { page ->
                ContentResult.Content(page, ContentSource.Network)
            } ?: ContentResult.Failure(
                com.ermao.library.shared.core.network.AppError(
                    com.ermao.library.shared.core.network.AppErrorKind.ProtocolViolation,
                    "FACET_IDENTITY_MISSING",
                    "Facet response is missing appliedFacet",
                ),
            )
            is ApiResult.Failure -> ContentResult.Failure(result.error)
        }
    }

    override suspend fun loadWorkDetail(
        context: ContentRequestContext,
        query: WorkDetailQuery,
    ): ContentResult<WorkDetailSummary> = when (val result = withClient(context) { client ->
        client.execute(
            ApiRequest(
                ApiMethod.Get,
                "/api/works/${query.workId}",
                WorkDetailPayloadWire.serializer(),
                queryParameters = buildMap {
                    // Without any query parameter the compatibility API intentionally returns
                    // a summary without readingUnits. Request the first bounded navigation page
                    // so a single-volume EPUB exposes its real directory on the initial load.
                    put("chapterPageSize", listOf(DEFAULT_READING_UNITS_PAGE_SIZE.toString()))
                    query.mediaKind?.let { put("detailTab", listOf(it.wireValue)) }
                    query.volumeId?.let { put("volumeId", listOf(it)) }
                },
            ),
        )
    }) {
        is ApiResult.Success -> ContentResult.Content(result.value.toDomain().toSummary(), ContentSource.Network)
        is ApiResult.Failure -> ContentResult.Failure(result.error)
    }

    override suspend fun loadWorkVolumes(
        context: ContentRequestContext,
        query: WorkVolumePageQuery,
    ): ContentResult<com.ermao.library.shared.modules.library.WorkVolumePage> = when (
        val result = withClient(context) { client ->
            client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    "/api/works/${query.workId}/media-versions/${query.mediaVersionId}/volumes",
                    WorkVolumePageWire.serializer(),
                    queryParameters = mapOf(
                        "page" to listOf(query.page.toString()),
                        "pageSize" to listOf(query.pageSize.toString()),
                    ),
                ),
            )
        }
    ) {
        is ApiResult.Success -> ContentResult.Content(result.value.toDomain(), ContentSource.Network)
        is ApiResult.Failure -> ContentResult.Failure(result.error)
    }

    override suspend fun loadCover(
        context: ContentRequestContext,
        apiPath: String,
        etag: String?,
    ): ContentResult<AuthenticatedCover> = when (val result = withClient(context) { client ->
        client.loadAuthenticatedAsset(apiPath, etag)
    }) {
        is ApiResult.Success -> ContentResult.Content(
            AuthenticatedCover(
                result.value.bytes,
                result.value.mimeType,
                result.value.etag,
                result.value.notModified,
            ),
            ContentSource.Network,
        )
        is ApiResult.Failure -> ContentResult.Failure(result.error)
    }

    override suspend fun invalidate(namespace: com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace) = Unit

    private suspend fun requestContinueReading(context: ContentRequestContext): HomeSection<com.ermao.library.shared.modules.library.ContinueReadingItem?> =
        when (val result = withClient(context) { client ->
            client.execute(ApiRequest(ApiMethod.Get, "/api/dashboard/continue-reading", ContinueReadingPayloadWire.serializer()))
        }) {
            is ApiResult.Success -> HomeSection.Content(result.value.item?.toDomain())
            is ApiResult.Failure -> HomeSection.Failure(result.error)
        }

    private suspend fun requestWorksSection(context: ContentRequestContext, path: String): HomeSection<List<WorkSummary>> =
        when (val result = requestWorks(context, path, 10)) {
            is ApiResult.Success -> HomeSection.Content(result.value)
            is ApiResult.Failure -> HomeSection.Failure(result.error)
        }

    private suspend fun requestWorksContent(
        context: ContentRequestContext,
        path: String,
        limit: Int,
    ): ContentResult<List<WorkSummary>> {
        require(limit in 1..24)
        return when (val result = requestWorks(context, path, limit)) {
            is ApiResult.Success -> ContentResult.Content(result.value, ContentSource.Network)
            is ApiResult.Failure -> ContentResult.Failure(result.error)
        }
    }

    private suspend fun requestWorks(
        context: ContentRequestContext,
        path: String,
        limit: Int,
    ): ApiResult<List<WorkSummary>> = when (val result = withClient(context) { client ->
            client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    path,
                    WorksWire.serializer(),
                    queryParameters = mapOf("limit" to listOf(limit.toString())),
                ),
            )
        }) {
            is ApiResult.Success -> ApiResult.Success(result.value.books.map(WorkSummaryWire::toDomain), result.metadata)
            is ApiResult.Failure -> result
        }

    private fun worksParameters(query: WorksQuery): Map<String, List<String>> = buildMap {
        put("view", listOf("search"))
        put("visibility", listOf("active"))
        put("page", listOf(query.page.toString()))
        put("pageSize", listOf(query.pageSize.toString()))
        put("sort", listOf(query.sort.wireValue))
        query.query.trim().takeIf(String::isNotEmpty)?.let { put("search", listOf(it)) }
        query.filters.mediaKinds.takeIf(Set<*>::isNotEmpty)?.let { kinds ->
            put("mediaKinds", listOf(kinds.map { it.wireValue }.sorted().joinToString(",")))
        }
        query.filters.readingStatuses.takeIf(Set<*>::isNotEmpty)?.let { statuses ->
            put("statuses", listOf(statuses.map { it.wireValue }.sorted().joinToString(",")))
        }
    }

    private fun WorkDetail.toSummary(): WorkDetailSummary = WorkDetailSummary(
        id = id,
        title = title,
        author = author,
        description = description,
        tags = tags,
        seriesName = seriesName,
        seriesFacet = seriesFacet,
        authorFacets = authorFacets,
        seriesIndex = seriesIndex,
        coverStatus = coverStatus,
        coverUrl = coverUrl,
        recentMediaKind = recentMediaKind,
        continueVolumeId = continueVolumeId,
        continueVolumeProgress = continueVolumeProgress,
        completed = completed,
        mediaVersions = mediaVersions,
        availableMediaKinds = availableMediaKinds,
        detailTabs = detailTabs,
        selectedDetailTab = selectedDetailTab,
        activeMedia = activeMedia,
        readingUnits = readingUnits,
        readingUnitsPage = readingUnitsPage,
    )

    private suspend fun <T> withClient(context: ContentRequestContext, block: suspend (ApiClient) -> ApiResult<T>): ApiResult<T> {
        val client = clients.create(context.profile)
        return try { block(client) } finally { client.close() }
    }

    private fun firstHomeError(snapshot: HomeSnapshot) = sequenceOf(
        snapshot.continueReading,
        snapshot.recentReading,
        snapshot.recentAdded,
    ).filterIsInstance<HomeSection.Failure>().first().error

    private companion object {
        const val DEFAULT_READING_UNITS_PAGE_SIZE = 120
    }
}
