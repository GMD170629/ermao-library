package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.LibraryContract
import com.ermao.library.shared.modules.library.domain.MediaKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json

class WorkDetailQueryWireTest {
    @Test
    fun decodesReadingUnitNavigationPathFromWorkDetailResponse() {
        val metadata = STRICT_JSON.decodeFromString(
            ReadingUnitMetadataWire.serializer(),
            """{"exactNavigation":true,"path":[0,1,3],"readingOrderPosition":7}""",
        )

        assertEquals(true, metadata.exactNavigation)
        assertEquals(listOf(0, 1, 3), metadata.path)
        assertEquals(7, metadata.readingOrderPosition)
    }

    @Test
    fun decodesAndMapsTheFullWorkDetailQueryContractStrictly() {
        val result = ApiEnvelopeDecoder(STRICT_JSON).decode(
            statusCode = 200,
            body = FULL_WORK_DETAIL_FIXTURE.replace(
                "\"level\":1,\"navigationKey\"",
                "\"level\":1,\"path\":[0,1,3],\"readingOrderPosition\":7,\"originalName\":\"001.jpg\",\"pageInVolume\":1,\"pageInSection\":1,\"navigationKey\"",
            ),
            dataDeserializer = WorkDetailPayloadWire.serializer(),
        )
        val wire = assertIs<ApiResult.Success<WorkDetailPayloadWire>>(result).value
        val detail = LibraryContract.workDetail(wire)

        assertEquals("full-work", detail.id)
        assertEquals(25.0, detail.continueVolumeProgress)
        assertEquals("chapter-1", detail.readingUnits.single().id)
        assertEquals(listOf(0, 1, 3), detail.readingUnits.single().metadata.path)
        assertEquals(7, detail.readingUnits.single().metadata.readingOrderPosition)
        assertEquals("chapter-1.xhtml", detail.readingUnits.single().metadata.navigationKey)
        assertEquals("001.jpg", detail.readingUnits.single().metadata.originalName)
        assertEquals(1, detail.readingUnits.single().metadata.pageInVolume)
        assertEquals(1, detail.readingUnits.single().metadata.pageInSection)
        assertEquals(2, detail.readingUnitsPage.totalPages)
        assertEquals("volume-1", detail.volumeSections.single().id)
        assertEquals("version-1", detail.volumeSections.single().versionId)
        assertEquals(120.0, detail.volumeSections.single().progressExtra.remainingTotalSeconds)
    }

    @Test
    fun exposesAnIndependentWorkSummaryModel() {
        val summary = LibraryContract.workSummary(
            WorkSummaryWire(
                id = "work-1",
                title = "书名",
                author = "作者",
                coverUrl = "/api/works/work-1/cover",
                availableMediaKinds = listOf("EBOOK"),
                progress = 25.0,
            ),
        )
        assertEquals("work-1", summary.id)
        assertEquals(listOf(MediaKind.Ebook), summary.availableMediaKinds)
        assertEquals(25.0, summary.progress)
    }

    @Test
    fun decodesAndMapsAPaginatedVolumePageWithoutDroppingSelectedVolumeMetadata() {
        val wire = STRICT_JSON.decodeFromString(
            WorkVolumePageWire.serializer(),
            VOLUME_PAGE_FIXTURE,
        )

        val page = wire.toDomain()
        val volume = page.volumes.single()

        assertEquals("version-1", page.versionId)
        assertEquals("__implicit__", page.sourceKey)
        assertNull(page.sourceName)
        assertEquals(2, page.page)
        assertEquals(3, page.totalPages)
        assertEquals("2010-11-01", volume.publishedAt)
        assertEquals("zh-CN", volume.language)
        assertEquals(428, volume.pageCount)
        assertEquals("Embedded metadata", volume.origin)
        assertEquals("library/golden-dream.epub", volume.files.single().path)
        assertEquals("version-1", volume.versionId)
    }
}

private val STRICT_JSON = Json { ignoreUnknownKeys = false }

private const val VOLUME_PAGE_FIXTURE = """{"versionId":"version-1","sourceKey":"__implicit__","sourceName":null,"volumes":[{"id":"volume-2","versionId":"version-1","title":"第二册","volumeIndex":2.0,"sortOrder":1,"format":"EPUB","readerType":"reflowable","classification":{"source":"AUTO","reason":"epub","suggestedMediaKind":"EBOOK"},"readable":true,"kindleSendAvailable":true,"publisher":"Publisher","publishedAt":"2010-11-01","language":"zh-CN","isbn":null,"identifier":null,"narrator":null,"abridged":null,"origin":"Embedded metadata","importStatus":"READY","importError":null,"coverStatus":"READY","pageCount":428,"chapterCount":12,"trackCount":null,"sizeBytes":1024,"coverUrl":"/api/volumes/volume-2/cover","progress":0.0,"completed":false,"lastReadAt":null,"durationMs":null,"files":[{"id":"file-2","volumeId":"volume-2","path":"library/golden-dream.epub","mimeType":"application/epub+zip","kind":"publication","sortOrder":0,"sizeBytes":1024,"size":"1 KB","durationMs":null,"codec":null,"bitrate":null,"sampleRate":null,"channels":null,"discNumber":null,"trackNumber":null,"url":null}]}],"page":2,"pageSize":24,"total":49,"totalPages":3}"""

private const val FULL_WORK_DETAIL_FIXTURE = """{"ok":true,"data":{"book":{"id":"full-work","title":"Full work","author":"Author","description":"Description","publicationStatus":"ONGOING","trackingStatus":"TRACKING","tags":["tag"],"seriesName":"Series","seriesIndex":1.0,"organized":true,"organizeStatus":"COMPLETED","metadataQuality":90,"metadataLookupStatus":"SUCCESS","metadataLookupSource":"provider","metadataLookupError":null,"coverStatus":"READY","coverUrl":"/api/works/full-work/cover","continueVolumeId":"volume-1","continueVolumeTitle":"正文","continueVolumeProgress":25.0,"completed":false,"lastReadAt":"2026-08-11T10:00:00Z","addedAt":"2026-08-01T10:00:00Z","versions":[]},"readingUnits":[{"id":"chapter-1","volumeId":"volume-1","fileId":"file-1","unitType":"chapter","title":"第一章","href":"chapter-1.xhtml","mediaType":"application/xhtml+xml","sortOrder":0,"startMs":null,"endMs":null,"durationMs":null,"width":null,"height":null,"size":1024,"metadataJson":{"exactNavigation":true,"level":1,"navigationKey":"chapter-1.xhtml","zipEntryName":null,"idref":"chapter-1","linear":true,"properties":[],"volumeIndex":1.0,"trackIndex":null,"pageNumber":null,"sourceFileName":"book.epub","hrefBase":"publication-root","recovered":false},"createdAt":"2026-08-01T10:00:00Z","updatedAt":"2026-08-01T10:00:00Z"}],"volumeSections":[{"id":"volume-1","versionId":"version-1","title":"正文","index":1.0,"fileId":"file-1","pageCount":4,"coverUrl":"/api/volumes/volume-1/cover","progress":25.0,"lastReadAt":"2026-08-11T10:00:00Z","position":"chapter-1.xhtml","currentPage":1,"currentHref":"chapter-1.xhtml","currentSectionIndex":0,"currentChapterTitle":"第一章","currentChapterIndex":0,"currentChapterSortOrder":0,"progressExtra":{"remainingTotalSeconds":120},"progressEstimated":false}],"readingUnitsPage":{"page":1,"pageSize":50,"total":51,"totalPages":2}}}"""
