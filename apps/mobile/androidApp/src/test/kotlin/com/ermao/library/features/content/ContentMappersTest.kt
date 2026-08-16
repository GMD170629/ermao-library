package com.ermao.library.features.content

import com.ermao.library.features.content.model.toUiContent
import com.ermao.library.features.content.model.toEpochMillisOrNull
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.ActiveMedia
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.LocalProgressScope
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.domain.ProgressExtra
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.library.domain.ReadingUnitMetadata
import com.ermao.library.shared.modules.library.domain.MediaVersion
import com.ermao.library.shared.modules.library.domain.Volume
import com.ermao.library.shared.modules.library.domain.VolumeClassification
import com.ermao.library.shared.modules.library.domain.VolumeFile
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
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
            continueVolumeProgress = 0.0,
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
            continueVolumeProgress = 0.0,
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

    @Test
    fun detailProgressUsesTheContinueVolumeProjectionInsteadOfAnotherSelectedVolume() {
        val completedVolume = Volume(
            id = "volume-completed",
            mediaVersionId = "media-1",
            title = "Completed volume",
            volumeIndex = 1.0,
            sortOrder = 0,
            format = "EPUB",
            readerType = "reflowable",
            classification = VolumeClassification("AUTO", "epub", MediaKind.Ebook),
            readable = true,
            kindleSendAvailable = true,
            derivedFromVolumeId = null,
            publisher = null,
            publishedAt = "2010-11-01",
            language = "zh-CN",
            isbn = null,
            identifier = null,
            narrator = null,
            abridged = null,
            origin = "Embedded metadata",
            importStatus = null,
            importError = null,
            coverStatus = null,
            coverUrl = "",
            sizeBytes = 0,
            pageCount = 428,
            chapterCount = null,
            durationMillis = null,
            trackCount = null,
            progress = 100.0,
            completed = true,
            lastReadAt = null,
            files = listOf(
                VolumeFile(
                    id = "file-1",
                    volumeId = "volume-completed",
                    path = "library/golden-dream.epub",
                    mimeType = "application/epub+zip",
                    kind = "publication",
                    sortOrder = 0,
                    sizeBytes = 1024,
                    displaySize = "1 KB",
                    durationMillis = null,
                    codec = null,
                    bitrate = null,
                    sampleRate = null,
                    channels = null,
                    discNumber = null,
                    trackNumber = null,
                    url = null,
                ),
            ),
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
            continueVolumeId = "volume-reading",
            continueVolumeProgress = 75.0,
            completed = false,
            mediaVersions = listOf(
                MediaVersion(
                    id = "media-1",
                    mediaKind = MediaKind.Ebook,
                    completed = false,
                    volumeCount = 1,
                    sizeBytes = 0,
                    volumes = listOf(completedVolume),
                ),
            ),
            availableMediaKinds = listOf(MediaKind.Ebook),
            detailTabs = emptyList(),
            selectedDetailTab = "EBOOK",
            activeMedia = ActiveMedia(
                key = MediaKind.Ebook,
                formatLabel = "EPUB",
                mediaVersionId = "media-1",
                selectedVolumeId = completedVolume.id,
                selectedVolumeTitle = completedVolume.title,
                status = "FINISHED",
                progressStatus = "FINISHED",
                progress = 100.0,
                positionLabel = "",
                durationMillis = null,
                narrator = null,
                primaryAction = null,
                units = emptyList(),
                volumes = listOf(completedVolume),
                tracks = emptyList(),
                localProgressScope = LocalProgressScope("user-1", completedVolume.id),
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

        val content = detail.toUiContent()
        val mappedVolume = content.media.single().volumes.single()

        assertEquals(75, content.work.progressPercent)
        assertEquals(1, content.media.single().volumeCount)
        assertEquals("2010-11-01", mappedVolume.publishedAt)
        assertEquals("zh-CN", mappedVolume.language)
        assertEquals(428, mappedVolume.pageCount)
        assertEquals("Embedded metadata", mappedVolume.metadataSource)
        assertEquals("library/golden-dream.epub", mappedVolume.files.single().path)
    }
}
