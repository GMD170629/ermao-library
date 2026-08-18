package com.ermao.library.features.content

import com.ermao.library.features.content.model.MediaFilter
import com.ermao.library.features.content.model.VersionContent
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
    fun onlyReflowableVolumesExposeAChapterDirectory() {
        val chapter = listOf(ReadingUnitContent("chapter-1", "Chapter 1"))
        val reflowable = VolumeContent(
            id = "epub",
            title = "EPUB",
            format = "EPUB",
            readerType = "reflowable",
            versionId = "version-1",
            progressPercent = null,
            readable = true,
            selected = true,
        )
        val detail = WorkDetailContent(
            work = WorkCard("work-1", "Title", "Author", "", listOf("EBOOK"), null),
            seriesId = null,
            seriesName = null,
            authorFacetId = null,
            description = null,
            tags = emptyList(),
            versions = listOf(VersionContent("version-1", "__implicit__", volumes = listOf(reflowable))),
            selectedVersionId = "version-1",
            readingUnits = chapter,
        )

        assertTrue(detail.supportsChapterDirectory(reflowable.id))
        assertFalse(detail.copy(versions = listOf(VersionContent("version-pdf", "__implicit__", volumes = listOf(reflowable.copy(format = "PDF", readerType = "pdf", id = "pdf"))))).supportsChapterDirectory("pdf"))
        assertFalse(detail.copy(versions = listOf(VersionContent("version-comic", "comic", volumes = listOf(reflowable.copy(format = "CBZ", readerType = "comic", id = "comic"))))).supportsChapterDirectory("comic"))
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
            versions = listOf(VersionContent("version-1", "__implicit__", volumes = emptyList())),
            selectedVersionId = "version-1",
        )

        assertFalse(content.hasDescription)
        assertFalse(content.showsVersionPicker)
        assertTrue(content.copy(description = "Description").hasDescription)
        assertTrue(
            content.copy(
                versions = content.versions + VersionContent("version-2", "kindle", sourceName = "Kindle", volumes = emptyList()),
            ).showsVersionPicker,
        )
    }
}
