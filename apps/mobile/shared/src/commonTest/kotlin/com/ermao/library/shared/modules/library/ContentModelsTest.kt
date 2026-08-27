package com.ermao.library.shared.modules.library

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertIs
import kotlinx.coroutines.runBlocking

class ContentModelsTest {
    @Test
    fun queryFingerprintDoesNotIncludePage() {
        val first = BooksQuery(
            query = "  三体  ",
            filters = LibraryFilters(readingStatus = ReadingStatus.Reading),
            page = 1,
        )
        val second = first.copy(
            page = 3,
        )

        assertEquals(first.fingerprint(), second.fingerprint())
    }

    @Test
    fun facetSortDefaultsAreFixedByFacetKind() {
        assertEquals(
            FacetSort.SeriesIndex,
            FacetQuery(com.ermao.library.shared.modules.library.domain.FacetKind.Series, "series-1").sort,
        )
        assertEquals(
            FacetSort.RecentlyRead,
            FacetQuery(com.ermao.library.shared.modules.library.domain.FacetKind.Author, "author-1").sort,
        )
    }

    @Test
    fun swiftFriendlyFilterFactoryProducesSingleReadingStatus() {
        val filters = createLibraryFilters(readingStatus = ReadingStatus.Reading)

        assertEquals(ReadingStatus.Reading, filters.readingStatus)
    }

    @Test
    fun bookContentSortsMatchWebQueryContract() {
        assertEquals("name" to "asc", BookContentSort.NameAscending.toWirePair())
        assertEquals("name" to "desc", BookContentSort.NameDescending.toWirePair())
        assertEquals("updated" to "desc", BookContentSort.UpdatedDescending.toWirePair())
        assertEquals("updated" to "asc", BookContentSort.UpdatedAscending.toWirePair())
        assertEquals("type" to "asc", BookContentSort.TypeAscending.toWirePair())
        assertEquals("size" to "desc", BookContentSort.SizeDescending.toWirePair())
    }

    @Test
    fun directoryDoesNotAcquireItsRepresentativeResourcesIdentity() {
        assertEquals(BookContentTarget.Directory("node"), bookContentTarget(node("FOLDER")))
    }

    @Test
    fun physicalFolderBoundToResourceOpensResourceDetail() {
        assertEquals(BookContentTarget.ResourceDetail("resource"), bookContentTarget(node("FOLDER", "resource")))
    }

    @Test
    fun fileBoundToResourceOpensResourceDetail() {
        assertEquals(BookContentTarget.ResourceDetail("resource"), bookContentTarget(node("FILE", "resource")))
    }

    @Test
    fun unboundFileDoesNotBecomeDirectoryOrAnotherResource() {
        assertNull(bookContentTarget(node("FILE")))
    }


    @Test
    fun rootDirectoryDoesNotDependOnResourceCount() = runBlocking {
        for (count in listOf(0, 1, 3)) {
            val repository = DetailRepository((0 until count).map { resource("resource-$it") }, node("FOLDER"))
            val snapshot = assertIs<ContentResult.Content<BookContentSnapshot>>(
                loadBookContentPage(repository, requestContext, "book", BookContentTarget.Root, BookContentSort.NameAscending, 1)
            ).value
            assertEquals(BookContentTarget.Directory("node"), snapshot.target)
        }
    }

    @Test
    fun rootResourceUsesItsIdentityEvenWhenAnotherResourceWasRecentlyRead() = runBlocking {
        val repository = DetailRepository(listOf(resource("other"), resource("bound")), node("FOLDER", "bound"))
        val snapshot = assertIs<ContentResult.Content<BookContentSnapshot>>(
            loadBookContentPage(repository, requestContext, "book", BookContentTarget.Root, BookContentSort.NameAscending, 1)
        ).value
        assertEquals(BookContentTarget.ResourceDetail("bound"), snapshot.target)
    }

    @Test
    fun requestedResourceIsHydratedWithoutSelectingAnExistingDifferentResource() = runBlocking {
        val repository = DetailRepository(listOf(resource("other")), node("FOLDER"), listOf(resource("requested")))
        val snapshot = assertIs<ContentResult.Content<BookContentSnapshot>>(
            loadBookContentPage(repository, requestContext, "book", BookContentTarget.ResourceDetail("requested"), BookContentSort.NameAscending, 1)
        ).value
        assertEquals(BookContentTarget.ResourceDetail("requested"), snapshot.target)
        assertEquals(1, repository.resourceRequests)
        assertEquals(0, repository.contentsRequests)
    }

    @Test
    fun missingResourceDoesNotFallBackToTheFirstResource() = runBlocking {
        val repository = DetailRepository(listOf(resource("other")), node("FOLDER"))
        val result = loadBookContentPage(repository, requestContext, "book", BookContentTarget.ResourceDetail("missing"), BookContentSort.NameAscending, 1)
        assertEquals("CONTENT_NOT_ACCESSIBLE", assertIs<ContentResult.Failure>(result).error.code)
    }

    @Test
    fun directoryRequestKeepsItsSortAndPage() = runBlocking {
        val repository = DetailRepository(emptyList(), node("FOLDER"))
        loadBookContentPage(repository, requestContext, "book", BookContentTarget.Directory("node"), BookContentSort.SizeDescending, 3)
        assertEquals(BookContentsQuery("book", "node", BookContentSort.SizeDescending, 3), repository.lastContentsQuery)
    }

    @Test
    fun rootHydratesContinueResourceWithoutChangingDirectoryDestination() = runBlocking {
        val repository = DetailRepository(listOf(resource("other")), node("FOLDER"), listOf(resource("resume")), "resume")
        val snapshot = assertIs<ContentResult.Content<BookContentSnapshot>>(
            loadBookContentPage(repository, requestContext, "book", BookContentTarget.Root, BookContentSort.NameAscending, 1)
        ).value
        assertEquals(BookContentTarget.Directory("node"), snapshot.target)
        assertEquals("resume", snapshot.book.continueResourceId)
        assertEquals(listOf("other", "resume"), snapshot.book.resources.map { it.id })
        assertEquals(1, repository.resourceRequests)
    }

    @Test
    fun missingOrHiddenContinueResourceDoesNotSubstituteAnotherResource() = runBlocking {
        for (later in listOf(emptyList(), listOf(resource("resume").copy(hidden = true)))) {
            val repository = DetailRepository(listOf(resource("other")), node("FOLDER"), later, "resume")
            val snapshot = assertIs<ContentResult.Content<BookContentSnapshot>>(
                loadBookContentPage(repository, requestContext, "book", BookContentTarget.Root, BookContentSort.NameAscending, 1)
            ).value
            assertEquals("resume", snapshot.book.continueResourceId)
            assertNull(snapshot.book.resources.firstOrNull { it.id == snapshot.book.continueResourceId })
        }
    }

    private val requestContext: ContentRequestContext
        get() {
            val parsed = assertIs<com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult.Valid>(
                com.ermao.library.shared.modules.servers.domain.ServerBaseUrl.parse("https://library.example")
            )
            val profile = com.ermao.library.shared.modules.servers.domain.ServerProfile(
                "profile", "Library", parsed.baseUrl, "server", true,
                com.ermao.library.shared.modules.servers.domain.TlsMode.SystemTrust,
            )
            return ContentRequestContext(profile, com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace("server", "user", 1))
        }

    private class DetailRepository(
        private val resources: List<com.ermao.library.shared.modules.library.domain.Resource>,
        private val root: BookContentEntry,
        private val laterResources: List<com.ermao.library.shared.modules.library.domain.Resource> = emptyList(),
        private val continueResourceId: String? = resources.firstOrNull()?.id,
    ) : ContentRepository {
        var resourceRequests = 0
        var contentsRequests = 0
        var lastContentsQuery: BookContentsQuery? = null
        override suspend fun loadBookDetail(context: ContentRequestContext, query: BookDetailQuery) =
            ContentResult.Content(com.ermao.library.shared.modules.library.domain.BookDetailSummary(
                id = "book", sourceNodeId = "node", title = "Book", author = null, description = null,
                tags = emptyList(), seriesName = null, seriesIndex = null, coverStatus = "READY", coverUrl = "",
                continueResourceId = continueResourceId, continueResourceProgress = 75.0,
                completed = false, resources = resources,
            ))
        override suspend fun loadBookContents(context: ContentRequestContext, query: BookContentsQuery): ContentResult<BookContentsPage> {
            contentsRequests += 1
            lastContentsQuery = query
            return ContentResult.Content(BookContentsPage(
                bookId = "book", currentSourceNodeId = root.sourceNodeId, currentResourceId = root.resourceId,
                currentNode = root, currentResourceIds = resources.map { it.id }, parentSourceNodeId = null,
                breadcrumbs = emptyList(), entries = emptyList(), page = query.page, pageSize = query.pageSize,
                total = 0, totalPages = 1,
            ))
        }
        override suspend fun loadBookResources(context: ContentRequestContext, query: BookResourcePageQuery): ContentResult<BookResourcePage> {
            resourceRequests += 1
            return ContentResult.Content(BookResourcePage("book", laterResources, 1, 24, laterResources.size, 1))
        }
        override suspend fun loadHome(context: ContentRequestContext): Nothing = error("Unexpected home request")
        override suspend fun loadContinueReading(context: ContentRequestContext): Nothing = error("Unexpected continue-reading request")
        override suspend fun loadRecentReading(context: ContentRequestContext, limit: Int): Nothing = error("Unexpected recent-reading request")
        override suspend fun loadRecentAdded(context: ContentRequestContext, limit: Int): Nothing = error("Unexpected recent-added request")
        override suspend fun loadBooks(context: ContentRequestContext, query: BooksQuery): Nothing = error("Unexpected library request")
        override suspend fun loadGroupings(context: ContentRequestContext, query: GroupingQuery): Nothing = error("Unexpected groupings request")
        override suspend fun loadFacet(context: ContentRequestContext, query: FacetQuery): Nothing = error("Unexpected facet request")
        override suspend fun loadCover(context: ContentRequestContext, apiPath: String, etag: String?): Nothing = error("Unexpected cover request")
        override suspend fun invalidate(namespace: com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace): Nothing = error("Unexpected invalidation")
    }

    private fun node(kind: String, resourceId: String? = null) = BookContentEntry(
        sourceNodeId = "node", parentSourceNodeId = null, name = "node", title = "node",
        description = null, kind = kind, physicalKind = "DIRECTORY", sizeBytes = null,
        observedAt = "2026-08-27", hasChildren = true, resourceId = resourceId,
        representativeResourceId = "representative", coverUrl = null,
    )

    private fun BookContentSort.toWirePair() = sortWireValue to directionWireValue

    private fun resource(id: String) = com.ermao.library.shared.modules.library.domain.Resource(
        id = id,
        bookId = "book",
        sourceNodeId = "node-$id",
        title = id,
        description = null,
        resourceIndex = null,
        sortOrder = 0,
        format = "epub",
        readerType = "reflowable",
        readable = true,
        kindleSendAvailable = false,
        publisher = null,
        publishedAt = null,
        language = null,
        isbn = null,
        identifier = null,
        narrator = null,
        abridged = null,
        importStatus = "READY",
        importError = null,
        coverStatus = "READY",
        coverPath = null,
        coverUrl = "",
        sizeBytes = 1,
        pageCount = null,
        chapterCount = null,
        durationMillis = null,
        trackCount = null,
        progress = 0.0,
        lastReadAt = null,
        hidden = false,
        completed = false,
        assets = emptyList(),
    )
}
