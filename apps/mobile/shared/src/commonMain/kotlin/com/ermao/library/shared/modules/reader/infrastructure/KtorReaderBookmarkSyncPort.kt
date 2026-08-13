package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncResponse
import com.ermao.library.shared.modules.reader.domain.ReaderBookmark
import com.ermao.library.shared.modules.reader.domain.ReaderBookmarkLocation
import com.ermao.library.shared.modules.reader.domain.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString

class KtorReaderBookmarkSyncPort(
    private val clients: ApiClientFactory,
    private val profile: ServerProfile,
) : ReaderBookmarkSyncPort {
    override suspend fun load(target: ReaderBookmarkSyncTarget): ReaderBookmarkSyncResponse =
        execute(target, ApiMethod.Get, null)

    override suspend fun replace(
        target: ReaderBookmarkSyncTarget,
        bookmarks: List<ReaderBookmark>,
    ): ReaderBookmarkSyncResponse = execute(
        target,
        ApiMethod.Put,
        readerServerWireJson.encodeToString(
            ReaderBookmarksReplaceWire(
                contentFingerprint = target.contentFingerprint,
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
        val client = clients.create(profile)
        return try {
            when (val result = client.execute(
                ApiRequest(
                    method = method,
                    apiPath = "/api/reader/v4/volumes/${encodePathSegment(target.volumeId)}/bookmarks",
                    queryParameters = if (method == ApiMethod.Get) {
                        mapOf("contentFingerprint" to listOf(target.contentFingerprint))
                    } else {
                        emptyMap()
                    },
                    responseDeserializer = ReaderBookmarksDataWire.serializer(),
                    requestBody = requestBody,
                ),
            )) {
                is ApiResult.Success -> ReaderBookmarkSyncResponse(
                    succeeded = true,
                    bookmarks = result.value.bookmarks.map(ReaderBookmarkWire::toDomain),
                )
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
private data class ReaderBookmarkLocationWire(
    val kind: String = "reflow",
    val resourceKey: String,
    val progression: Double? = null,
)

@Serializable
private data class ReaderBookmarkWire(
    val id: String,
    val location: ReaderBookmarkLocationWire,
    val label: String,
    val percent: Double,
    val createdAt: String,
)

@Serializable
private data class ReaderBookmarksDataWire(val bookmarks: List<ReaderBookmarkWire>)

@Serializable
private data class ReaderBookmarksReplaceWire(
    val contentFingerprint: String,
    val bookmarks: List<ReaderBookmarkWire>,
)

private fun ReaderBookmark.toWire() = ReaderBookmarkWire(
    id = id,
    location = ReaderBookmarkLocationWire(
        resourceKey = location.resourceKey,
        progression = location.progression,
    ),
    label = label,
    percent = percent,
    createdAt = createdAt,
)

private fun ReaderBookmarkWire.toDomain(): ReaderBookmark {
    require(location.kind == "reflow")
    return ReaderBookmark(
        id = id,
        location = ReaderBookmarkLocation(location.resourceKey, location.progression),
        label = label,
        percent = percent,
        createdAt = createdAt,
    )
}
