package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.domain.FacetKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertNotNull
import kotlinx.serialization.json.Json

class ContentWireTest {
    private val decoder = ApiEnvelopeDecoder(Json { ignoreUnknownKeys = false; explicitNulls = false })

    @Test
    fun decodesFacetPageWithStableIdentity() {
        val result = decoder.decode(
            200,
            """{"ok":true,"data":{"books":[],"page":1,"pageSize":24,"total":0,"totalPages":1,"appliedFacet":{"id":"series-1","kind":"SERIES","name":"Saga"}}}""",
            WorkPageWire.serializer(),
        )

        val page = assertNotNull(assertIs<ApiResult.Success<WorkPageWire>>(result).value.toFacetPage())
        assertEquals("series-1", page.facet.id)
        assertEquals(FacetKind.Series, page.facet.kind)
    }

    @Test
    fun missingFacetIdentityIsRejectedWithoutThrowingAcrossPlatformBoundary() {
        val result = decoder.decode(
            200,
            """{"ok":true,"data":{"books":[],"page":1,"pageSize":24,"total":0,"totalPages":1,"appliedFacet":null}}""",
            WorkPageWire.serializer(),
        )

        assertNull(assertIs<ApiResult.Success<WorkPageWire>>(result).value.toFacetPage())
    }

    @Test
    fun groupingRepresentativeWorksAreBounded() {
        val result = decoder.decode(
            200,
            """{"ok":true,"data":{"kind":"AUTHOR","groups":[{"id":"author-1","name":"Ursula","bookCount":4,"updatedAt":"2026-01-01T00:00:00Z","representativeWorks":[${representativeWork("1")},${representativeWork("2")},${representativeWork("3")}]}],"page":1,"pageSize":30,"total":1,"totalPages":1}}""",
            GroupingPageWire.serializer(),
        )

        val group = assertIs<ApiResult.Success<GroupingPageWire>>(result).value.toPage().items.single()
        assertEquals(listOf("1", "2", "3"), group.representativeWorks.map { it.id })
    }

    @Test
    fun decodesCurrentContinueReadingContractWithoutDroppingStrictFields() {
        val result = decoder.decode(
            200,
            """{"ok":true,"data":{"item":{"workId":"work-1","title":"Title","author":"Author","coverUrl":"/api/works/work-1/cover","mediaKind":"EBOOK","volumeFormat":"EPUB","readerType":"reflowable","resumeVolumeId":"volume-1","progress":42.0,"chapter":null,"lastReadAt":"2026-08-12T00:00:00Z","volumeTitle":"Volume 1","narrator":null}}}""",
            ContinueReadingPayloadWire.serializer(),
        )

        val item = assertIs<ApiResult.Success<ContinueReadingPayloadWire>>(result).value.item
        assertEquals("work-1", item?.toDomain()?.workId)
        assertEquals("EPUB", item?.volumeFormat)
        assertEquals("reflowable", item?.readerType)
        assertNull(item?.chapter)
    }

    private fun work(id: String) =
        """{"id":"$id","title":"Title $id","author":"Author","coverUrl":"/api/works/$id/cover","availableMediaKinds":["EBOOK"],"progress":0.0}"""

    private fun representativeWork(id: String) =
        """{"id":"$id","title":"Title $id","author":"Author","coverUrl":"/api/works/$id/cover"}"""
}
