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
import io.ktor.client.request.head
import io.ktor.client.request.headers
import io.ktor.client.request.request
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.utils.io.readAvailable
import kotlinx.coroutines.CancellationException

class KtorPdfRangeServerPort internal constructor(
    private val profile: ServerProfile,
    private val createClient: (ServerProfile) -> ApiClient,
) : PdfRangeServerPort {
    constructor(profile: ServerProfile, clients: ApiClientFactory) : this(profile, clients::create)

    override suspend fun probe(source: RemoteByteRangeReaderSource): PdfRangeProbeResult = withClient { client ->
        try {
            val response = client.authenticatedHttpClient().head(client.resolveAuthenticatedApiPath(source.apiPath))
            when {
                response.status.value !in 200..299 -> PdfRangeProbeResult.Failure(
                    PdfReaderErrorCode.NetworkUnavailable,
                    recoverable = true,
                )
                response.headers[HttpHeaders.AcceptRanges]?.split(',')
                    ?.map(String::trim)?.any { it.equals("bytes", ignoreCase = true) } != true ->
                    PdfRangeProbeResult.Failure(PdfReaderErrorCode.RangeUnsupported, recoverable = false)
                response.headers[HttpHeaders.ContentLength]?.toLongOrNull() != source.expectedSizeBytes ->
                    PdfRangeProbeResult.Failure(PdfReaderErrorCode.ResourceChanged, recoverable = false)
                else -> PdfRangeProbeResult.Available
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
            val response = client.authenticatedHttpClient().request(client.resolveAuthenticatedApiPath(source.apiPath)) {
                method = HttpMethod.Get
                headers {
                    append(HttpHeaders.Range, "bytes=${range.begin}-${range.endExclusive - 1}")
                }
            }
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
