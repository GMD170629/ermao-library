package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AuthenticatedMediaStream
import com.ermao.library.shared.core.network.AuthenticatedStreamMethod
import com.ermao.library.shared.core.network.AuthenticatedStreamRequest
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
import io.ktor.http.HttpHeaders
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
            when (val opened = client.openAuthenticatedStream(
                AuthenticatedStreamRequest(AuthenticatedStreamMethod.Head, source.apiPath),
            )) {
                is ApiResult.Failure -> PdfRangeProbeResult.Failure(
                    PdfReaderErrorCode.NetworkUnavailable,
                    recoverable = true,
                )
                is ApiResult.Success -> opened.value.useStream { response ->
            val result = when {
                response.statusCode !in 200..299 -> PdfRangeProbeResult.Failure(
                    PdfReaderErrorCode.NetworkUnavailable,
                    recoverable = true,
                )
                response.header(HttpHeaders.AcceptRanges)?.split(',')
                    ?.map(String::trim)?.any { it.equals("bytes", ignoreCase = true) } != true ->
                    probePolicyFailure(PdfReaderErrorCode.RangeUnsupported)
                !acceptsPdfMimeType(response.header(HttpHeaders.ContentType)) ->
                    probePolicyFailure(
                        PdfReaderErrorCode.RangeInvalid,
                        ReaderSafetyRuleId.COMMON_EXACT_FORMAT_MIME,
                    )
                !hasIdentityContentEncoding(response.header(HttpHeaders.ContentEncoding)) ->
                    probePolicyFailure(PdfReaderErrorCode.RangeInvalid)
                response.header(HttpHeaders.ContentLength)?.toLongOrNull() != source.expectedSizeBytes ->
                    probePolicyFailure(PdfReaderErrorCode.ResourceChanged)
                else -> {
                    val etag = response.header(HttpHeaders.ETag)
                    if (etag.isNullOrBlank() || !isStrongEtag(etag)) {
                        revision.value = null
                        probePolicyFailure(PdfReaderErrorCode.RangeInvalid)
                    } else {
                        revision.value = Revision(source, etag)
                        PdfRangeProbeResult.Available
                    }
                }
            }
            result
                }
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
            when (val opened = client.openAuthenticatedStream(
                AuthenticatedStreamRequest(
                    method = AuthenticatedStreamMethod.Get,
                    apiPath = source.apiPath,
                    rangeStart = range.begin,
                    rangeEndInclusive = range.endExclusive - 1,
                    ifRange = expectedRevision.etag,
                ),
            )) {
                is ApiResult.Failure -> PdfRangeReadResult.Failure(
                    PdfReaderErrorCode.NetworkUnavailable,
                    recoverable = true,
                )
                is ApiResult.Success -> opened.value.useStream { response -> when (response.statusCode) {
                200 -> {
                    readPolicyFailure(PdfReaderErrorCode.RangeUnsupported)
                }
                416 -> {
                    readPolicyFailure(PdfReaderErrorCode.RangeInvalid)
                }
                206 -> validatePartialResponse(source, range, response)
                else -> {
                    PdfRangeReadResult.Failure(PdfReaderErrorCode.NetworkUnavailable, recoverable = true)
                }
                } }
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
        response: AuthenticatedMediaStream,
    ): PdfRangeReadResult {
        val expected = revision.value?.takeIf { it.source == source }
        val responseEtag = response.header(HttpHeaders.ETag)
        if (expected == null || responseEtag.isNullOrBlank() || !isStrongEtag(responseEtag)) {
            return readPolicyFailure(PdfReaderErrorCode.RangeInvalid)
        }
        if (responseEtag != expected.etag) {
            return readPolicyFailure(PdfReaderErrorCode.ResourceChanged)
        }
        val expectedLength = (range.endExclusive - range.begin).toInt()
        val expectedContentRange = "bytes ${range.begin}-${range.endExclusive - 1}/${source.expectedSizeBytes}"
        if (!acceptsPdfMimeType(response.header(HttpHeaders.ContentType))) {
            return readPolicyFailure(
                PdfReaderErrorCode.RangeInvalid,
                ReaderSafetyRuleId.COMMON_EXACT_FORMAT_MIME,
            )
        }
        if (!hasIdentityContentEncoding(response.header(HttpHeaders.ContentEncoding)) ||
            response.header(HttpHeaders.ContentRange) != expectedContentRange ||
            response.header(HttpHeaders.ContentLength)?.toIntOrNull() != expectedLength
        ) {
            return readPolicyFailure(PdfReaderErrorCode.RangeInvalid)
        }
        val bytes = ByteArray(expectedLength)
        var offset = 0
        while (offset < bytes.size) {
            val chunk = response.read(bytes.size - offset)
            if (chunk.isEmpty()) break
            chunk.copyInto(bytes, destinationOffset = offset)
            offset += chunk.size
        }
        if (offset != bytes.size || response.read(1).isNotEmpty()) {
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

private suspend inline fun <T> AuthenticatedMediaStream.useStream(
    crossinline block: suspend (AuthenticatedMediaStream) -> T,
): T =
    try {
        block(this)
    } finally {
        close()
    }
