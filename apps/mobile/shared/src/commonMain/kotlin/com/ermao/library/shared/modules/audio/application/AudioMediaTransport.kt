package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.audio.domain.AudioAsset

data class AudioMediaMetadata(
    val mimeType: String,
    val contentLength: Long?,
    val totalLength: Long?,
    val acceptsByteRanges: Boolean,
    val etag: String?,
) {
    init {
        require(mimeType.isNotBlank())
        require(contentLength == null || contentLength >= 0)
        require(totalLength == null || totalLength > 0)
        require(etag == null || etag.isNotBlank())
    }
}

data class AudioMediaFailure(
    val code: String,
    val recoverable: Boolean,
    val requiresReauthentication: Boolean = false,
) {
    init {
        require(code.isNotBlank())
        require(!requiresReauthentication || recoverable)
    }
}

sealed interface AudioMediaProbeResult {
    data class Available(val metadata: AudioMediaMetadata) : AudioMediaProbeResult
    data class Failure(val error: AudioMediaFailure) : AudioMediaProbeResult
}

interface AudioMediaStream {
    val metadata: AudioMediaMetadata
    suspend fun read(maximumBytes: Int): ByteArray
    fun close()
}

sealed interface AudioMediaOpenResult {
    data class Content(val stream: AudioMediaStream) : AudioMediaOpenResult
    data class Failure(val error: AudioMediaFailure) : AudioMediaOpenResult
}

/** Platform engines consume this port and never receive Cookie, TLS or raw HTTP clients. */
interface AudioMediaTransport {
    suspend fun probe(asset: AudioAsset): AudioMediaProbeResult

    /** Opens an incremental response. A null end keeps the response streaming until engine release. */
    suspend fun open(
        asset: AudioAsset,
        rangeStart: Long = 0,
        rangeEndInclusive: Long? = null,
    ): AudioMediaOpenResult
}
