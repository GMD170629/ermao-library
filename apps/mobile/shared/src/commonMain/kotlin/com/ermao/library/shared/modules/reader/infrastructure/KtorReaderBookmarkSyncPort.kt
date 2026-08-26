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
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
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
        readerServerWireJson.encodeToString(
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
                    apiPath = "/api/reader/v4/resources/${encodePathSegment(target.resourceId)}/bookmarks",
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
    val location: JsonObject,
    val label: String,
    val percent: Double,
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
    location = location.toWire(),
    label = label,
    percent = percent,
    createdAt = createdAt,
)

private fun ReaderBookmarkWire.toDomain(): ReaderBookmark {
    return ReaderBookmark(
        id = id,
        location = location.toDomain(),
        label = label,
        percent = percent,
        createdAt = createdAt,
    )
}

private fun ReaderBookmarkLocation.toWire(): JsonObject = buildJsonObject {
    put("kind", kind)
    when (kind) {
        "reflow" -> {
            put("resourceKey", resourceKey)
            progression?.let { put("progression", it) }
        }
        "comic" -> put("pageIndex", requireNotNull(pageIndex))
        "pdf" -> put("pageNumber", requireNotNull(pageNumber))
        "audio" -> {
            put("assetId", requireNotNull(assetId))
            chapterId?.let { put("chapterId", it) }
            put("positionMs", requireNotNull(positionMs))
        }
        else -> error("Unsupported Reader bookmark kind")
    }
}

private fun JsonObject.toDomain(): ReaderBookmarkLocation {
    val kind = requiredString("kind")
    return when (kind) {
        "reflow" -> {
            requireOnly("kind", "resourceKey", "progression")
            ReaderBookmarkLocation.reflow(requiredString("resourceKey"), optionalDouble("progression"))
        }
        "comic" -> {
            requireOnly("kind", "pageIndex")
            ReaderBookmarkLocation.comic(requiredInt("pageIndex"))
        }
        "pdf" -> {
            requireOnly("kind", "pageNumber")
            ReaderBookmarkLocation.pdf(requiredInt("pageNumber"))
        }
        "audio" -> {
            requireOnly("kind", "assetId", "chapterId", "positionMs")
            ReaderBookmarkLocation.audio(
                assetId = requiredString("assetId"),
                chapterId = optionalString("chapterId"),
                positionMs = requiredLong("positionMs"),
            )
        }
        else -> throw IllegalArgumentException("Unsupported Reader bookmark kind")
    }
}

private fun JsonObject.requireOnly(vararg allowed: String) {
    require(keys.all(allowed.toSet()::contains)) { "Reader bookmark location contains unsupported fields" }
}

private fun JsonObject.requiredString(name: String): String =
    (this[name] as? JsonPrimitive)?.content?.takeIf(String::isNotBlank)
        ?: throw IllegalArgumentException("Reader bookmark field $name is missing")

private fun JsonObject.optionalString(name: String): String? =
    (this[name] as? JsonPrimitive)?.content?.takeIf(String::isNotBlank)

private fun JsonObject.requiredInt(name: String): Int =
    (this[name] as? JsonPrimitive)?.content?.toIntOrNull()
        ?: throw IllegalArgumentException("Reader bookmark field $name is missing")

private fun JsonObject.requiredLong(name: String): Long =
    (this[name] as? JsonPrimitive)?.longOrNull
        ?: throw IllegalArgumentException("Reader bookmark field $name is missing")

private fun JsonObject.optionalDouble(name: String): Double? =
    (this[name] as? JsonPrimitive)?.doubleOrNull
