package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.LibraryContract
import com.ermao.library.shared.modules.library.domain.MediaKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
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
                "\"level\":1,\"path\":[0,1,3],\"readingOrderPosition\":7,\"navigationKey\"",
            ),
            dataDeserializer = WorkDetailPayloadWire.serializer(),
        )
        val wire = assertIs<ApiResult.Success<WorkDetailPayloadWire>>(result).value
        val detail = LibraryContract.workDetail(wire)

        assertEquals("full-work", detail.id)
        assertEquals(MediaKind.Ebook, detail.activeMedia?.key)
        assertEquals("chapter-1", detail.readingUnits.single().id)
        assertEquals(listOf(0, 1, 3), detail.readingUnits.single().metadata.path)
        assertEquals(7, detail.readingUnits.single().metadata.readingOrderPosition)
        assertEquals("chapter-1.xhtml", detail.readingUnits.single().metadata.navigationKey)
        assertEquals(2, detail.readingUnitsPage.totalPages)
        assertEquals("volume-1", detail.volumeSections.single().id)
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
}

private val STRICT_JSON = Json { ignoreUnknownKeys = false }

private const val FULL_WORK_DETAIL_FIXTURE = """{"ok":true,"data":{"book":{"id":"full-work","title":"Full work","author":"Author","description":"Description","publicationStatus":"ONGOING","trackingStatus":"TRACKING","tags":["tag"],"seriesName":"Series","seriesIndex":1.0,"organized":true,"organizeStatus":"COMPLETED","metadataQuality":90,"metadataLookupStatus":"SUCCESS","metadataLookupSource":"provider","metadataLookupError":null,"coverStatus":"READY","coverUrl":"/api/works/full-work/cover","recentMediaKind":"EBOOK","continueVolumeId":"volume-1","continueVolumeTitle":"正文","continueVolumeProgress":25.0,"completed":false,"lastReadAt":"2026-08-11T10:00:00Z","addedAt":"2026-08-01T10:00:00Z","mediaVersions":[],"availableMediaKinds":["EBOOK"],"detailTabs":[{"key":"EBOOK","label":"电子书","sortOrder":0}],"selectedDetailTab":"EBOOK"},"activeMedia":{"key":"EBOOK","formatLabel":"EPUB","mediaVersionId":"media-1","selectedVolumeId":"volume-1","selectedVolumeTitle":"正文","status":"READING","progressStatus":"READING","progress":25.0,"positionLabel":"第 1 章","durationMs":null,"narrator":null,"primaryAction":{"label":"继续阅读","href":"/reader/volume-1"},"units":[{"id":"chapter-1","volumeId":"volume-1","fileId":"file-1","unitType":"chapter","title":"第一章","href":"chapter-1.xhtml","mediaType":"application/xhtml+xml","sortOrder":0,"startMs":null,"endMs":null,"durationMs":null,"width":null,"height":null,"size":1024,"metadataJson":{"exactNavigation":true,"level":1,"navigationKey":"chapter-1.xhtml","zipEntryName":null,"idref":"chapter-1","linear":true,"properties":[],"volumeIndex":1.0,"trackIndex":null,"pageNumber":null,"sourceFileName":"book.epub","hrefBase":"publication-root","recovered":false},"createdAt":"2026-08-01T10:00:00Z","updatedAt":"2026-08-01T10:00:00Z"}],"volumes":[],"tracks":[],"localProgressScope":{"userId":"user-1","volumeId":"volume-1","contentFingerprint":"fingerprint-1"},"currentHref":"chapter-1.xhtml","currentSectionIndex":0,"currentChapterTitle":"第一章","currentChapterIndex":0,"currentPageNumber":null,"currentChapterSortOrder":0,"progressExtra":{"cfi":"epubcfi(/6/2)","progression":0.25,"navigationKey":"chapter-1.xhtml","navigationFingerprint":"fingerprint-1","sourceFormat":"epub","fileId":"file-1","chapterId":"chapter-1","positionMs":null,"volumeId":"volume-1","pageIndex":null,"chapterHref":"chapter-1.xhtml","currentHref":"chapter-1.xhtml","chapterSectionIndex":0,"sectionIndex":0,"chapterIndex":0,"chapterSortOrder":0,"chapterTitle":"第一章","sectionPage":1,"sectionTotalPages":4,"sectionTotal":4,"locationCurrent":1,"locationNext":2,"locationTotal":4,"remainingSectionSeconds":30,"remainingTotalSeconds":120,"progressEstimated":false},"progressEstimated":false},"readingUnits":[{"id":"chapter-1","volumeId":"volume-1","fileId":"file-1","unitType":"chapter","title":"第一章","href":"chapter-1.xhtml","mediaType":"application/xhtml+xml","sortOrder":0,"startMs":null,"endMs":null,"durationMs":null,"width":null,"height":null,"size":1024,"metadataJson":{"exactNavigation":true,"level":1,"navigationKey":"chapter-1.xhtml","zipEntryName":null,"idref":"chapter-1","linear":true,"properties":[],"volumeIndex":1.0,"trackIndex":null,"pageNumber":null,"sourceFileName":"book.epub","hrefBase":"publication-root","recovered":false},"createdAt":"2026-08-01T10:00:00Z","updatedAt":"2026-08-01T10:00:00Z"}],"volumeSections":[{"id":"volume-1","mediaVersionId":"media-1","title":"正文","index":1.0,"fileId":"file-1","pageCount":4,"coverUrl":"/api/volumes/volume-1/cover","progress":25.0,"lastReadAt":"2026-08-11T10:00:00Z","position":"chapter-1.xhtml","currentPage":1,"currentHref":"chapter-1.xhtml","currentSectionIndex":0,"currentChapterTitle":"第一章","currentChapterIndex":0,"currentChapterSortOrder":0,"progressExtra":{"remainingTotalSeconds":120},"progressEstimated":false}],"readingUnitsPage":{"page":1,"pageSize":50,"total":51,"totalPages":2}}}"""
