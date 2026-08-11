package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.domain.MediaKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.serialization.json.Json

class WorkDetailWireTest {
    @Test
    fun decodesAndMapsTheRealBoundedWorkDetailShape() {
        val decoded = ApiEnvelopeDecoder(Json { ignoreUnknownKeys = false }).decode(
            statusCode = 200,
            body = WORK_DETAIL_FIXTURE,
            dataDeserializer = WorkDetailSummaryPayloadWire.serializer(),
        )
        val work = assertIs<ApiResult.Success<WorkDetailSummaryPayloadWire>>(decoded).value.toDomain()

        assertEquals("detail-work", work.id)
        assertEquals(MediaKind.Comic, work.mediaVersions.single().mediaKind)
        assertEquals(12, work.mediaVersions.single().volumeCount)
        assertEquals("/library/detail-01.zip", work.mediaVersions.single().volumes.single().files.single().path)
        assertEquals(listOf(MediaKind.Comic), work.availableMediaKinds)
    }
}

private const val WORK_DETAIL_FIXTURE = """{"ok":true,"data":{"book":{"id":"detail-work","title":"Detail work","author":"Author","description":null,"tags":[],"seriesName":null,"seriesIndex":null,"coverStatus":"READY","coverUrl":"/api/works/detail-work/cover","recentMediaKind":"COMIC","continueVolumeId":"detail-volume-01","completed":false,"mediaVersions":[{"id":"detail-media","mediaKind":"COMIC","completed":false,"volumeCount":12,"sizeBytes":7800,"volumes":[{"id":"detail-volume-01","mediaVersionId":"detail-media","title":"第 1 卷","volumeIndex":1.0,"sortOrder":0,"format":"COMIC","readerType":"comic","classification":{"source":"AUTO","reason":"archive","suggestedMediaKind":"COMIC"},"readable":true,"conversionAvailable":false,"kindleSendAvailable":false,"derivedFromVolumeId":null,"publisher":null,"publishedAt":null,"language":"zh-CN","isbn":null,"identifier":null,"narrator":null,"coverUrl":"/api/volumes/detail-volume-01/cover","sizeBytes":100,"pageCount":2,"chapterCount":null,"durationMs":null,"trackCount":null,"progress":12.5,"files":[{"id":"detail-file-01","path":"/library/detail-01.zip","sizeBytes":100,"size":"100 B"}]}]}],"availableMediaKinds":["COMIC"],"detailTabs":[{"key":"COMIC","label":"漫画","sortOrder":0}],"selectedDetailTab":"COMIC"}}}"""
