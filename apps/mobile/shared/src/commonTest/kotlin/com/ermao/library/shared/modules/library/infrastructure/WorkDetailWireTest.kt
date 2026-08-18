package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.domain.IMPLICIT_WORK_VERSION_SOURCE_KEY
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
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
        val version = work.versions.single()
        val volume = version.volumes.single()

        assertEquals("detail-work", work.id)
        assertEquals("detail-version", version.id)
        assertEquals(IMPLICIT_WORK_VERSION_SOURCE_KEY, version.sourceKey)
        assertNull(version.sourceName)
        assertEquals(12, version.volumeCount)
        assertEquals("detail-version", volume.versionId)
        assertEquals("/library/detail-01.zip", volume.files.single().path)
    }

    @Test
    fun mixedFormatsStayInASingleVersionAndDoNotRequireLegacyMediaFields() {
        val decoded = ApiEnvelopeDecoder(Json { ignoreUnknownKeys = false }).decode(
            statusCode = 200,
            body = MIXED_FORMAT_WORK_DETAIL_FIXTURE,
            dataDeserializer = WorkDetailSummaryPayloadWire.serializer(),
        )
        val work = assertIs<ApiResult.Success<WorkDetailSummaryPayloadWire>>(decoded).value.toDomain()
        val version = work.versions.single()

        assertEquals("named-scan", version.sourceKey)
        assertEquals("2024 scan", version.sourceName)
        assertEquals(4, version.volumes.size)
        assertEquals(listOf("EPUB", "PDF", "CBZ", "AUDIO"), version.volumes.map { it.format })
        assertEquals(setOf("version-1"), version.volumes.map { it.versionId }.toSet())
    }
}

private fun volumeFixture(
    id: String,
    format: String,
    readerType: String,
    suggestedMediaKind: String,
): String = """
{"id":"$id","versionId":"version-1","title":"$id","volumeIndex":1.0,"sortOrder":0,"format":"$format","readerType":"$readerType","classification":{"source":"AUTO","reason":"file","suggestedMediaKind":"$suggestedMediaKind"},"readable":true,"kindleSendAvailable":false,"derivedFromVolumeId":null,"publisher":null,"publishedAt":null,"language":"zh-CN","isbn":null,"identifier":null,"narrator":null,"coverUrl":"/api/volumes/$id/cover","sizeBytes":100,"pageCount":2,"chapterCount":null,"durationMs":null,"trackCount":null,"progress":0.0,"files":[{"id":"$id-file","path":"/library/$id","sizeBytes":100,"size":"100 B"}]}
""".trimIndent()

private const val WORK_DETAIL_FIXTURE = """{"ok":true,"data":{"book":{"id":"detail-work","title":"Detail work","author":"Author","description":null,"tags":[],"seriesName":null,"seriesIndex":null,"coverStatus":"READY","coverUrl":"/api/works/detail-work/cover","continueVolumeId":"detail-volume-01","completed":false,"versions":[{"id":"detail-version","sourceKey":"__implicit__","sourceName":null,"completed":false,"volumeCount":12,"sizeBytes":7800,"volumes":[{"id":"detail-volume-01","versionId":"detail-version","title":"第 1 卷","volumeIndex":1.0,"sortOrder":0,"format":"COMIC","readerType":"comic","classification":{"source":"AUTO","reason":"archive","suggestedMediaKind":"COMIC"},"readable":true,"kindleSendAvailable":false,"derivedFromVolumeId":null,"publisher":null,"publishedAt":null,"language":"zh-CN","isbn":null,"identifier":null,"narrator":null,"coverUrl":"/api/volumes/detail-volume-01/cover","sizeBytes":100,"pageCount":2,"chapterCount":null,"durationMs":null,"trackCount":null,"progress":12.5,"files":[{"id":"detail-file-01","path":"/library/detail-01.zip","sizeBytes":100,"size":"100 B"}]}]}]}}}"""

private val MIXED_FORMAT_WORK_DETAIL_FIXTURE = """
{"ok":true,"data":{"book":{"id":"mixed-work","title":"Mixed work","author":"Author","description":null,"tags":[],"seriesName":null,"seriesIndex":null,"coverStatus":"READY","coverUrl":"/api/works/mixed-work/cover","continueVolumeId":null,"completed":false,"versions":[{"id":"version-1","sourceKey":"named-scan","sourceName":"2024 scan","completed":false,"volumeCount":4,"sizeBytes":400,"volumes":[${volumeFixture("epub-1", "EPUB", "reflowable", "EBOOK")},${volumeFixture("pdf-1", "PDF", "pdf", "EBOOK")},${volumeFixture("cbz-1", "CBZ", "comic", "COMIC")},${volumeFixture("audio-1", "AUDIO", "audio", "AUDIOBOOK")}]}]}}}
""".trimIndent()
