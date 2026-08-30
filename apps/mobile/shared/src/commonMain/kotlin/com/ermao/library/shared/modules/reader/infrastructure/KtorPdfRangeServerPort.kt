package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.reader.application.PdfRangeProbeResult
import com.ermao.library.shared.modules.reader.application.PdfRangeReadResult
import com.ermao.library.shared.modules.reader.application.PdfRangeServerPort
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFormat
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
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
    private data class Revision(val source: RemoteByteRangeReaderSource, val etag: String)
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
                    probePolicyFailure(PdfReaderErrorCode.RangeUnsupported)
                !acceptsPdfMimeType(response.headers[HttpHeaders.ContentType]) ->
                    probePolicyFailure(
                        PdfReaderErrorCode.RangeInvalid,
                        ReaderSafetyRuleId.COMMON_EXACT_FORMAT_MIME,
                    )
                !hasIdentityContentEncoding(response.headers[HttpHeaders.ContentEncoding]) ->
                    probePolicyFailure(PdfReaderErrorCode.RangeInvalid)
                response.headers[HttpHeaders.ContentLength]?.toLongOrNull() != source.expectedSizeBytes ->
                    probePolicyFailure(PdfReaderErrorCode.ResourceChanged)
                else -> {
                    val etag = response.headers[HttpHeaders.ETag]
                    if (etag.isNullOrBlank() || !isStrongEtag(etag)) {
                        revision.value = null
                        probePolicyFailure(PdfReaderErrorCode.RangeInvalid)
                    } else {
                        revision.value = Revision(source, etag)
                        PdfRangeProbeResult.Available
                    }
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
        val expectedRevision = revision.value?.takeIf { it.source == source }
        if (expectedRevision == null || !isStrongEtag(expectedRevision.etag)) {
            return@withClient readPolicyFailure(PdfReaderErrorCode.RangeInvalid)
        }
        try {
            require(range.endExclusive <= source.expectedSizeBytes)
            require(range.endExclusive - range.begin <= rangeRequestMaxBytes())
            client.authenticatedHttpClient().prepareGet(client.resolveAuthenticatedApiPath(source.apiPath)) {
                headers {
                    append(HttpHeaders.Range, "bytes=${range.begin}-${range.endExclusive - 1}")
                    append(HttpHeaders.IfRange, expectedRevision.etag)
                }
            }.execute { response ->
            when (response.status.value) {
                200 -> {
                    response.bodyAsChannel().cancel(null)
                    readPolicyFailure(PdfReaderErrorCode.RangeUnsupported)
                }
                416 -> {
                    response.bodyAsChannel().cancel(null)
                    readPolicyFailure(PdfReaderErrorCode.RangeInvalid)
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
        val responseEtag = response.headers[HttpHeaders.ETag]
        if (expected == null || responseEtag.isNullOrBlank() || !isStrongEtag(responseEtag)) {
            response.bodyAsChannel().cancel(null)
            return readPolicyFailure(PdfReaderErrorCode.RangeInvalid)
        }
        if (responseEtag != expected.etag) {
            response.bodyAsChannel().cancel(null)
            return readPolicyFailure(PdfReaderErrorCode.ResourceChanged)
        }
        val expectedLength = (range.endExclusive - range.begin).toInt()
        val expectedContentRange = "bytes ${range.begin}-${range.endExclusive - 1}/${source.expectedSizeBytes}"
        if (!acceptsPdfMimeType(response.headers[HttpHeaders.ContentType])) {
            response.bodyAsChannel().cancel(null)
            return readPolicyFailure(
                PdfReaderErrorCode.RangeInvalid,
                ReaderSafetyRuleId.COMMON_EXACT_FORMAT_MIME,
            )
        }
        if (!hasIdentityContentEncoding(response.headers[HttpHeaders.ContentEncoding]) ||
            response.headers[HttpHeaders.ContentRange] != expectedContentRange ||
            response.headers[HttpHeaders.ContentLength]?.toIntOrNull() != expectedLength
        ) {
            response.bodyAsChannel().cancel(null)
            return readPolicyFailure(PdfReaderErrorCode.RangeInvalid)
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
            return readPolicyFailure(PdfReaderErrorCode.RangeInvalid)
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

    private fun rangeRequestMaxBytes(): Long =
        ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_RANGE_REQUEST_MAX_BYTES)

    private fun probePolicyFailure(
        code: PdfReaderErrorCode,
        ruleId: ReaderSafetyRuleId = ReaderSafetyRuleId.PDF_RANGE_PROTOCOL,
    ): PdfRangeProbeResult.Failure = PdfRangeProbeResult.Failure(
        code = code,
        recoverable = false,
        safetyFailure = ReaderSafetyFacade().failureFor(ruleId),
    )

    private fun readPolicyFailure(
        code: PdfReaderErrorCode,
        ruleId: ReaderSafetyRuleId = ReaderSafetyRuleId.PDF_RANGE_PROTOCOL,
    ): PdfRangeReadResult.Failure = PdfRangeReadResult.Failure(
        code = code,
        recoverable = false,
        safetyFailure = ReaderSafetyFacade().failureFor(ruleId),
    )

    private fun acceptsPdfMimeType(value: String?): Boolean {
        val normalized = value?.trim()?.lowercase()?.substringBefore(';') ?: return false
        return normalized in ReaderSafetyPolicy.formats.getValue(ReaderSafetyFormat.PDF).acceptedMimeTypes
    }

    private fun hasIdentityContentEncoding(value: String?): Boolean =
        value.isNullOrBlank() || value.trim().equals("identity", ignoreCase = true)

    private fun isStrongEtag(etag: String): Boolean =
        etag.isNotBlank() && !etag.trimStart().startsWith("W/", ignoreCase = true)
}
