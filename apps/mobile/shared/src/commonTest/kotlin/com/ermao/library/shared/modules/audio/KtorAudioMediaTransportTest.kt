package com.ermao.library.shared.modules.audio

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.audio.application.AudioMediaOpenResult
import com.ermao.library.shared.modules.audio.domain.AudioAsset
import com.ermao.library.shared.modules.audio.infrastructure.KtorAudioMediaTransport
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.Headers
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.utils.io.ByteReadChannel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class KtorAudioMediaTransportTest {
    @Test
    fun rangeStreamUsesTheSharedOpenEndedRangeAndBoundedReads() = runBlocking {
        var observedRange: String? = null
        val transport = transport { request ->
            observedRange = request.headers[HttpHeaders.Range]
            respond(
                ByteReadChannel(byteArrayOf(1, 2, 3, 4, 5, 6)),
                HttpStatusCode.PartialContent,
                Headers.build {
                    append(HttpHeaders.ContentType, "audio/mp4")
                    append(HttpHeaders.ContentRange, "bytes 2-7/8")
                    append(HttpHeaders.AcceptRanges, "bytes")
                    append(HttpHeaders.ETag, "\"revision-1\"")
                },
            )
        }

        val result = transport.open(asset(), rangeStart = 2)
        val stream = assertIs<AudioMediaOpenResult.Content>(result).stream
        try {
            assertEquals(listOf<Byte>(1, 2, 3), stream.read(3).toList())
            assertEquals("bytes=2-", observedRange)
            assertTrue(stream.metadata.acceptsByteRanges)
            assertEquals(listOf<Byte>(4, 5, 6), stream.read(3).toList())
        } finally {
            stream.close()
        }
    }

    @Test
    fun crossOriginRedirectIsRejectedBeforeOpeningMediaBody() = runBlocking {
        val transport = transport {
            respond(
                "",
                HttpStatusCode.Found,
                Headers.build { append(HttpHeaders.Location, "https://other.example/api/assets/asset-1") },
            )
        }

        val failure = assertIs<AudioMediaOpenResult.Failure>(transport.open(asset(), rangeStart = 0))
        assertEquals("AUDIO_SECURITY_REJECTED", failure.error.code)
    }

    private fun transport(handler: suspend io.ktor.client.engine.mock.MockRequestHandleScope.(io.ktor.client.request.HttpRequestData) -> io.ktor.client.request.HttpResponseData) =
        KtorAudioMediaTransport(profile()) { profile ->
            ApiClient(
                profile,
                HttpClient(MockEngine(handler)) { followRedirects = false },
                Json { ignoreUnknownKeys = false; explicitNulls = false },
            )
        }

    private fun asset() = AudioAsset(
        assetId = "asset-1",
        resourceId = "resource-1",
        title = "Track",
        apiPath = "/api/assets/asset-1",
        mimeType = "audio/mp4",
        sizeBytes = 8,
        durationMillis = 60_000,
        discNumber = 1,
        trackNumber = 1,
        sortOrder = 0,
        codec = "aac",
    )

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }
}
