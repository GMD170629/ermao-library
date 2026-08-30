package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.application.PdfRangeProbeResult
import com.ermao.library.shared.modules.reader.application.PdfRangeReadResult
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
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
            assertEquals("/api/assets/asset-1", request.url.encodedPath)
            when (request.method.value) {
                "HEAD" -> respond(
                    content = byteArrayOf(),
                    status = HttpStatusCode.OK,
                    headers = headersOf(
                        HttpHeaders.AcceptRanges to listOf("bytes"),
                        HttpHeaders.ContentLength to listOf(FILE_SIZE.toString()),
                        HttpHeaders.ETag to listOf(STRONG_ETAG),
                        HttpHeaders.ContentType to listOf("application/pdf"),
                    ),
                )
                "GET" -> {
                    assertEquals("bytes=4-7", request.headers[HttpHeaders.Range])
                    assertEquals(STRONG_ETAG, request.headers[HttpHeaders.IfRange])
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
    fun acceptsTheGeneratedMaximumRequestRatherThanLimitingReadsToOneChunk() = runBlocking {
        val requestBytes = ReaderSafetyPolicy
            .budget(ReaderSafetyBudgetName.PDF_RANGE_REQUEST_MAX_BYTES)
            .toInt()
        val expected = ByteArray(requestBytes) { (it % 251).toByte() }
        val largeSource = source(expectedSizeBytes = requestBytes.toLong())
        val port = port { request ->
            if (request.method.value == "HEAD") {
                respond(
                    byteArrayOf(),
                    HttpStatusCode.OK,
                    headersOf(
                        HttpHeaders.AcceptRanges to listOf("bytes"),
                        HttpHeaders.ContentLength to listOf(requestBytes.toString()),
                        HttpHeaders.ETag to listOf(STRONG_ETAG),
                        HttpHeaders.ContentType to listOf("application/pdf"),
                    ),
                )
            } else {
                assertEquals("bytes=0-${requestBytes - 1}", request.headers[HttpHeaders.Range])
                respond(
                    expected,
                    HttpStatusCode.PartialContent,
                    partialHeaders(0, requestBytes.toLong() - 1, requestBytes, requestBytes.toLong()),
                )
            }
        }

        assertIs<PdfRangeProbeResult.Available>(port.probe(largeSource))
        val content = assertIs<PdfRangeReadResult.Content>(
            port.read(largeSource, PdfByteRange(0, requestBytes.toLong())),
        )
        assertContentEquals(expected, content.bytes)
    }

    @Test
    fun rejectsWholeFileFallbackAndChangedLength() = runBlocking {
        val unsupported = assertIs<PdfRangeReadResult.Failure>(
            port { respond(byteArrayOf(1), HttpStatusCode.OK) }
                .read(source(), PdfByteRange(0, 1)),
        )
        assertEquals(PdfReaderErrorCode.RangeInvalid, unsupported.code)
        assertEquals(false, unsupported.recoverable)

        val changed = assertIs<PdfRangeProbeResult.Failure>(
            port {
                respond(
                    byteArrayOf(), HttpStatusCode.OK,
                    headersOf(
                        HttpHeaders.AcceptRanges to listOf("bytes"),
                        HttpHeaders.ContentLength to listOf("15"),
                        HttpHeaders.ContentType to listOf("application/pdf"),
                    ),
                )
            }.probe(source()),
        )
        assertEquals(PdfReaderErrorCode.ResourceChanged, changed.code)
        assertEquals(
            ReaderSafetyRuleId.PDF_RANGE_PROTOCOL.wireValue,
            changed.safetyFailure?.ruleId,
        )
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

    @Test
    fun weakEtagIsRejectedAndChangedStrongRevisionIsRejectedBeforeBody() = runBlocking {
        val etag = "W/\"version\""
        val date = "Thu, 27 Aug 2026 00:00:00 GMT"
        val gateway = port { request ->
            if (request.method.value == "HEAD") respond(byteArrayOf(), HttpStatusCode.OK, headersOf(
                HttpHeaders.AcceptRanges to listOf("bytes"), HttpHeaders.ContentLength to listOf(FILE_SIZE.toString()),
                HttpHeaders.ETag to listOf(etag), HttpHeaders.LastModified to listOf(date),
                HttpHeaders.ContentType to listOf("application/pdf"),
                )) else {
                assertEquals(STRONG_ETAG, request.headers[HttpHeaders.IfRange])
                respond(byteArrayOf(1, 2, 3, 4), HttpStatusCode.PartialContent, headersOf(
                    HttpHeaders.ContentRange to listOf("bytes 4-7/$FILE_SIZE"), HttpHeaders.ContentLength to listOf("4"),
                    HttpHeaders.ETag to listOf("W/\"changed\""),
                    HttpHeaders.ContentType to listOf("application/pdf"),
                ))
            }
        }
        assertEquals(
            PdfReaderErrorCode.RangeInvalid,
            assertIs<PdfRangeProbeResult.Failure>(gateway.probe(source())).code,
        )

        val available = port { request ->
            if (request.method.value == "HEAD") respond(
                byteArrayOf(), HttpStatusCode.OK, headersOf(
                    HttpHeaders.AcceptRanges to listOf("bytes"),
                    HttpHeaders.ContentLength to listOf(FILE_SIZE.toString()),
                    HttpHeaders.ETag to listOf(STRONG_ETAG),
                    HttpHeaders.ContentType to listOf("application/pdf"),
                )
            ) else respond(
                byteArrayOf(1, 2, 3, 4), HttpStatusCode.PartialContent, headersOf(
                    HttpHeaders.ContentRange to listOf("bytes 4-7/$FILE_SIZE"),
                    HttpHeaders.ContentLength to listOf("4"),
                    HttpHeaders.ETag to listOf("\"changed\""),
                    HttpHeaders.ContentType to listOf("application/pdf"),
                )
            )
        }
        assertIs<PdfRangeProbeResult.Available>(available.probe(source()))
        assertEquals(
            PdfReaderErrorCode.ResourceChanged,
            assertIs<PdfRangeReadResult.Failure>(available.read(source(), PdfByteRange(4, 8))).code,
        )
    }

    private fun port(
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ) = KtorPdfRangeServerPort(
        profile = profile(),
        createClient = { profile ->
            ApiClient(profile, HttpClient(MockEngine(handler)), Json { ignoreUnknownKeys = false })
        },
    )

    private fun source(expectedSizeBytes: Long = FILE_SIZE) = RemoteByteRangeReaderSource(
        resourceId = "resource-1",
        displayTitle = "PDF",
        bookId = "book-1",
        assetId = "asset-1",
        namespace = ReaderSyncNamespace("server-1", "user-1", 3),
        apiPath = "/api/assets/asset-1",
        expectedSizeBytes = expectedSizeBytes,
    )

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }

    private fun MockRequestHandleScope.partialHeaders(
        begin: Long,
        endInclusive: Long,
        length: Int,
        totalLength: Long = FILE_SIZE,
    ) = headersOf(
        HttpHeaders.ContentRange to listOf("bytes $begin-$endInclusive/$totalLength"),
        HttpHeaders.ContentLength to listOf(length.toString()),
        HttpHeaders.ETag to listOf(STRONG_ETAG),
        HttpHeaders.ContentType to listOf("application/pdf"),
    )

    private companion object {
        const val FILE_SIZE = 16L
        const val STRONG_ETAG = "\"version\""
    }
}
