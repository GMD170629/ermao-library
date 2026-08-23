package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.AuthenticatedCover
import com.ermao.library.shared.modules.library.BookDetailQuery
import com.ermao.library.shared.modules.library.BookResourcePage
import com.ermao.library.shared.modules.library.BookResourcePageQuery
import com.ermao.library.shared.modules.library.BookResourcePageRepository
import com.ermao.library.shared.modules.library.BooksQuery
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
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import io.ktor.http.encodeURLPathPart

class KtorContentRepository(
    private val clients: ApiClientFactory,
) : ContentRepository, BookResourcePageRepository {
    override suspend fun loadHome(context: ContentRequestContext): ContentResult<HomeSnapshot> = coroutineScope {
        val continueReading = async { requestContinueReading(context) }
        val recentReading = async { requestBooksSection(context, "/api/dashboard/recent-reading") }
        val recentAdded = async { requestBooksSection(context, "/api/dashboard/recent-books") }
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
    ): ContentResult<List<BookSummary>> = requestBooksContent(context, "/api/dashboard/recent-reading", limit)

    override suspend fun loadRecentAdded(
        context: ContentRequestContext,
        limit: Int,
    ): ContentResult<List<BookSummary>> = requestBooksContent(context, "/api/dashboard/recent-books", limit)

    override suspend fun loadBooks(
        context: ContentRequestContext,
        query: BooksQuery,
    ): ContentResult<LibraryPage<BookSummary>> = when (val result = withClient(context) { client ->
            client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    "/api/books",
                    BookPageWire.serializer(),
                    queryParameters = booksParameters(query),
                ),
            )
        }) {
            is ApiResult.Success -> ContentResult.Content(result.value.toPage(), ContentSource.Network)
            is ApiResult.Failure -> ContentResult.Failure(result.error)
        }

    override suspend fun loadGroupings(
        context: ContentRequestContext,
        query: GroupingQuery,
    ): ContentResult<LibraryPage<GroupingSummary>> = when (val result = withClient(context) { client ->
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

    override suspend fun loadFacet(context: ContentRequestContext, query: FacetQuery): ContentResult<FacetPage> =
        when (val result = withClient(context) { client ->
            client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    "/api/books",
                    BookPageWire.serializer(),
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
            is ApiResult.Success -> ContentResult.Content(
                result.value.toFacetPage(query.kind, query.facetId),
                ContentSource.Network,
            )
            is ApiResult.Failure -> ContentResult.Failure(result.error)
        }

    override suspend fun loadBookDetail(
        context: ContentRequestContext,
        query: BookDetailQuery,
    ): ContentResult<BookDetailSummary> = when (val result = withClient(context) { client ->
        client.execute(
            ApiRequest(
                ApiMethod.Get,
                "/api/books/${query.bookId.encodeURLPathPart()}",
                BookPayloadWire.serializer(),
            ),
        )
    }) {
        is ApiResult.Success -> ContentResult.Content(result.value.toDomain(), ContentSource.Network)
        is ApiResult.Failure -> ContentResult.Failure(result.error)
    }

    override suspend fun loadBookResources(
        context: ContentRequestContext,
        query: BookResourcePageQuery,
    ): ContentResult<BookResourcePage> = when (val result = withClient(context) { client ->
        client.execute(
            ApiRequest(
                ApiMethod.Get,
                "/api/books/${query.bookId.encodeURLPathPart()}/resources",
                ResourcesPayloadWire.serializer(),
                queryParameters = mapOf(
                    "page" to listOf(query.page.toString()),
                    "pageSize" to listOf(query.pageSize.toString()),
                ),
            ),
        )
    }) {
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
            AuthenticatedCover(result.value.bytes, result.value.mimeType, result.value.etag, result.value.notModified),
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

    private suspend fun requestBooksSection(context: ContentRequestContext, path: String): HomeSection<List<BookSummary>> =
        when (val result = requestBooks(context, path, 10)) {
            is ApiResult.Success -> HomeSection.Content(result.value)
            is ApiResult.Failure -> HomeSection.Failure(result.error)
        }

    private suspend fun requestBooksContent(
        context: ContentRequestContext,
        path: String,
        limit: Int,
    ): ContentResult<List<BookSummary>> {
        require(limit in 1..50)
        return when (val result = requestBooks(context, path, limit)) {
            is ApiResult.Success -> ContentResult.Content(result.value, ContentSource.Network)
            is ApiResult.Failure -> ContentResult.Failure(result.error)
        }
    }

    private suspend fun requestBooks(
        context: ContentRequestContext,
        path: String,
        limit: Int,
    ): ApiResult<List<BookSummary>> = when (val result = withClient(context) { client ->
        client.execute(
            ApiRequest(
                ApiMethod.Get,
                path,
                BooksWire.serializer(),
                queryParameters = mapOf("limit" to listOf(limit.toString())),
            ),
        )
    }) {
        is ApiResult.Success -> ApiResult.Success(result.value.books.map(BookSummaryWire::toDomain), result.metadata)
        is ApiResult.Failure -> result
    }

    private fun booksParameters(query: BooksQuery): Map<String, List<String>> = buildMap {
        put("view", listOf("search"))
        put("visibility", listOf("active"))
        put("page", listOf(query.page.toString()))
        put("pageSize", listOf(query.pageSize.toString()))
        put("sort", listOf(query.sort.wireValue))
        query.query.trim().takeIf(String::isNotEmpty)?.let { put("search", listOf(it)) }
        query.filters.mediaKinds.takeIf(Set<*>::isNotEmpty)?.let { kinds ->
            put("media", listOf(kinds.map { it.wireValue }.sorted().joinToString(",")))
        }
        query.filters.readingStatuses.takeIf(Set<*>::isNotEmpty)?.let { statuses ->
            put("status", listOf(statuses.map { it.wireValue }.sorted().joinToString(",")))
        }
    }

    private suspend fun <T> withClient(
        context: ContentRequestContext,
        block: suspend (ApiClient) -> ApiResult<T>,
    ): ApiResult<T> {
        val client = clients.create(context.profile)
        return try { block(client) } finally { client.close() }
    }

    private fun firstHomeError(snapshot: HomeSnapshot) = sequenceOf(
        snapshot.continueReading,
        snapshot.recentReading,
        snapshot.recentAdded,
    ).filterIsInstance<HomeSection.Failure>().first().error
}

@kotlinx.serialization.Serializable
private data class ResourcesPayloadWire(
    val bookId: String,
    val resources: List<ResourceWire>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
) {
    fun toDomain() = BookResourcePage(
        bookId = bookId,
        resources = resources.map(ResourceWire::toDomain),
        page = page,
        pageSize = pageSize,
        total = total,
        totalPages = totalPages,
    )
}
