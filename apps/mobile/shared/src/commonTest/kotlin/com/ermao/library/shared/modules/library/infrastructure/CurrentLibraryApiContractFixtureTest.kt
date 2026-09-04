package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * JVM-side contract fixtures copied from the current FastAPI response models.
 *
 * Keep these fixtures representative of the route payloads, including the
 * absence of retired fields.  The FastAPI companion test exercises the routes
 * that produce these shapes; this test proves the mobile decoder accepts them
 * with the production strict-JSON policy.
 */
class CurrentLibraryApiContractFixtureTest {
    private val decoder = ApiEnvelopeDecoder(
        Json {
            ignoreUnknownKeys = false
            explicitNulls = false
        },
    )

    @Test
    fun decodesDashboardBooksWithImportSummary() {
        val result = decoder.decode(
            200,
            DASHBOARD_BOOKS_FIXTURE,
            BooksWire.serializer(),
        )

        val book = assertIs<ApiResult.Success<BooksWire>>(result).value.books.single()
        assertEquals("mobile-contract-book", book.id)
        assertEquals(0, book.resourceImportSummary.ready)
        assertEquals(42.0, book.progress)
    }

    @Test
    fun decodesGroupingPageWithoutRootKind() {
        val result = decoder.decode(
            200,
            GROUPINGS_FIXTURE,
            GroupingPageWire.serializer(),
        )

        val group = assertIs<ApiResult.Success<GroupingPageWire>>(result).value
            .toPage()
            .items
            .single()
        assertEquals("mobile-contract-author", group.id)
        assertEquals("mobile-contract-book", group.representativeBooks.single().id)
    }

    @Test
    fun decodesContinueReadingWithoutRetiredMediaKind() {
        val result = decoder.decode(
            200,
            CONTINUE_READING_FIXTURE,
            ContinueReadingPayloadWire.serializer(),
        )

        val item = assertIs<ApiResult.Success<ContinueReadingPayloadWire>>(result)
            .value
            .item
            ?: error("fixture did not contain a continue-reading item")
        assertEquals("mobile-contract-resource", item.resumeResourceId)
        assertEquals("PDF", item.resourceFormat)
        assertEquals(42.0, item.progress)
    }

    @Test
    fun decodesBookDetailAndResourcePageWithAssetTitles() {
        val detailResult = decoder.decode(
            200,
            BOOK_DETAIL_FIXTURE,
            BookPayloadWire.serializer(),
        )
        val detail = assertIs<ApiResult.Success<BookPayloadWire>>(detailResult)
            .value
            .toDomain()
        val resource = detail.resources.single()
        assertEquals("mobile-contract-resource", resource.id)
        assertEquals("PDF", resource.format)
        assertEquals("mobile-contract-resource.pdf", resource.assets.single().title)
        assertEquals("mobile-contract-book/mobile-contract-resource.pdf", resource.assets.single().path)

        val resourcesResult = decoder.decode(
            200,
            RESOURCES_FIXTURE,
            CurrentResourcesPayloadWire.serializer(),
        )
        val resources = assertIs<ApiResult.Success<CurrentResourcesPayloadWire>>(
            resourcesResult,
        ).value
        assertEquals("mobile-contract-book", resources.bookId)
        assertEquals("mobile-contract-resource", resources.resources.single().id)
        assertEquals("mobile-contract-resource.pdf", resources.resources.single().assets.single().title)
    }
}

@Serializable
private data class CurrentResourcesPayloadWire(
    val bookId: String,
    val resources: List<ResourceWire>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
)

private const val DASHBOARD_BOOKS_FIXTURE = """
    {"ok":true,"data":{"books":[{"id":"mobile-contract-book","title":"Mobile contract book","author":"Contract author","coverUrl":"/api/books/mobile-contract-book/cover?size=medium","resourceImportSummary":{"ready":0,"pending":0,"failed":0},"progress":42.0}]}}
"""

private const val GROUPINGS_FIXTURE = """
    {"ok":true,"data":{"groups":[{"id":"mobile-contract-author","name":"Contract author","bookCount":1,"updatedAt":"2026-08-12T00:00:00Z","representativeBooks":[{"id":"mobile-contract-book","title":"Mobile contract book","author":"Contract author","coverUrl":"/api/books/mobile-contract-book/cover?size=medium","updatedAt":"2026-08-12T00:00:00Z"}]}],"page":1,"pageSize":48,"total":1,"totalPages":1}}
"""

private const val CONTINUE_READING_FIXTURE = """
    {"ok":true,"data":{"item":{"bookId":"mobile-contract-book","title":"Mobile contract book","author":"Contract author","coverUrl":"/api/books/mobile-contract-book/cover?size=medium","resourceFormat":"PDF","readerType":"pdf","resumeResourceId":"mobile-contract-resource","progress":42.0,"lastReadAt":"2026-08-12T00:00:00Z","chapter":null,"resourceTitle":"Contract resource","narrator":null}}}
"""

private const val BOOK_DETAIL_FIXTURE = """
    {"ok":true,"data":{"book":{"id":"mobile-contract-book","libraryId":"test-library","sourceNodeId":"mobile-contract-book-node","title":"Mobile contract book","author":"Contract author","description":null,"seriesName":"Contract series","seriesIndex":null,"visibilityState":"VISIBLE","curationState":"PENDING","publicationStatus":"UNKNOWN","trackingStatus":"NOT_TRACKING","metadataQuality":0,"coverStatus":"PENDING","coverPath":null,"coverUrl":"/api/books/mobile-contract-book/cover?size=medium","tags":[],"ignored":false,"organized":false,"addedAt":"2026-08-12T00:00:00Z","createdAt":"2026-08-12T00:00:00Z","updatedAt":"2026-08-12T00:00:00Z","gradient":"","resources":[{"id":"mobile-contract-resource","bookId":"mobile-contract-book","sourceNodeId":"mobile-contract-resource-node","title":"Contract resource","description":null,"resourceIndex":1.0,"sortOrder":0,"format":"PDF","readerType":"pdf","kindleSendAvailable":false,"publisher":null,"publishedAt":null,"language":null,"isbn":null,"identifier":null,"narrator":null,"abridged":null,"importStatus":"READY","importError":null,"sizeBytes":1024,"pageCount":null,"chapterCount":null,"durationMs":null,"trackCount":null,"coverStatus":"PENDING","coverPath":null,"coverUrl":"/api/resources/mobile-contract-resource/cover","progress":42.0,"lastReadAt":"2026-08-12T00:00:00Z","hidden":false,"readable":true,"resourceCompleted":false,"assets":[{"id":"mobile-contract-asset","title":"mobile-contract-resource.pdf","path":"mobile-contract-book/mobile-contract-resource.pdf","resourceId":"mobile-contract-resource","sourceNodeId":"mobile-contract-resource-node","role":"PRIMARY","mimeType":"application/octet-stream","sizeBytes":1024,"size":"1 KB","mtimeMs":1724470400000,"durationMs":null,"codec":null,"bitrate":null,"sampleRate":null,"channels":null,"discNumber":null,"trackNumber":null,"sortOrder":0,"url":"/api/assets/mobile-contract-asset","downloadUrl":"/api/assets/mobile-contract-asset?download=true"}]}],"resourceImportSummary":{"ready":1,"pending":0,"failed":0},"completed":false,"continueResourceId":"mobile-contract-resource","continueResourceTitle":"Contract resource","continueResourceProgress":42.0}}}
"""

private const val RESOURCES_FIXTURE = """
    {"ok":true,"data":{"bookId":"mobile-contract-book","resources":[{"id":"mobile-contract-resource","bookId":"mobile-contract-book","sourceNodeId":"mobile-contract-resource-node","title":"Contract resource","resourceIndex":1.0,"sortOrder":0,"format":"PDF","readerType":"pdf","kindleSendAvailable":false,"importStatus":"READY","sizeBytes":1024,"coverStatus":"PENDING","coverUrl":"/api/resources/mobile-contract-resource/cover","progress":42.0,"lastReadAt":"2026-08-12T00:00:00Z","hidden":false,"readable":true,"resourceCompleted":false,"assets":[{"id":"mobile-contract-asset","title":"mobile-contract-resource.pdf","path":"mobile-contract-book/mobile-contract-resource.pdf","resourceId":"mobile-contract-resource","sourceNodeId":"mobile-contract-resource-node","role":"PRIMARY","mimeType":"application/octet-stream","sizeBytes":1024,"size":"1 KB","mtimeMs":1724470400000,"sortOrder":0,"url":"/api/assets/mobile-contract-asset","downloadUrl":"/api/assets/mobile-contract-asset?download=true"}]}],"page":1,"pageSize":50,"total":1,"totalPages":1}}
"""
