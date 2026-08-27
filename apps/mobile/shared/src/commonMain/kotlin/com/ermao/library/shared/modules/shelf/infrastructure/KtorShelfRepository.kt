package com.ermao.library.shared.modules.shelf.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.shelf.application.ShelfRepository
import com.ermao.library.shared.modules.shelf.domain.ShelfError
import com.ermao.library.shared.modules.shelf.domain.ShelfErrorKind
import com.ermao.library.shared.modules.shelf.domain.ShelfKind
import com.ermao.library.shared.modules.shelf.domain.ShelfMembership
import com.ermao.library.shared.modules.shelf.domain.ShelfMembershipChange
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import com.ermao.library.shared.modules.shelf.domain.ShelfSummary
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

class KtorShelfRepository(
    private val clientProvider: (com.ermao.library.shared.modules.servers.domain.ServerProfile) -> ApiClient,
) : ShelfRepository {
    constructor(clients: ApiClientFactory) : this(clients::create)
    private val encoder = Json { explicitNulls = false; encodeDefaults = true }

    override suspend fun loadShelves(
        context: ShelfRequestContext,
        bookId: String,
    ): ShelfResult<List<ShelfSummary>> = coroutineScope {
        when (val result = request(context) { client ->
            client.execute(ApiRequest(ApiMethod.Get, "/api/shelves", JsonElement.serializer()))
        }) {
            is ApiResult.Failure -> ShelfResult.Failure(result.error.toShelfError())
            is ApiResult.Success -> {
                val shelves = (result.value as? JsonObject)?.get("shelves") as? JsonArray
                    ?: return@coroutineScope protocolFailure("SHELVES_MISSING")
                val listedShelves = shelves.mapNotNull { element ->
                    val value = element as? JsonObject ?: return@mapNotNull null
                    val kind = value.string("kind")?.toShelfKind() ?: return@mapNotNull null
                    val id = value.string("id") ?: return@mapNotNull null
                    val name = value.string("name") ?: return@mapNotNull null
                    Triple(id, name, kind)
                }
                val details = listedShelves.map { (id, name, kind) ->
                    async {
                        // Collections own shelves and have no bookIds field.
                        if (kind == ShelfKind.Collection) {
                            return@async ShelfResult.Content(ShelfSummary(id, name, kind, false))
                        }
                        when (val detail = request(context) { client ->
                            client.execute(
                                ApiRequest(
                                    ApiMethod.Get,
                                    "/api/shelves/$id",
                                    JsonElement.serializer(),
                                    queryParameters = mapOf(
                                        "includeBookIds" to listOf("true"),
                                        "pageSize" to listOf("1"),
                                    ),
                                ),
                            )
                        }) {
                            is ApiResult.Failure -> ShelfResult.Failure(detail.error.toShelfError())
                            is ApiResult.Success -> {
                                val shelf = (detail.value as? JsonObject)?.get("shelf") as? JsonObject
                                    ?: return@async protocolFailure("SHELF_MISSING")
                                val ids = shelf["bookIds"] as? JsonArray
                                    ?: return@async protocolFailure("SHELF_BOOK_IDS_MISSING")
                                ShelfResult.Content(
                                    ShelfSummary(
                                        id = id,
                                        name = name,
                                        kind = kind,
                                        containsBook = ids.any { (it as? JsonPrimitive)?.contentOrNull == bookId },
                                    ),
                                )
                            }
                        }
                    }
                }.awaitAll()
                val failure = details.filterIsInstance<ShelfResult.Failure>().firstOrNull()
                failure ?: ShelfResult.Content(
                    details.filterIsInstance<ShelfResult.Content<ShelfSummary>>().map { it.value },
                )
            }
        }
    }

    override suspend fun updateMembership(
        context: ShelfRequestContext,
        change: ShelfMembershipChange,
    ): ShelfResult<Unit> {
        val body = encoder.encodeToString(
            BulkShelfMembershipWire(
                ids = listOf(change.bookId),
                shelfId = change.shelfId,
                membership = change.membership.name.uppercase(),
            ),
        )
        return when (val result = request(context) { client ->
            client.execute(
                ApiRequest(
                    ApiMethod.Post,
                    "/api/library/operations/books/shelf-membership",
                    JsonElement.serializer(),
                    requestBody = body,
                ),
            )
        }) {
            is ApiResult.Failure -> ShelfResult.Failure(result.error.toShelfError())
            is ApiResult.Success -> {
                val updated = (result.value as? JsonObject)?.get("updated") as? JsonPrimitive
                if (updated?.contentOrNull?.toIntOrNull() == null) protocolFailure("SHELF_UPDATE_INVALID")
                else ShelfResult.Content(Unit)
            }
        }
    }

    private suspend fun <T> request(
        context: ShelfRequestContext,
        block: suspend (ApiClient) -> ApiResult<T>,
    ): ApiResult<T> {
        val client = clientProvider(context.profile)
        return try {
            block(client)
        } finally {
            client.close()
        }
    }
}

@kotlinx.serialization.Serializable
private data class BulkShelfMembershipWire(
    val ids: List<String>,
    val shelfId: String,
    val membership: String,
)

private fun JsonObject.string(name: String): String? =
    (this[name] as? JsonPrimitive)?.contentOrNull

private fun String.toShelfKind(): ShelfKind? = when (this) {
    "STATIC" -> ShelfKind.Static
    "SMART" -> ShelfKind.Smart
    "COLLECTION" -> ShelfKind.Collection
    else -> null
}

internal fun AppError.toShelfError(): ShelfError = ShelfError(
    kind = when (kind) {
        AppErrorKind.Unauthorized -> ShelfErrorKind.Unauthorized
        AppErrorKind.NetworkUnavailable, AppErrorKind.Timeout, AppErrorKind.TlsFailure -> ShelfErrorKind.Offline
        AppErrorKind.Forbidden, AppErrorKind.NotFoundOrUnavailable -> ShelfErrorKind.Inaccessible
        AppErrorKind.InvalidRequest, AppErrorKind.Validation, AppErrorKind.Conflict -> ShelfErrorKind.InvalidRequest
        AppErrorKind.ServerFailure, AppErrorKind.ServiceUnavailable, AppErrorKind.RateLimited -> ShelfErrorKind.Server
        else -> ShelfErrorKind.Protocol
    },
    code = code,
)

internal fun <T> protocolFailure(code: String): ShelfResult<T> =
    ShelfResult.Failure(ShelfError(ShelfErrorKind.Protocol, code))
