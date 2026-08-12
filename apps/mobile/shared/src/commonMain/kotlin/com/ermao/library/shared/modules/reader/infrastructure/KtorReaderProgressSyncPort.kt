package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.reader.application.ReaderProgressPushResult
import com.ermao.library.shared.modules.reader.application.ReaderProgressSyncPort
import com.ermao.library.shared.modules.reader.application.ReaderProgressUpload
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import kotlinx.coroutines.CancellationException

class KtorReaderProgressSyncPort(
    private val clients: ApiClientFactory,
    private val profile: ServerProfile,
    private val mapper: ReaderServerWireMapper = ReaderServerWireMapper(),
) : ReaderProgressSyncPort {
    override suspend fun push(upload: ReaderProgressUpload): ReaderProgressPushResult {
        require(upload.target.namespace.serverIdentity == profile.serverIdentity) {
            "Reader progress upload belongs to another server"
        }
        val client = clients.create(profile)
        return try {
            when (val result = client.execute(
                ApiRequest(
                    method = ApiMethod.Put,
                    apiPath = "/api/reader/v4/volumes/${encodePathSegment(upload.target.volumeId)}/progress",
                    responseDeserializer = mapper.responseSerializer(),
                    requestBody = mapper.encodeProgressUpload(upload),
                ),
            )) {
                is ApiResult.Success -> try {
                    ReaderProgressPushResult.Accepted(
                        mapper.decodeSnapshot(result.value, upload.target.volumeId),
                    )
                } catch (_: IllegalArgumentException) {
                    ReaderProgressPushResult.Discarded("INVALID_PROGRESS_RESPONSE")
                }
                is ApiResult.Failure -> ReaderProgressPushResult.Discarded(result.error.code)
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
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
                else {
                    append('%')
                    append(HEX[unsigned ushr 4])
                    append(HEX[unsigned and 0x0f])
                }
            }
        }
    }

    private companion object {
        const val HEX = "0123456789ABCDEF"
    }
}
