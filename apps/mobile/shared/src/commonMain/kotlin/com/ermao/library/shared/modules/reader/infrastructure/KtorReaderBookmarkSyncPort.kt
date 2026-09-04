package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncResponse
import com.ermao.library.shared.modules.reader.domain.ReaderBookmark
import com.ermao.library.shared.modules.reader.domain.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class KtorReaderBookmarkSyncPort internal constructor(
    private val profile: ServerProfile,
    private val createClient: (ServerProfile) -> com.ermao.library.shared.core.network.ApiClient,
) : ReaderBookmarkSyncPort {
    constructor(clients: ApiClientFactory, profile: ServerProfile) : this(profile, clients::create)

    override suspend fun load(target: ReaderBookmarkSyncTarget): ReaderBookmarkSyncResponse =
        execute(target, ApiMethod.Get, null)

    override suspend fun replace(
        target: ReaderBookmarkSyncTarget,
        bookmarks: List<ReaderBookmark>,
    ): ReaderBookmarkSyncResponse = execute(
        target,
        ApiMethod.Put,
        readerV5ServerWireJson.encodeToString(
            ReaderBookmarksReplaceWire(
                bookmarks = bookmarks.map(ReaderBookmark::toWire),
            ),
        ),
    )

    private suspend fun execute(
        target: ReaderBookmarkSyncTarget,
        method: ApiMethod,
        requestBody: String?,
    ): ReaderBookmarkSyncResponse {
        require(target.serverIdentity == profile.serverIdentity) {
            "Reader bookmark operation belongs to another server"
        }
        val client = createClient(profile)
        return try {
            when (val result = client.execute(
                ApiRequest(
                    method = method,
                    apiPath = "/api/reader/v5/resources/${encodePathSegment(target.resourceId)}/bookmarks",
                    queryParameters = emptyMap(),
                    responseDeserializer = ReaderBookmarksDataWire.serializer(),
                    requestBody = requestBody,
                ),
            )) {
                is ApiResult.Success -> runCatching {
                    ReaderBookmarkSyncResponse(
                        succeeded = true,
                        bookmarks = result.value.bookmarks.map(ReaderBookmarkWire::toDomain),
                    )
                }.getOrElse {
                    ReaderBookmarkSyncResponse(
                        succeeded = false,
                        failureCode = "INVALID_BOOKMARK_RESPONSE",
                    )
                }
                is ApiResult.Failure -> ReaderBookmarkSyncResponse(
                    succeeded = false,
                    failureCode = result.error.code,
                )
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } finally {
            client.close()
        }
    }

    private fun encodePathSegment(value: String): String = buildString {
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

    private companion object {
        const val HEX = "0123456789ABCDEF"
    }
}

@Serializable
private data class ReaderBookmarkWire(
    val id: String,
    val position: JsonObject,
    val label: String,
    val createdAt: String,
)

@Serializable
private data class ReaderBookmarksDataWire(val bookmarks: List<ReaderBookmarkWire>)

@Serializable
private data class ReaderBookmarksReplaceWire(
    val bookmarks: List<ReaderBookmarkWire>,
)

private fun ReaderBookmark.toWire() = ReaderBookmarkWire(
    id = id,
    position = reportJson.encode(position).let { readerV5ServerWireJson.parseToJsonElement(it) as JsonObject },
    label = label,
    createdAt = createdAt,
)

private fun ReaderBookmarkWire.toDomain(): ReaderBookmark {
    return ReaderBookmark(
        id = id,
        position = reportJson.decode(position.toString()),
        label = label,
        createdAt = createdAt,
    )
}

private val reportJson = ReaderPositionReportJson()
