package com.ermao.library.shared.core.network

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
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

class ApiClientStreamingDownloadTest {
    @Test
    fun rejectsRedirectWithoutConsumingPublicationIntoTheSink() = runBlocking {
        var writes = 0
        val result = client(
            status = HttpStatusCode.Found,
            bytes = ByteArray(256 * 1024),
            extraHeaders = mapOf(HttpHeaders.Location to "/api/files/other"),
        ).streamAuthenticatedDownload(PATH, 512 * 1024L, MIMES) { _, _ -> writes += 1 }

        val failure = assertIs<ApiResult.Failure>(result).error
        assertEquals("DOWNLOAD_REDIRECT_REJECTED", failure.code, failure.diagnosticMessage)
        assertEquals(0, writes)
    }

    @Test
    fun rejectsDeclaredOversizeBeforeWritingAChunk() = runBlocking {
        var writes = 0
        val result = client(
            bytes = ByteArray(1_000),
            extraHeaders = mapOf(HttpHeaders.ContentLength to "1000"),
        ).streamAuthenticatedDownload(PATH, 10, MIMES) { _, _ -> writes += 1 }

        val failure = assertIs<ApiResult.Failure>(result).error
        assertEquals("DOWNLOAD_TOO_LARGE", failure.code, failure.diagnosticMessage)
        assertEquals(0, writes)
    }

    @Test
    fun detectsOverflowEvenWithoutContentLength() = runBlocking {
        var received = 0
        val result = client(bytes = ByteArray(11), includeContentLength = false)
            .streamAuthenticatedDownload(PATH, 10, MIMES) { _, count -> received += count }

        assertEquals("DOWNLOAD_TOO_LARGE", assertIs<ApiResult.Failure>(result).error.code)
        assertTrue(received <= 10)
    }

    @Test
    fun rejectsEmptyAndLyingContentLengthResponses() = runBlocking {
        val empty = client(bytes = byteArrayOf(), includeContentLength = false)
            .streamAuthenticatedDownload(PATH, 10, MIMES) { _, _ -> }
        val mismatched = consumeStreamedDownloadBody(
            channel = ByteReadChannel(byteArrayOf(1, 2, 3)),
            maximumBytes = 10,
            declaredSize = 2,
        ) { _, _ -> }

        assertEquals("DOWNLOAD_EMPTY", assertIs<ApiResult.Failure>(empty).error.code)
        val mismatchFailure = assertIs<StreamedDownloadBodyResult.Failure>(mismatched).error
        assertEquals("DOWNLOAD_LENGTH_MISMATCH", mismatchFailure.code, mismatchFailure.diagnosticMessage)
    }

    @Test
    fun cancellationFromNativeSinkPropagates() {
        assertFailsWith<CancellationException> {
            runBlocking {
                client(bytes = ByteArray(10), includeContentLength = false)
                    .streamAuthenticatedDownload(PATH, 10, MIMES) { _, _ ->
                        throw CancellationException("native sink cancelled")
                    }
            }
        }
    }

    @Test
    fun oversizedErrorEnvelopeIsBounded() = runBlocking {
        val result = client(
            status = HttpStatusCode.InternalServerError,
            bytes = ByteArray(70 * 1024) { 'x'.code.toByte() },
            includeContentLength = false,
        ).streamAuthenticatedDownload(PATH, 100_000, MIMES) { _, _ -> }

        assertEquals("DOWNLOAD_ERROR_BODY_TOO_LARGE", assertIs<ApiResult.Failure>(result).error.code)
    }

    private fun client(
        status: HttpStatusCode = HttpStatusCode.OK,
        bytes: ByteArray,
        includeContentLength: Boolean = true,
        extraHeaders: Map<String, String> = emptyMap(),
    ): ApiClient {
        val headers = Headers.build {
            append(HttpHeaders.ContentType, "application/epub+zip")
            if (includeContentLength && HttpHeaders.ContentLength !in extraHeaders) {
                append(HttpHeaders.ContentLength, bytes.size.toString())
            }
            extraHeaders.forEach { (name, value) -> append(name, value) }
        }
        val engine = MockEngine {
            respond(ByteReadChannel(bytes), status, headers)
        }
        return ApiClient(
            profile(),
            HttpClient(engine) { followRedirects = false },
            Json { ignoreUnknownKeys = false },
        )
    }

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile", "Books", baseUrl, "server", true, TlsMode.SystemTrust)
    }

    private companion object {
        const val PATH = "/api/files/publication"
        val MIMES = setOf("application/epub+zip")
    }
}
