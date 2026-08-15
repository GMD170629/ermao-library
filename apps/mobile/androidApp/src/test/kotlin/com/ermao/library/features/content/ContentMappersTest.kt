package com.ermao.library.features.content

import com.ermao.library.features.content.model.toUiContent
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.ActiveMedia
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.LocalProgressScope
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.domain.ProgressExtra
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.library.domain.ReadingUnitMetadata
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import kotlin.test.assertEquals
import org.junit.Test

class ContentMappersTest {
    @Test
    fun detailUsesStableFacetIdentifiers() {
        val detail = WorkDetailSummary(
            id = "work-1",
            title = "Title",
            author = "Author",
            description = null,
            tags = emptyList(),
            seriesName = "Series",
            seriesFacet = AppliedFacet("series-1", FacetKind.Series, "Series"),
            authorFacets = listOf(AppliedFacet("author-1", FacetKind.Author, "Author")),
            seriesIndex = 1.0,
            coverStatus = "ready",
            coverUrl = "/api/works/work-1/cover",
            recentMediaKind = MediaKind.Ebook,
            continueVolumeId = null,
            completed = false,
            mediaVersions = emptyList(),
            availableMediaKinds = listOf(MediaKind.Ebook),
            detailTabs = emptyList(),
            selectedDetailTab = "EBOOK",
        )

        val mapped = detail.toUiContent()

        assertEquals("series-1", mapped.seriesId)
        assertEquals("author-1", mapped.authorFacetId)
    }

    @Test
    fun detailFallsBackToActiveMediaUnitsForSingleEbookDirectory() {
        val chapter = ReadingUnit(
            id = "chapter-1",
            volumeId = "volume-1",
            fileId = null,
            unitType = "chapter",
            title = "Chapter 1",
            href = "chapter-1.xhtml",
            mediaType = "application/xhtml+xml",
            sortOrder = 1,
            startMillis = null,
            endMillis = null,
            durationMillis = null,
            width = null,
            height = null,
            sizeBytes = null,
            metadata = ReadingUnitMetadata(
                exactNavigation = null,
                level = null,
                path = null,
                navigationKey = null,
                zipEntryName = null,
                idref = null,
                linear = null,
                properties = null,
                volumeIndex = null,
                trackIndex = null,
                pageNumber = null,
                sourceFileName = null,
                hrefBase = null,
                recovered = null,
                readingOrderPosition = 7,
            ),
            createdAt = null,
            updatedAt = null,
        )
        val detail = WorkDetailSummary(
            id = "work-1",
            title = "Title",
            author = "Author",
            description = null,
            tags = emptyList(),
            seriesName = null,
            seriesIndex = null,
            coverStatus = "ready",
            coverUrl = "",
            recentMediaKind = MediaKind.Ebook,
            continueVolumeId = "volume-1",
            completed = false,
            mediaVersions = emptyList(),
            availableMediaKinds = listOf(MediaKind.Ebook),
            detailTabs = emptyList(),
            selectedDetailTab = "EBOOK",
            activeMedia = ActiveMedia(
                key = MediaKind.Ebook,
                formatLabel = "EPUB",
                mediaVersionId = "media-1",
                selectedVolumeId = "volume-1",
                selectedVolumeTitle = "Book",
                status = "UNREAD",
                progressStatus = "UNREAD",
                progress = 0.0,
                positionLabel = "",
                durationMillis = null,
                narrator = null,
                primaryAction = null,
                units = listOf(chapter),
                volumes = emptyList(),
                tracks = emptyList(),
                localProgressScope = LocalProgressScope("user-1", "volume-1"),
                currentHref = null,
                currentSectionIndex = null,
                currentChapterTitle = null,
                currentChapterIndex = null,
                currentPageNumber = null,
                currentChapterSortOrder = null,
                progressExtra = ProgressExtra(),
                progressEstimated = false,
            ),
        )

        val mappedUnit = detail.toUiContent().readingUnits.single()
        assertEquals("Chapter 1", mappedUnit.title)
        assertEquals(7, mappedUnit.readingOrderPosition)
    }
}
