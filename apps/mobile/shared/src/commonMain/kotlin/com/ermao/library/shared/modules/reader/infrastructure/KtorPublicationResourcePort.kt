package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.reader.application.OnlinePublicationReadResult
import com.ermao.library.shared.modules.reader.application.PublicationResourcePort

class KtorPublicationResourcePort internal constructor(private val client: ApiClient) : PublicationResourcePort {
    private var revision: String? = null
    override suspend fun read(apiPath: String, maximumBytes: Int, mediaTypes: Set<String>): OnlinePublicationReadResult {
        val versionHeaders = revision?.let { mapOf("X-Publication-Revision" to it) }.orEmpty()
        return when (val result = client.loadAuthenticatedBinary(
            apiPath, maximumBytes, mediaTypes, versionHeaders, versionHeaders,
            errorCodeStatuses = ReaderHttpErrorStatuses.publication,
        )) {
            is ApiResult.Success -> {
                if (apiPath.endsWith("/manifest.json")) revision = result.metadata.firstHeader("X-Publication-Revision")
                OnlinePublicationReadResult.Content(result.value.bytes)
            }
            is ApiResult.Failure -> OnlinePublicationReadResult.Failure(
                if (result.error.code == "BINARY_VERSION_CHANGED") "PUBLICATION_CHANGED" else result.error.code,
                cause = result.error.cause,
                source = readerFailureSource(result.error.kind),
            )
        }
    }

    override fun close() = client.close()
}

internal fun readerFailureSource(kind: AppErrorKind): String = when (kind) {
    AppErrorKind.NetworkUnavailable, AppErrorKind.Timeout, AppErrorKind.TlsFailure,
    AppErrorKind.Cancelled, AppErrorKind.ProtocolViolation -> "transport"
    AppErrorKind.StorageFailure -> "storage"
    else -> "server"
}
