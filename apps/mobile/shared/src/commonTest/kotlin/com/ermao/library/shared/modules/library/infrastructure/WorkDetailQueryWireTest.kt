package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.LibraryContract
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json

class WorkDetailQueryWireTest {
    @Test
    fun mapsReadingUnitsAndResourceSectionsToBookResourceAssetIdentities() {
        val result = ApiEnvelopeDecoder(STRICT_JSON).decode(
            statusCode = 200,
            body = BOOK_DETAIL_QUERY_FIXTURE,
            dataDeserializer = BookDetailPayloadWire.serializer(),
        )
        val detail = LibraryContract.bookDetail(
            assertIs<ApiResult.Success<BookDetailPayloadWire>>(result).value,
        )

        assertEquals("book-1", detail.id)
        assertEquals("resource-1", detail.continueResourceId)
        assertEquals("resource-1", detail.readingUnits.single().resourceId)
        assertEquals("asset-1", detail.readingUnits.single().assetId)
        assertEquals("resource-1", detail.resourceSections.single().resourceId)
        assertEquals("asset-1", detail.resourceSections.single().assetId)
        assertEquals(2, detail.readingUnitsPage.totalPages)
    }

    @Test
    fun mapsProgressExtraResourceAndAssetReferences() {
        val wire = STRICT_JSON.decodeFromString(
            ProgressExtraWire.serializer(),
            """{"resourceId":"resource-1","assetId":"asset-1","positionMs":1200,"progressEstimated":true}""",
        )

        val extra = wire.toProgressExtraForTest()
        assertEquals("resource-1", extra.resourceId)
        assertEquals("asset-1", extra.assetId)
        assertEquals(1200, extra.positionMillis)
        assertEquals(true, extra.progressEstimated)
    }
}

private val STRICT_JSON = Json { ignoreUnknownKeys = false; explicitNulls = false }

private const val BOOK_DETAIL_QUERY_FIXTURE = """{"ok":true,"data":{"book":{"id":"book-1","libraryId":"library-1","sourceNodeId":"source-node-1","title":"Book 1","author":"Author","description":null,"seriesName":null,"seriesIndex":null,"visibilityState":"ACTIVE","curationState":"NONE","publicationStatus":"ONGOING","trackingStatus":"TRACKING","metadataQuality":80,"coverStatus":"READY","coverUrl":"/api/books/book-1/cover","tags":[],"completed":false,"continueResourceId":"resource-1","continueResourceTitle":"Resource 1","continueResourceProgress":25.0,"resources":[]},"readingUnits":[{"id":"unit-1","resourceId":"resource-1","assetId":"asset-1","unitType":"chapter","title":"Chapter 1","href":"chapter-1.xhtml","mediaType":"application/xhtml+xml","sortOrder":0,"size":1024,"metadataJson":"{}","createdAt":"2026-08-01T00:00:00Z","updatedAt":"2026-08-01T00:00:00Z"}],"resourceSections":[{"id":"section-1","resourceId":"resource-1","title":"Resource 1","index":1.0,"assetId":"asset-1","pageCount":4,"coverUrl":"/api/books/book-1/resources/resource-1/cover","progress":25.0,"progressExtra":{"resourceId":"resource-1","assetId":"asset-1","positionMs":1200,"progressEstimated":true},"progressEstimated":true}],"readingUnitsPage":{"page":1,"pageSize":50,"total":51,"totalPages":2}}}"""

private fun ProgressExtraWire.toProgressExtraForTest() = com.ermao.library.shared.modules.library.domain.ProgressExtra(
    cfi = cfi,
    progression = progression,
    navigationKey = navigationKey,
    navigationFingerprint = navigationFingerprint,
    sourceFormat = sourceFormat,
    assetId = assetId,
    chapterId = chapterId,
    positionMillis = positionMs,
    resourceId = resourceId,
    pageIndex = pageIndex,
    chapterHref = chapterHref,
    currentHref = currentHref,
    chapterSectionIndex = chapterSectionIndex,
    sectionIndex = sectionIndex,
    chapterIndex = chapterIndex,
    chapterSortOrder = chapterSortOrder,
    chapterTitle = chapterTitle,
    sectionPage = sectionPage,
    sectionTotalPages = sectionTotalPages,
    sectionTotal = sectionTotal,
    locationCurrent = locationCurrent,
    locationNext = locationNext,
    locationTotal = locationTotal,
    remainingSectionSeconds = remainingSectionSeconds,
    remainingTotalSeconds = remainingTotalSeconds,
    progressEstimated = progressEstimated,
)
