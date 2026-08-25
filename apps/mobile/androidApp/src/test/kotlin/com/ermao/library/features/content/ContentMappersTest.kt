package com.ermao.library.features.content

import com.ermao.library.features.content.model.toUiContent
import com.ermao.library.features.content.model.toEpochMillisOrNull
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.Asset
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.Resource
import java.time.Instant
import kotlin.test.assertEquals
import org.junit.Test

class ContentMappersTest {
    @Test
    fun continueTimestampIsValidatedAtTheMappingBoundary() {
        val wireTimestamp = "2026-08-15T13:47:38.286000Z"

        assertEquals(Instant.parse(wireTimestamp).toEpochMilli(), wireTimestamp.toEpochMillisOrNull())
        assertEquals(null, "not-a-timestamp".toEpochMillisOrNull())
        assertEquals(null, "  ".toEpochMillisOrNull())
    }

    @Test
    fun detailUsesStableFacetIdentifiers() {
        val detail = BookDetailSummary(
            id = "book-1",
            sourceNodeId = "source-book-1",
            title = "Title",
            author = "Author",
            description = null,
            tags = emptyList(),
            seriesName = "Series",
            seriesFacet = AppliedFacet("series-1", FacetKind.Series, "Series"),
            authorFacets = listOf(AppliedFacet("author-1", FacetKind.Author, "Author")),
            seriesIndex = 1.0,
            coverStatus = "ready",
            coverUrl = "/api/books/book-1/cover",
            continueResourceId = null,
            continueResourceProgress = 0.0,
            completed = false,
            resources = emptyList(),
        )

        val mapped = detail.toUiContent()

        assertEquals("series-1", mapped.seriesId)
        assertEquals("author-1", mapped.authorFacetId)
        assertEquals(emptyList(), mapped.resources)
    }

    @Test
    fun detailProgressUsesTheContinueResourceProjectionInsteadOfAnotherSelectedResource() {
        val completedResource = Resource(
            id = "resource-completed",
            bookId = "book-1",
            sourceNodeId = "source-resource-1",
            title = "Completed resource",
            description = null,
            resourceIndex = 1.0,
            sortOrder = 0,
            format = "EPUB",
            readerType = "reflowable",
            readable = true,
            kindleSendAvailable = true,
            publisher = null,
            publishedAt = "2010-11-01",
            language = "zh-CN",
            isbn = null,
            identifier = null,
            narrator = null,
            abridged = null,
            importStatus = "READY",
            importError = null,
            coverStatus = "ready",
            coverPath = null,
            coverUrl = "",
            sizeBytes = 0,
            pageCount = 428,
            chapterCount = null,
            durationMillis = null,
            trackCount = null,
            progress = 100.0,
            completed = true,
            hidden = false,
            lastReadAt = null,
            assets = listOf(
                Asset(
                    id = "asset-1",
                    title = "golden-dream.epub",
                    resourceId = "resource-completed",
                    sourceNodeId = "source-asset-1",
                    role = "publication",
                    mimeType = "application/epub+zip",
                    sizeBytes = 1024,
                    displaySize = "1 KB",
                    mtimeMillis = null,
                    durationMillis = null,
                    codec = null,
                    bitrate = null,
                    sampleRate = null,
                    channels = null,
                    discNumber = null,
                    trackNumber = null,
                    sortOrder = 0,
                    url = null,
                    downloadUrl = "library/golden-dream.epub",
                ),
            ),
        )
        val detail = BookDetailSummary(
            id = "book-1",
            sourceNodeId = "source-book-1",
            title = "Title",
            author = "Author",
            description = null,
            tags = emptyList(),
            seriesName = null,
            seriesIndex = null,
            coverStatus = "ready",
            coverUrl = "",
            continueResourceId = "resource-reading",
            continueResourceProgress = 75.0,
            completed = false,
            resources = listOf(completedResource),
        )

        val content = detail.toUiContent()
        val mappedResource = content.resources.single()

        assertEquals(75, content.book.progressPercent)
        assertEquals("resource-completed", content.resources.single().id)
        assertEquals("2010-11-01", mappedResource.publishedAt)
        assertEquals("zh-CN", mappedResource.language)
        assertEquals(428, mappedResource.pageCount)
        assertEquals(null, mappedResource.metadataSource)
        assertEquals("library/golden-dream.epub", mappedResource.assets.single().path)
    }
}
