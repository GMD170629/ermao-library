package com.ermao.library.features.content

import com.ermao.library.features.content.model.toUiContent
import com.ermao.library.features.content.model.toEpochMillisOrNull
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.domain.Volume
import com.ermao.library.shared.modules.library.domain.VolumeClassification
import com.ermao.library.shared.modules.library.domain.VolumeFile
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkVersion
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
            continueVolumeId = null,
            continueVolumeProgress = 0.0,
            completed = false,
            versions = emptyList(),
        )

        val mapped = detail.toUiContent()

        assertEquals("series-1", mapped.seriesId)
        assertEquals("author-1", mapped.authorFacetId)
        assertEquals(emptyList(), mapped.versions)
    }

    @Test
    fun detailProgressUsesTheContinueVolumeProjectionInsteadOfAnotherSelectedVolume() {
        val completedVolume = Volume(
            id = "volume-completed",
            versionId = "version-1",
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
            continueVolumeId = "volume-reading",
            continueVolumeProgress = 75.0,
            completed = false,
            versions = listOf(
                WorkVersion(
                    id = "version-1",
                    sourceKey = "__implicit__",
                    sourceName = null,
                    completed = false,
                    volumeCount = 1,
                    sizeBytes = 0,
                    volumes = listOf(completedVolume),
                ),
            ),
        )

        val content = detail.toUiContent()
        val mappedVolume = content.versions.single().volumes.single()

        assertEquals(75, content.work.progressPercent)
        assertEquals("version-1", content.versions.single().id)
        assertEquals("__implicit__", content.versions.single().sourceKey)
        assertEquals(1, content.versions.single().volumeCount)
        assertEquals("version-1", mappedVolume.versionId)
        assertEquals("2010-11-01", mappedVolume.publishedAt)
        assertEquals("zh-CN", mappedVolume.language)
        assertEquals(428, mappedVolume.pageCount)
        assertEquals("Embedded metadata", mappedVolume.metadataSource)
        assertEquals("library/golden-dream.epub", mappedVolume.files.single().path)
    }
}
