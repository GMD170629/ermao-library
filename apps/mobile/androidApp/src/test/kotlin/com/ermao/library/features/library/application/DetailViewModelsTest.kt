package com.ermao.library.features.library.application

import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.shared.modules.reader.ReaderChapterPresentation
import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import kotlin.test.assertEquals
import org.junit.Test

class DetailViewModelsTest {
    @Test
    fun liveReaderLocationUsesReadingOrderPositionWhenRuntimeHrefDiffers() {
        val content = contentWithChapters(
            ReadingUnitContent(
                id = "chapter-1",
                title = "Chapter 1",
                href = "text/part0003.html",
                sortOrder = 1,
                readingOrderPosition = 3,
            ),
            ReadingUnitContent(
                id = "chapter-2",
                title = "Chapter 2",
                href = "text/part0008_split_000.html",
                sortOrder = 4,
                readingOrderPosition = 10,
            ),
            ReadingUnitContent(
                id = "chapter-3",
                title = "Chapter 3",
                href = "text/part0009.html",
                sortOrder = 5,
                readingOrderPosition = 13,
            ),
        )

        val update = ReaderProgressPresentationUpdate(
            namespaceKey = "server:user",
            bookId = "book-1",
            resourceId = "resource-1",
            position = ReaderPositionReport(
                locator = ReaderOpaqueLocator.parse(
                    """{"href":"text/part0008_split_001.html","type":"application/xhtml+xml","locations":{"cssSelector":"body","fragments":["visible"],"position":11}}""",
                ),
                presentation = ReaderPositionPresentation(
                    displayPercent = 42.0,
                    totalProgression = 0.42,
                    currentHref = "text/part0008_split_001.html",
                    chapter = ReaderChapterPresentation(
                        href = "text/part0008_split_000.html",
                        title = "Chapter 2",
                        index = 1,
                    ),
                    page = null,
                    playback = null,
                ),
            ),
            capturedAtEpochMillis = 123,
        )
        val updated = content.applying(update, selectedResourceId = "resource-1")

        assertEquals(
            listOf(ChapterReadingState.Read, ChapterReadingState.Current, ChapterReadingState.Unread),
            updated.readingUnits.map(ReadingUnitContent::readingState),
        )
        assertEquals(listOf(null, 42, null), updated.readingUnits.map(ReadingUnitContent::progressPercent))
        val parentDirectory = content.applying(update, selectedResourceId = null)
        assertEquals(content.book, parentDirectory.book)
        assertEquals(content.readingUnits, parentDirectory.readingUnits)
        assertEquals(42, parentDirectory.resources.single().progressPercent)
        assertEquals("resource-1", parentDirectory.continueResourceId)
        assertEquals(42, parentDirectory.continueResource?.progressPercent)
    }

    private fun contentWithChapters(vararg chapters: ReadingUnitContent): BookDetailContent = BookDetailContent(
        book = BookCard(
            id = "book-1",
            title = "Book",
            author = "Author",
            coverUrl = "",
            progressPercent = null,
        ),
        seriesId = null,
        seriesName = null,
        authorFacetId = null,
        description = null,
        tags = emptyList(),
        resources = listOf(
            ResourceContent(
                id = "resource-1",
                title = "Resource",
                format = "EPUB",
                progressPercent = null,
                readable = true,
                selected = true,
            ),
        ),
        selectedResourceId = "resource-1",
        readingUnits = chapters.toList(),
    )
}
