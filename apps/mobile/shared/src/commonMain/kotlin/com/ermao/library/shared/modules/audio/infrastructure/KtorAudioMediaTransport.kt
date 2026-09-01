package com.ermao.library.shared.modules.audio.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.core.network.AuthenticatedMediaStream
import com.ermao.library.shared.core.network.AuthenticatedStreamMethod
import com.ermao.library.shared.core.network.AuthenticatedStreamRequest
import com.ermao.library.shared.modules.audio.application.AudioMediaFailure
import com.ermao.library.shared.modules.audio.application.AudioMediaMetadata
import com.ermao.library.shared.modules.audio.application.AudioMediaOpenResult
import com.ermao.library.shared.modules.audio.application.AudioMediaProbeResult
import com.ermao.library.shared.modules.audio.application.AudioMediaStream
import com.ermao.library.shared.modules.audio.application.AudioMediaTransport
import com.ermao.library.shared.modules.audio.domain.AudioAsset
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import io.ktor.http.HttpHeaders

class KtorAudioMediaTransport internal constructor(
    private val profile: ServerProfile,
    private val createClient: (ServerProfile) -> ApiClient,
) : AudioMediaTransport {
    constructor(profile: ServerProfile, clients: ApiClientFactory) : this(profile, clients::create)

    override suspend fun probe(asset: AudioAsset): AudioMediaProbeResult {
        val client = createClient(profile)
        return try {
            when (val opened = client.openAuthenticatedStream(
                AuthenticatedStreamRequest(AuthenticatedStreamMethod.Head, asset.apiPath),
            )) {
                is ApiResult.Failure -> AudioMediaProbeResult.Failure(opened.error.toAudioFailure())
                is ApiResult.Success -> opened.value.useStream { stream ->
                    stream.validate(asset, rangeStart = null)?.let(AudioMediaProbeResult::Failure)
                        ?: AudioMediaProbeResult.Available(stream.metadata(asset))
                }
            }
        } finally {
            client.close()
        }
    }

    override suspend fun open(
        asset: AudioAsset,
        rangeStart: Long,
        rangeEndInclusive: Long?,
    ): AudioMediaOpenResult {
        require(rangeStart >= 0 && rangeStart < asset.sizeBytes)
        require(rangeEndInclusive == null || rangeEndInclusive in rangeStart until asset.sizeBytes)
        val client = createClient(profile)
        val opened = client.openAuthenticatedStream(
            AuthenticatedStreamRequest(
                method = AuthenticatedStreamMethod.Get,
                apiPath = asset.apiPath,
                rangeStart = rangeStart,
                rangeEndInclusive = rangeEndInclusive,
            ),
        )
        return when (opened) {
            is ApiResult.Failure -> {
                client.close()
                AudioMediaOpenResult.Failure(opened.error.toAudioFailure())
            }
            is ApiResult.Success -> {
                val validation = opened.value.validate(asset, rangeStart)
                if (validation != null) {
                    opened.value.close()
                    client.close()
                    AudioMediaOpenResult.Failure(validation)
                } else {
                    AudioMediaOpenResult.Content(
                        KtorAudioMediaStream(opened.value.metadata(asset), opened.value, client),
                    )
                }
            }
        }
    }
}

private class KtorAudioMediaStream(
    override val metadata: AudioMediaMetadata,
    private val delegate: AuthenticatedMediaStream,
    private val client: ApiClient,
) : AudioMediaStream {
    private var closed = false

    override suspend fun read(maximumBytes: Int): ByteArray {
        check(!closed)
        return delegate.read(maximumBytes)
    }

    override fun close() {
        if (closed) return
        closed = true
        delegate.close()
        client.close()
    }
}

private suspend inline fun <T> AuthenticatedMediaStream.useStream(
    crossinline block: suspend (AuthenticatedMediaStream) -> T,
): T =
    try {
        block(this)
    } finally {
        close()
    }

private fun AuthenticatedMediaStream.validate(asset: AudioAsset, rangeStart: Long?): AudioMediaFailure? {
    if (statusCode == 401) return AudioMediaFailure("UNAUTHORIZED", true, requiresReauthentication = true)
    if (statusCode == 403 || statusCode == 404) return AudioMediaFailure("AUDIO_ACCESS_REVOKED", false)
    val expectedStatus = if (rangeStart == null) 200..299 else 206..206
    if (statusCode !in expectedStatus) return AudioMediaFailure("AUDIO_NETWORK_UNAVAILABLE", true)
    val mimeType = normalizedHeader(HttpHeaders.ContentType)
        ?: return AudioMediaFailure("AUDIO_MIME_MISMATCH", false)
    if (mimeType != asset.mimeType) return AudioMediaFailure("AUDIO_MIME_MISMATCH", false)
    val encoding = header(HttpHeaders.ContentEncoding)
    if (!encoding.isNullOrBlank() && !encoding.equals("identity", ignoreCase = true)) {
        return AudioMediaFailure("AUDIO_SECURITY_REJECTED", false)
    }
    val declaredLength = header(HttpHeaders.ContentLength)?.toLongOrNull()
    if (header(HttpHeaders.ContentLength) != null && declaredLength == null) {
        return AudioMediaFailure("AUDIO_SECURITY_REJECTED", false)
    }
    if (rangeStart == null && declaredLength != null && declaredLength != asset.sizeBytes) {
        return AudioMediaFailure("AUDIO_RESOURCE_CHANGED", false)
    }
    if (rangeStart != null) {
        val contentRange = parseContentRange(header(HttpHeaders.ContentRange))
            ?: return AudioMediaFailure("AUDIO_SECURITY_REJECTED", false)
        if (contentRange.first != rangeStart || contentRange.third != asset.sizeBytes) {
            return AudioMediaFailure("AUDIO_RESOURCE_CHANGED", false)
        }
    }
    return null
}

private fun AuthenticatedMediaStream.metadata(asset: AudioAsset): AudioMediaMetadata {
    val range = parseContentRange(header(HttpHeaders.ContentRange))
    return AudioMediaMetadata(
        mimeType = requireNotNull(normalizedHeader(HttpHeaders.ContentType)),
        contentLength = header(HttpHeaders.ContentLength)?.toLongOrNull(),
        totalLength = range?.third ?: asset.sizeBytes,
        acceptsByteRanges = header(HttpHeaders.AcceptRanges)?.split(',')?.any {
            it.trim().equals("bytes", ignoreCase = true)
        } == true || range != null,
        etag = header(HttpHeaders.ETag),
    )
}

private fun AuthenticatedMediaStream.normalizedHeader(name: String): String? =
    header(name)?.trim()?.lowercase()?.substringBefore(';')

private data class ContentRange(val first: Long, val last: Long, val third: Long)

private fun parseContentRange(value: String?): ContentRange? {
    val match = CONTENT_RANGE.matchEntire(value?.trim().orEmpty()) ?: return null
    val first = match.groupValues[1].toLongOrNull() ?: return null
    val last = match.groupValues[2].toLongOrNull() ?: return null
    val total = match.groupValues[3].toLongOrNull() ?: return null
    return ContentRange(first, last, total).takeIf { first <= last && last < total }
}

private fun com.ermao.library.shared.core.network.AppError.toAudioFailure(): AudioMediaFailure = when (kind) {
    AppErrorKind.Unauthorized -> AudioMediaFailure(code, true, requiresReauthentication = true)
    AppErrorKind.Forbidden, AppErrorKind.NotFoundOrUnavailable, AppErrorKind.Gone ->
        AudioMediaFailure("AUDIO_ACCESS_REVOKED", false)
    AppErrorKind.ProtocolViolation, AppErrorKind.Validation -> AudioMediaFailure("AUDIO_SECURITY_REJECTED", false)
    else -> AudioMediaFailure(code, true)
}

private val CONTENT_RANGE = Regex("^bytes ([0-9]+)-([0-9]+)/([0-9]+)$")
