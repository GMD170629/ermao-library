package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.reader.application.PdfRangeProbeResult
import com.ermao.library.shared.modules.reader.application.PdfRangeReadResult
import com.ermao.library.shared.modules.reader.application.PdfRangeServerPort
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.request.prepareHead
import io.ktor.client.request.headers
import io.ktor.client.request.prepareGet
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.HttpHeaders
import io.ktor.utils.io.readAvailable
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow

class KtorPdfRangeServerPort internal constructor(
    private val profile: ServerProfile,
    private val createClient: (ServerProfile) -> ApiClient,
) : PdfRangeServerPort {
    constructor(profile: ServerProfile, clients: ApiClientFactory) : this(profile, clients::create)
    private data class Revision(val source: RemoteByteRangeReaderSource, val etag: String, val ifRange: String?)
    private val revision = MutableStateFlow<Revision?>(null)

    override suspend fun probe(source: RemoteByteRangeReaderSource): PdfRangeProbeResult = withClient { client ->
        try {
            client.authenticatedHttpClient().prepareHead(client.resolveAuthenticatedApiPath(source.apiPath)).execute { response ->
            val result = when {
                response.status.value !in 200..299 -> PdfRangeProbeResult.Failure(
                    PdfReaderErrorCode.NetworkUnavailable,
                    recoverable = true,
                )
                response.headers[HttpHeaders.AcceptRanges]?.split(',')
                    ?.map(String::trim)?.any { it.equals("bytes", ignoreCase = true) } != true ->
                    PdfRangeProbeResult.Failure(PdfReaderErrorCode.RangeUnsupported, recoverable = false)
                response.headers[HttpHeaders.ContentLength]?.toLongOrNull() != source.expectedSizeBytes ->
                    PdfRangeProbeResult.Failure(PdfReaderErrorCode.ResourceChanged, recoverable = false)
                else -> {
                    revision.value = response.headers[HttpHeaders.ETag]?.let { etag ->
                        Revision(source, etag, etag.takeUnless { it.startsWith("W/") }
                            ?: response.headers[HttpHeaders.LastModified])
                    }
                    PdfRangeProbeResult.Available
                }
            }
            response.bodyAsChannel().cancel(null)
            result
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: HttpRequestTimeoutException) {
            PdfRangeProbeResult.Failure(PdfReaderErrorCode.NetworkUnavailable, recoverable = true)
        } catch (_: Throwable) {
            PdfRangeProbeResult.Failure(PdfReaderErrorCode.NetworkUnavailable, recoverable = true)
        }
    }

    override suspend fun read(
        source: RemoteByteRangeReaderSource,
        range: PdfByteRange,
    ): PdfRangeReadResult = withClient { client ->
        try {
            require(range.endExclusive <= source.expectedSizeBytes)
            require(range.endExclusive - range.begin <= 1024L * 1024)
            client.authenticatedHttpClient().prepareGet(client.resolveAuthenticatedApiPath(source.apiPath)) {
                headers {
                    append(HttpHeaders.Range, "bytes=${range.begin}-${range.endExclusive - 1}")
                    revision.value?.takeIf { it.source == source }?.ifRange?.let { append(HttpHeaders.IfRange, it) }
                }
            }.execute { response ->
            when (response.status.value) {
                200 -> {
                    response.bodyAsChannel().cancel(null)
                    PdfRangeReadResult.Failure(
                        PdfReaderErrorCode.RangeUnsupported,
                        recoverable = false,
                    )
                }
                416 -> {
                    response.bodyAsChannel().cancel(null)
                    PdfRangeReadResult.Failure(PdfReaderErrorCode.RangeInvalid, recoverable = false)
                }
                206 -> validatePartialResponse(source, range, response)
                else -> {
                    response.bodyAsChannel().cancel(null)
                    PdfRangeReadResult.Failure(PdfReaderErrorCode.NetworkUnavailable, recoverable = true)
                }
            }
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: HttpRequestTimeoutException) {
            PdfRangeReadResult.Failure(PdfReaderErrorCode.NetworkUnavailable, recoverable = true)
        } catch (_: Throwable) {
            PdfRangeReadResult.Failure(PdfReaderErrorCode.NetworkUnavailable, recoverable = true)
        }
    }

    private suspend fun validatePartialResponse(
        source: RemoteByteRangeReaderSource,
        range: PdfByteRange,
        response: io.ktor.client.statement.HttpResponse,
    ): PdfRangeReadResult {
        val expected = revision.value?.takeIf { it.source == source }
        if (expected != null && response.headers[HttpHeaders.ETag] != expected.etag) {
            response.bodyAsChannel().cancel(null)
            return PdfRangeReadResult.Failure(PdfReaderErrorCode.ResourceChanged, false)
        }
        val expectedLength = (range.endExclusive - range.begin).toInt()
        val expectedContentRange = "bytes ${range.begin}-${range.endExclusive - 1}/${source.expectedSizeBytes}"
        if (response.headers[HttpHeaders.ContentRange] != expectedContentRange ||
            response.headers[HttpHeaders.ContentLength]?.toIntOrNull() != expectedLength
        ) {
            response.bodyAsChannel().cancel(null)
            return PdfRangeReadResult.Failure(
                PdfReaderErrorCode.RangeInvalid,
                recoverable = false,
            )
        }
        val channel = response.bodyAsChannel()
        val bytes = ByteArray(expectedLength)
        var offset = 0
        while (offset < bytes.size) {
            val count = channel.readAvailable(bytes, offset, bytes.size - offset)
            if (count < 0) break
            if (count > 0) offset += count
        }
        if (offset != bytes.size || channel.readAvailable(ByteArray(1), 0, 1) >= 0) {
            channel.cancel(null)
            return PdfRangeReadResult.Failure(PdfReaderErrorCode.RangeInvalid, recoverable = false)
        }
        return PdfRangeReadResult.Content(range, bytes)
    }

    private suspend fun <T> withClient(block: suspend (ApiClient) -> T): T {
        val client = createClient(profile)
        return try {
            block(client)
        } finally {
            client.close()
        }
    }
}
