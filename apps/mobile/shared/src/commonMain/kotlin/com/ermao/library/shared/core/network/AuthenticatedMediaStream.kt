package com.ermao.library.shared.core.network

import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.cancel
import io.ktor.utils.io.readAvailable

internal enum class AuthenticatedStreamMethod {
    Head,
    Get,
}

internal data class AuthenticatedStreamRequest(
    val method: AuthenticatedStreamMethod,
    val apiPath: String,
    val rangeStart: Long? = null,
    val rangeEndInclusive: Long? = null,
    val ifRange: String? = null,
) {
    init {
        require(apiPath.startsWith("/api/"))
        require('#' !in apiPath && '?' !in apiPath)
        require(rangeStart == null || method == AuthenticatedStreamMethod.Get)
        require(rangeStart == null || rangeStart >= 0)
        require(rangeEndInclusive == null || rangeStart != null && rangeEndInclusive >= rangeStart)
        require(ifRange == null || ifRange.isNotBlank())
    }
}

/** Response body remains incremental and is cancelled when the native engine releases it. */
internal class AuthenticatedMediaStream(
    val statusCode: Int,
    val headers: Map<String, List<String>>,
    private val channel: ByteReadChannel,
) {
    private var closed = false

    suspend fun read(maximumBytes: Int): ByteArray {
        require(maximumBytes > 0)
        check(!closed) { "Authenticated media stream is closed" }
        val buffer = ByteArray(maximumBytes)
        while (true) {
            val count = channel.readAvailable(buffer, 0, buffer.size)
            if (count < 0) return byteArrayOf()
            if (count > 0) return if (count == buffer.size) buffer else buffer.copyOf(count)
        }
    }

    fun header(name: String): String? = headers.entries
        .firstOrNull { it.key.equals(name, ignoreCase = true) }
        ?.value
        ?.singleOrNull()

    fun close() {
        if (closed) return
        closed = true
        channel.cancel(null)
    }
}
