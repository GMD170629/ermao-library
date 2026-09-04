package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.reader.application.ReaderPositionPushResult
import com.ermao.library.shared.modules.reader.application.ReaderPositionQueryResult
import com.ermao.library.shared.modules.reader.application.ReaderPositionServerPort
import com.ermao.library.shared.modules.reader.application.ReaderPositionUpload
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import kotlinx.coroutines.CancellationException

/** Reader v5 transport. The request body is never rebuilt during a retry. */
class KtorReaderPositionSyncPort internal constructor(
    private val profile: ServerProfile,
    private val createClient: (ServerProfile) -> com.ermao.library.shared.core.network.ApiClient,
    private val mapper: ReaderV5ServerWireMapper = ReaderV5ServerWireMapper(),
) : ReaderPositionServerPort {
    constructor(
        clients: ApiClientFactory,
        profile: ServerProfile,
        mapper: ReaderV5ServerWireMapper = ReaderV5ServerWireMapper(),
    ) : this(profile, clients::create, mapper)

    override suspend fun push(upload: ReaderPositionUpload): ReaderPositionPushResult {
        require(upload.target.namespace.serverIdentity == profile.serverIdentity) {
            "Reader position upload belongs to another server"
        }
        val client = createClient(profile)
        return try {
            when (val result = client.execute(
                ApiRequest(
                    method = ApiMethod.Put,
                    apiPath = "/api/reader/v5/resources/${encodePathSegment(upload.target.resourceId)}/progress",
                    responseDeserializer = mapper.responseSerializer(),
                    requestBody = mapper.encodeProgressUpload(upload),
                ),
            )) {
                is ApiResult.Success -> runCatching {
                    ReaderPositionPushResult.Accepted(
                        mapper.decodeWriteResponse(
                            result.value.toString(),
                            upload.target.resourceId,
                        ),
                    )
                }.getOrElse { ReaderPositionPushResult.Rejected("INVALID_PROGRESS_RESPONSE") }
                is ApiResult.Failure -> if (result.error.kind in RETRYABLE_KINDS) {
                    ReaderPositionPushResult.RetryableFailure(result.error.code)
                } else {
                    ReaderPositionPushResult.Rejected(result.error.code)
                }
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } finally {
            client.close()
        }
    }

    override suspend fun load(
        target: ReaderProgressSyncTarget,
        etag: String?,
    ): ReaderPositionQueryResult {
        require(target.namespace.serverIdentity == profile.serverIdentity) {
            "Reader position query belongs to another server"
        }
        val client = createClient(profile)
        return try {
            when (val result = client.loadAuthenticatedJson(
                apiPath = "/api/reader/v5/resources/${encodePathSegment(target.resourceId)}/progress",
                etag = etag,
                maximumBytes = MAXIMUM_RESPONSE_BYTES,
            )) {
                is ApiResult.Success -> if (result.value.notModified) {
                    ReaderPositionQueryResult.Unchanged(result.value.etag ?: etag)
                } else {
                    runCatching {
                        ReaderPositionQueryResult.Current(
                            mapper.decodeProgressState(
                                result.value.bytes.decodeToString(),
                                target.resourceId,
                            ),
                            result.value.etag,
                        )
                    }.getOrElse { ReaderPositionQueryResult.Failure("INVALID_PROGRESS_RESPONSE", false) }
                }
                is ApiResult.Failure -> ReaderPositionQueryResult.Failure(
                    result.error.code,
                    result.error.kind in RETRYABLE_KINDS,
                )
            }
        } finally {
            client.close()
        }
    }

    private fun encodePathSegment(value: String): String {
        require(value.isNotBlank())
        return buildString {
            value.encodeToByteArray().forEach { byte ->
                val unsigned = byte.toInt() and 0xff
                val character = unsigned.toChar()
                if (character.isLetterOrDigit() || character in setOf('-', '_', '.', '~')) append(character)
                else append('%').append(HEX[unsigned ushr 4]).append(HEX[unsigned and 0x0f])
            }
        }
    }

    private companion object {
        const val MAXIMUM_RESPONSE_BYTES = 196_608
        const val HEX = "0123456789ABCDEF"
        val RETRYABLE_KINDS = setOf(
            AppErrorKind.NetworkUnavailable,
            AppErrorKind.Timeout,
            AppErrorKind.RateLimited,
            AppErrorKind.ServiceUnavailable,
            AppErrorKind.ServerFailure,
            AppErrorKind.TlsFailure,
            AppErrorKind.Unauthorized,
        )
    }
}
