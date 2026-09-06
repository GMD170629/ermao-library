package com.ermao.library.features.library.application

import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.shared.modules.reader.ReaderChapterPresentation
import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionPresentationSnapshot
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import kotlin.test.assertEquals
import org.junit.Test

class DetailViewModelsTest {
    @Test
    fun liveReaderLocationUsesChapterIdentityWhenRuntimeHrefDiffers() {
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
                navigationKey = "chapter-2",
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
                        navigationKey = "chapter-2",
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

    @Test
    fun durableProgressProjectionPreservesIndependentReadingStatus() {
        val markedFinished = contentWithChapters(
            bookCompleted = true,
            resourceCompleted = false,
        ).applying(
            presentationSnapshot(displayPercent = 67.0),
            selectedResourceId = "resource-1",
        )

        assertEquals(true, markedFinished.completed)
        assertEquals(false, markedFinished.resources.single().completed)
        assertEquals(67, markedFinished.book.progressPercent)
        assertEquals(67, markedFinished.resources.single().progressPercent)

        val unmarkedAtEnd = contentWithChapters(
            bookCompleted = false,
            resourceCompleted = true,
        ).applying(
            presentationSnapshot(displayPercent = 100.0),
            selectedResourceId = "resource-1",
        )

        assertEquals(false, unmarkedAtEnd.completed)
        assertEquals(true, unmarkedAtEnd.resources.single().completed)
        assertEquals(100, unmarkedAtEnd.book.progressPercent)
        assertEquals(100, unmarkedAtEnd.resources.single().progressPercent)
    }

    private fun presentationSnapshot(displayPercent: Double) = ReaderPositionPresentationSnapshot(
        bookId = "book-1",
        resourceId = "resource-1",
        capturedAtEpochMillis = 123,
        presentation = ReaderPositionPresentation(
            displayPercent = displayPercent,
            totalProgression = displayPercent / 100.0,
            currentHref = null,
            chapter = null,
            page = null,
            playback = null,
        ),
    )

    private fun contentWithChapters(
        vararg chapters: ReadingUnitContent,
        bookCompleted: Boolean = false,
        resourceCompleted: Boolean = false,
    ): BookDetailContent = BookDetailContent(
        book = BookCard(
            id = "book-1",
            title = "Book",
            author = "Author",
            coverUrl = "",
            progressPercent = null,
            completed = bookCompleted,
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
                completed = resourceCompleted,
                readable = true,
                selected = true,
            ),
        ),
        selectedResourceId = "resource-1",
        completed = bookCompleted,
        readingUnits = chapters.toList(),
    )
}
