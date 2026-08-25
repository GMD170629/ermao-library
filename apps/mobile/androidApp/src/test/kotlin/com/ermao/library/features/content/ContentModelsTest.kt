package com.ermao.library.features.content

import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.ReadingFilter
import com.ermao.library.features.content.model.WorksFilters
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class ContentModelsTest {
    @Test
    fun resourceIndexUsesServerValueAndFallsBackToOneBasedPosition() {
        val base = ResourceContent(
            id = "resource-1",
            title = "Resource",
            format = "EPUB",
            progressPercent = null,
            readable = true,
            selected = false,
        )

        assertEquals("01", base.displayIndex(0))
        assertEquals("03", base.copy(resourceIndex = 3.0).displayIndex(0))
        assertEquals("1.5", base.copy(resourceIndex = 1.5).displayIndex(0))
    }

    @Test
    fun filterCountIncludesOnlySupportedPhaseSevenOptions() {
        val filters = WorksFilters(
            reading = ReadingFilter.Reading,
            downloadedOnly = true,
        )

        assertEquals(2, filters.count)
    }

    @Test
    fun onlyReflowableResourcesExposeAChapterDirectory() {
        val chapter = listOf(ReadingUnitContent("chapter-1", "Chapter 1"))
        val reflowable = ResourceContent(
            id = "epub",
            title = "EPUB",
            format = "EPUB",
            readerType = "reflowable",
            progressPercent = null,
            readable = true,
            selected = true,
        )
        val detail = BookDetailContent(
            book = BookCard("book-1", "Title", "Author", "", null),
            seriesId = null,
            seriesName = null,
            authorFacetId = null,
            description = null,
            tags = emptyList(),
            resources = listOf(reflowable),
            selectedResourceId = reflowable.id,
            readingUnits = chapter,
        )

        assertTrue(detail.supportsChapterDirectory(reflowable.id))
        assertFalse(detail.copy(resources = listOf(reflowable.copy(format = "PDF", readerType = "pdf", id = "pdf"))).supportsChapterDirectory("pdf"))
        assertFalse(detail.copy(resources = listOf(reflowable.copy(format = "CBZ", readerType = "comic", id = "comic"))).supportsChapterDirectory("comic"))
    }

    @Test
    fun emptyDescriptionAndSingleMediaHideRedundantControls() {
        val resource = ResourceContent(
            id = "resource-1",
            title = "EPUB",
            format = "EPUB",
            progressPercent = null,
            readable = true,
            selected = true,
        )
        val content = BookDetailContent(
            book = BookCard("book-1", "Title", "Author", "", null),
            seriesId = null,
            seriesName = null,
            authorFacetId = null,
            description = "  ",
            tags = emptyList(),
            resources = listOf(resource),
            selectedResourceId = resource.id,
        )

        assertFalse(content.hasDescription)
        assertFalse(content.showsResourcePicker)
        assertTrue(content.copy(description = "Description").hasDescription)
        assertTrue(
            content.copy(
                resources = content.resources + resource.copy(
                    id = "resource-2",
                    title = "Kindle",
                    format = "MOBI",
                    selected = false,
                ),
            ).showsResourcePicker,
        )
    }
}
