package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.AuthenticatedCover
import com.ermao.library.shared.modules.library.BookDetailQuery
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.BookContentsQuery
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
import com.ermao.library.shared.modules.library.LibraryOption
import com.ermao.library.shared.modules.library.ResourceReadingUnitsPage
import com.ermao.library.shared.modules.library.ResourceReadingUnitsQuery
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.library.domain.ReadingUnitMetadata
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import io.ktor.http.encodeURLPathPart
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

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

    override suspend fun loadLibraryOptions(
        context: ContentRequestContext,
    ): ContentResult<List<LibraryOption>> = when (val result = withClient(context) { client ->
        client.execute(
            ApiRequest(
                ApiMethod.Get,
                "/api/library/filter-schema",
                LibraryFilterSchemaWire.serializer(),
            ),
        )
    }) {
        is ApiResult.Success -> {
            val libraryField = result.value.fields.singleOrNull { it.key == "library" }
                ?: return ContentResult.Failure(
                    com.ermao.library.shared.core.network.AppError(
                        com.ermao.library.shared.core.network.AppErrorKind.ProtocolViolation,
                        "LIBRARY_FILTER_SCHEMA_INVALID",
                    ),
                )
            ContentResult.Content(
                libraryField.options.map { LibraryOption(it.value, it.label) },
                ContentSource.Network,
            )
        }
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

    override suspend fun loadBookContents(
        context: ContentRequestContext,
        query: BookContentsQuery,
    ): ContentResult<BookContentsPage> = when (val result = withClient(context) { client ->
        client.execute(
            ApiRequest(
                ApiMethod.Get,
                "/api/books/${query.bookId.encodeURLPathPart()}/contents",
                BookContentsPayloadWire.serializer(),
                queryParameters = bookContentsParameters(query),
            ),
        )
    }) {
        is ApiResult.Success -> ContentResult.Content(result.value.toDomain(), ContentSource.Network)
        is ApiResult.Failure -> ContentResult.Failure(result.error)
    }

    override suspend fun loadResourceReadingUnits(
        context: ContentRequestContext,
        query: ResourceReadingUnitsQuery,
    ): ContentResult<ResourceReadingUnitsPage> = when (val result = withClient(context) { client ->
        client.execute(
            ApiRequest(
                ApiMethod.Get,
                "/api/books/${query.bookId.encodeURLPathPart()}/resources/" +
                    "${query.resourceId.encodeURLPathPart()}/reading-units",
                ResourceReadingUnitsPayloadWire.serializer(),
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

    private fun booksParameters(query: BooksQuery): Map<String, List<String>> = libraryBooksParameters(query)

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

internal fun libraryBooksParameters(query: BooksQuery): Map<String, List<String>> = buildMap {
        put("view", listOf("search"))
        put("visibility", listOf("active"))
        put("page", listOf(query.page.toString()))
        put("pageSize", listOf(query.pageSize.toString()))
        put("sort", listOf(query.sort.wireValue))
        query.query.trim().takeIf(String::isNotEmpty)?.let { put("search", listOf(it)) }
        query.filters.readingStatus?.let { status ->
            put("status", listOf(status.wireValue))
        }
        query.libraryId?.takeIf(String::isNotBlank)?.let { libraryId ->
            val expression = buildJsonObject {
                put("combinator", "ALL")
                put("conditions", buildJsonArray {
                    add(buildJsonObject {
                        put("field", "library")
                        put("operator", "equals")
                        put("value", libraryId)
                    })
                })
            }
            put("filters", listOf(expression.toString()))
        }
}

internal fun bookContentsParameters(query: BookContentsQuery): Map<String, List<String>> = buildMap {
    query.sourceNodeId?.takeIf(String::isNotBlank)?.let { put("sourceNodeId", listOf(it)) }
    put("sort", listOf(query.sort.sortWireValue))
    put("direction", listOf(query.sort.directionWireValue))
    put("page", listOf(query.page.toString()))
    put("pageSize", listOf(query.pageSize.toString()))
}

@Serializable
private data class LibraryFilterSchemaWire(
    val fields: List<LibraryFilterFieldWire>,
    val maxConditions: Int,
)

@Serializable
private data class LibraryFilterFieldWire(
    val key: String,
    val label: String,
    val group: String,
    val type: String,
    val operators: List<String>,
    val optionSource: String? = null,
    val allowCustom: Boolean? = null,
    val unit: String? = null,
    val valueScale: Int? = null,
    val options: List<LibraryFilterOptionWire>,
)

@Serializable
private data class LibraryFilterOptionWire(
    val value: String,
    val label: String,
    val count: Int? = null,
    val rootPath: String? = null,
)

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

@Serializable
private data class BookContentEntryWire(
    val sourceNodeId: String,
    val parentSourceNodeId: String? = null,
    val name: String,
    val title: String,
    val description: String? = null,
    val kind: String,
    val physicalKind: String,
    val sizeBytes: Long? = null,
    val observedAt: String,
    val hasChildren: Boolean,
    val resourceId: String? = null,
    val representativeResourceId: String? = null,
    val coverUrl: String? = null,
) {
    fun toDomain() = BookContentEntry(
        sourceNodeId = sourceNodeId,
        parentSourceNodeId = parentSourceNodeId,
        name = name,
        title = title,
        description = description,
        kind = kind,
        physicalKind = physicalKind,
        sizeBytes = sizeBytes,
        observedAt = observedAt,
        hasChildren = hasChildren,
        resourceId = resourceId,
        representativeResourceId = representativeResourceId,
        coverUrl = coverUrl,
    )
}

@Serializable
private data class BookContentsPayloadWire(
    val bookId: String,
    val currentSourceNodeId: String? = null,
    val currentResourceId: String? = null,
    val currentNode: BookContentEntryWire,
    val currentResourceIds: List<String> = emptyList(),
    val parentSourceNodeId: String? = null,
    val breadcrumbs: List<BookContentEntryWire> = emptyList(),
    val entries: List<BookContentEntryWire> = emptyList(),
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
) {
    fun toDomain() = BookContentsPage(
        bookId = bookId,
        currentSourceNodeId = currentSourceNodeId,
        currentResourceId = currentResourceId,
        currentNode = currentNode.toDomain(),
        currentResourceIds = currentResourceIds,
        parentSourceNodeId = parentSourceNodeId,
        breadcrumbs = breadcrumbs.map(BookContentEntryWire::toDomain),
        entries = entries.map(BookContentEntryWire::toDomain),
        page = page,
        pageSize = pageSize,
        total = total,
        totalPages = totalPages,
    )
}

@Serializable
private data class ResourceReadingUnitWire(
    val id: String,
    val title: String,
    val href: String? = null,
    val sortOrder: Int,
    val unitType: String,
    val assetId: String? = null,
    val pageNumber: Int? = null,
    val mediaType: String? = null,
    val previewUrl: String? = null,
    val level: Int? = null,
    val durationMs: Long? = null,
    val discNumber: Int? = null,
    val trackNumber: Int? = null,
    val metadataJson: String = "{}",
) {
    fun toDomain(resourceId: String) = ReadingUnit(
        id = id,
        resourceId = resourceId,
        assetId = assetId,
        unitType = unitType,
        title = title,
        href = href,
        mediaType = mediaType,
        sortOrder = sortOrder,
        startMillis = null,
        endMillis = null,
        durationMillis = durationMs,
        width = null,
        height = null,
        sizeBytes = null,
        metadata = ReadingUnitMetadata(
            exactNavigation = null,
            level = level,
            path = null,
            navigationKey = null,
            zipEntryName = null,
            idref = null,
            linear = null,
            properties = null,
            resourceIndex = null,
            trackIndex = null,
            pageNumber = pageNumber,
            sourceFileName = null,
            hrefBase = null,
            recovered = null,
        ),
        createdAt = null,
        updatedAt = null,
        previewUrl = previewUrl,
        discNumber = discNumber,
        trackNumber = trackNumber,
    )
}

@Serializable
private data class ResourceReadingUnitsPageWire(
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
)

@Serializable
private data class ResourceReadingUnitsPayloadWire(
    val bookId: String,
    val resourceId: String,
    val units: List<ResourceReadingUnitWire> = emptyList(),
    val page: ResourceReadingUnitsPageWire,
    val currentHref: String? = null,
    val currentChapterIndex: Int? = null,
    val currentChapterTitle: String? = null,
    val currentChapterSortOrder: Int? = null,
    val currentPageNumber: Int? = null,
    val progress: Double,
) {
    fun toDomain() = ResourceReadingUnitsPage(
        bookId = bookId,
        resourceId = resourceId,
        units = units.map { it.toDomain(resourceId) },
        page = page.page,
        pageSize = page.pageSize,
        total = page.total,
        totalPages = page.totalPages,
        currentHref = currentHref,
        currentChapterIndex = currentChapterIndex,
        currentChapterTitle = currentChapterTitle,
        currentChapterSortOrder = currentChapterSortOrder,
        currentPageNumber = currentPageNumber,
        progress = progress,
    )
}
