package com.ermao.library.shared.modules.library

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

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
    fun singleReadableResourceOpensResourceDetail() {
        val selected = selectBookDetailPresentation(listOf(resource("readable")))

        assertEquals(BookDetailPresentation.ResourceDetail, selected.presentation)
        assertEquals("readable", selected.resourceId)
    }

    @Test
    fun multipleReadableResourcesOpenBrowserUnlessOneIsRequested() {
        val resources = listOf(resource("one"), resource("two"))

        val browser = selectBookDetailPresentation(resources)
        val detail = selectBookDetailPresentation(resources, "two")

        assertEquals(BookDetailPresentation.ContentBrowser, browser.presentation)
        assertNull(browser.resourceId)
        assertEquals(BookDetailPresentation.ResourceDetail, detail.presentation)
        assertEquals("two", detail.resourceId)
    }

    @Test
    fun hiddenOrUnreadableResourcesNeverBecomeTheSelectedDetail() {
        val hidden = resource("hidden").copy(hidden = true)
        val unreadable = resource("unreadable").copy(readable = false)

        val selected = selectBookDetailPresentation(listOf(hidden, unreadable), "hidden")

        assertEquals(BookDetailPresentation.ContentBrowser, selected.presentation)
        assertNull(selected.resourceId)
    }

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
