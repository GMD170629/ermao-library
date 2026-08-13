package com.ermao.library.features.content

import com.ermao.library.features.content.model.MediaFilter
import com.ermao.library.features.content.model.MediaContent
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.ReadingFilter
import com.ermao.library.features.content.model.VolumeContent
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.model.WorkDetailContent
import com.ermao.library.features.content.model.WorksFilters
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class ContentModelsTest {
    @Test
    fun volumeIndexUsesServerValueAndFallsBackToOneBasedPosition() {
        val base = VolumeContent(
            id = "volume-1",
            title = "Volume",
            format = "EPUB",
            progressPercent = null,
            readable = true,
            selected = false,
        )

        assertEquals("01", base.displayIndex(0))
        assertEquals("03", base.copy(volumeIndex = 3.0).displayIndex(0))
        assertEquals("1.5", base.copy(volumeIndex = 1.5).displayIndex(0))
    }

    @Test
    fun filterCountIncludesOnlySupportedPhaseSevenOptions() {
        val filters = WorksFilters(
            media = setOf(MediaFilter.Ebook, MediaFilter.Audiobook),
            reading = setOf(ReadingFilter.Reading),
        )

        assertEquals(3, filters.count)
    }

    @Test
    fun singleEbookVolumeFallsBackToChaptersOnlyWhenReadingUnitsExist() {
        val ebook = MediaContent(
            kind = "EBOOK",
            volumes = listOf(VolumeContent("volume-1", "Book", "EPUB", progressPercent = 34, readable = true, selected = true)),
        )
        val base = WorkDetailContent(
            work = WorkCard("work-1", "Title", "Author", "", listOf("EBOOK"), 34),
            seriesId = null,
            seriesName = null,
            authorFacetId = null,
            description = "Description",
            tags = emptyList(),
            media = listOf(ebook),
            selectedMediaKind = "EBOOK",
        )

        assertFalse(base.usesEbookChapterFallback("EBOOK"))
        assertTrue(
            base.copy(readingUnits = listOf(ReadingUnitContent("chapter-1", "Chapter 1")))
                .usesEbookChapterFallback("EBOOK"),
        )
        assertFalse(
            base.copy(readingUnits = listOf(ReadingUnitContent("chapter-1", "Chapter 1")))
                .usesEbookChapterFallback("COMIC"),
        )
    }

    @Test
    fun emptyDescriptionAndSingleMediaHideRedundantControls() {
        val content = WorkDetailContent(
            work = WorkCard("work-1", "Title", "Author", "", listOf("EBOOK"), null),
            seriesId = null,
            seriesName = null,
            authorFacetId = null,
            description = "  ",
            tags = emptyList(),
            media = listOf(MediaContent("EBOOK", emptyList())),
            selectedMediaKind = "EBOOK",
        )

        assertFalse(content.hasDescription)
        assertFalse(content.showsMediaPicker)
        assertTrue(content.copy(description = "Description").hasDescription)
        assertTrue(content.copy(media = content.media + MediaContent("COMIC", emptyList())).showsMediaPicker)
    }
}
