package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.application.PdfRangeProbeResult
import com.ermao.library.shared.modules.reader.application.PdfRangeReadResult
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import com.ermao.library.shared.modules.reader.infrastructure.KtorPdfRangeServerPort
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertIs

class KtorPdfRangeServerPortTest {
    @Test
    fun validatesHeadAndReadsOnlyAnExactPartialResponse() = runBlocking {
        val requestedBytes = byteArrayOf(4, 5, 6, 7)
        val port = port { request ->
            assertEquals("/api/volumes/volume-1/file", request.url.encodedPath)
            when (request.method.value) {
                "HEAD" -> respond(
                    content = byteArrayOf(),
                    status = HttpStatusCode.OK,
                    headers = headersOf(
                        HttpHeaders.AcceptRanges to listOf("bytes"),
                        HttpHeaders.ContentLength to listOf(FILE_SIZE.toString()),
                    ),
                )
                "GET" -> {
                    assertEquals("bytes=4-7", request.headers[HttpHeaders.Range])
                    assertEquals(null, request.headers[HttpHeaders.IfRange])
                    respond(
                        content = requestedBytes,
                        status = HttpStatusCode.PartialContent,
                        headers = partialHeaders(4, 7, requestedBytes.size),
                    )
                }
                else -> error("Unexpected method ${request.method.value}")
            }
        }

        assertIs<PdfRangeProbeResult.Available>(port.probe(source()))
        val content = assertIs<PdfRangeReadResult.Content>(port.read(source(), PdfByteRange(4, 8)))
        assertEquals(PdfByteRange(4, 8), content.range)
        assertContentEquals(requestedBytes, content.bytes)
    }

    @Test
    fun rejectsWholeFileFallbackAndChangedLength() = runBlocking {
        val unsupported = assertIs<PdfRangeReadResult.Failure>(
            port { respond(byteArrayOf(1), HttpStatusCode.OK) }
                .read(source(), PdfByteRange(0, 1)),
        )
        assertEquals(PdfReaderErrorCode.RangeUnsupported, unsupported.code)
        assertEquals(false, unsupported.recoverable)

        val changed = assertIs<PdfRangeProbeResult.Failure>(
            port {
                respond(
                    byteArrayOf(), HttpStatusCode.OK,
                    headersOf(
                        HttpHeaders.AcceptRanges to listOf("bytes"),
                        HttpHeaders.ContentLength to listOf("15"),
                    ),
                )
            }.probe(source()),
        )
        assertEquals(PdfReaderErrorCode.ResourceChanged, changed.code)
    }

    @Test
    fun rejectsInvalidPartialResponsesAndRangeNotSatisfiable() = runBlocking {
        val malformed = assertIs<PdfRangeReadResult.Failure>(
            port {
                respond(
                    byteArrayOf(1, 2, 3, 4),
                    HttpStatusCode.PartialContent,
                    partialHeaders(5, 8, 4),
                )
            }.read(source(), PdfByteRange(4, 8)),
        )
        assertEquals(PdfReaderErrorCode.RangeInvalid, malformed.code)

        val unsatisfiable = assertIs<PdfRangeReadResult.Failure>(
            port { respond(byteArrayOf(), HttpStatusCode.RequestedRangeNotSatisfiable) }
                .read(source(), PdfByteRange(4, 8)),
        )
        assertEquals(PdfReaderErrorCode.RangeInvalid, unsatisfiable.code)
    }

    private fun port(
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ) = KtorPdfRangeServerPort(
        profile = profile(),
        createClient = { profile ->
            ApiClient(profile, HttpClient(MockEngine(handler)), Json { ignoreUnknownKeys = false })
        },
    )

    private fun source() = RemoteByteRangeReaderSource(
        sourceId = "volume-1",
        displayTitle = "PDF",
        workId = "work-1",
        volumeId = "volume-1",
        namespace = ReaderSyncNamespace("server-1", "user-1", 3),
        apiPath = "/api/volumes/volume-1/file",
        expectedSizeBytes = FILE_SIZE,
    )

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }

    private fun MockRequestHandleScope.partialHeaders(begin: Long, endInclusive: Long, length: Int) = headersOf(
        HttpHeaders.ContentRange to listOf("bytes $begin-$endInclusive/$FILE_SIZE"),
        HttpHeaders.ContentLength to listOf(length.toString()),
    )

    private companion object {
        const val FILE_SIZE = 16L
    }
}
