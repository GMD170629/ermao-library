package com.ermao.library.shared.modules.shelf.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.shelf.application.ShelfCatalogRepository
import com.ermao.library.shared.modules.shelf.domain.CreateShelfInput
import com.ermao.library.shared.modules.shelf.domain.ShelfBookPreview
import com.ermao.library.shared.modules.shelf.domain.ShelfCatalogEntry
import com.ermao.library.shared.modules.shelf.domain.ShelfCatalogPage
import com.ermao.library.shared.modules.shelf.domain.ShelfKind
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import io.ktor.http.encodeURLPathPart
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

class KtorShelfCatalogRepository(
    private val clientProvider: (ServerProfile) -> ApiClient,
) : ShelfCatalogRepository {
    constructor(clients: ApiClientFactory) : this(clients::create)
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = true }

    override suspend fun loadCatalog(context: ShelfRequestContext): ShelfResult<List<ShelfCatalogEntry>> =
        when (val result = request(context, ApiRequest(ApiMethod.Get, "/api/shelves", JsonElement.serializer()))) {
            is ApiResult.Failure -> ShelfResult.Failure(result.error.toShelfError())
            is ApiResult.Success -> decode(result.value) { element ->
                json.decodeFromJsonElement(CatalogWire.serializer(), element).shelves.map { it.toEntry() }
                    .also { require(it.distinctBy(ShelfCatalogEntry::id).size == it.size) }
            }
        }

    override suspend fun loadPage(context: ShelfRequestContext, shelfId: String, page: Int): ShelfResult<ShelfCatalogPage> {
        require(shelfId.isNotBlank() && page > 0)
        return when (val result = request(context, ApiRequest(
            ApiMethod.Get, "/api/shelves/${shelfId.encodeURLPathPart()}", JsonElement.serializer(),
            queryParameters = mapOf("page" to listOf(page.toString()), "pageSize" to listOf("24"), "includeBookIds" to listOf("false")),
        ))) {
            is ApiResult.Failure -> ShelfResult.Failure(result.error.toShelfError())
            is ApiResult.Success -> decode(result.value) { element ->
                val wire = json.decodeFromJsonElement(DetailWire.serializer(), element).shelf
                require(wire.id == shelfId && wire.page == page && (wire.totalPages ?: 0) >= page)
                ShelfCatalogPage(wire.toEntry(), wire.shelves.orEmpty().map { it.toEntry() }, page, requireNotNull(wire.totalPages))
            }
        }
    }

    override suspend fun createShelf(context: ShelfRequestContext, input: CreateShelfInput): ShelfResult<String> {
        val body = json.encodeToString(CreateWire(
            input.name.trim(), input.description.trim(),
            if (input.kind == ShelfKind.Collection) "COLLECTION" else "STATIC",
            input.memberShelfIds.takeIf { input.kind == ShelfKind.Collection },
        ))
        return when (val result = request(context, ApiRequest(
            ApiMethod.Post, "/api/shelves", JsonElement.serializer(), requestBody = body,
        ))) {
            is ApiResult.Failure -> ShelfResult.Failure(result.error.toShelfError())
            is ApiResult.Success -> decode(result.value) { element ->
                val shelf = (element as? JsonObject)?.get("shelf") as? JsonObject
                val id = shelf?.get("id") as? JsonPrimitive
                require(id != null && id.isString && id.content.isNotBlank())
                id.content
            }
        }
    }

    private suspend fun <T> request(context: ShelfRequestContext, request: ApiRequest<T>): ApiResult<T> {
        val client = clientProvider(context.profile)
        return try { client.execute(request) } finally { client.close() }
    }

    private fun <T> decode(value: JsonElement, map: (JsonElement) -> T): ShelfResult<T> = try {
        ShelfResult.Content(map(value))
    } catch (_: IllegalArgumentException) {
        protocolFailure("SHELF_CATALOG_INVALID")
    }
}

@Serializable private data class CatalogWire(val shelves: List<ShelfWire>)
@Serializable private data class DetailWire(val shelf: ShelfWire)
@Serializable private data class CreateWire(val name: String, val description: String, val kind: String, val memberShelfIds: List<String>?)
@Serializable private data class BookWire(
    val id: String, val title: String, val author: String? = null, val coverUrl: String, val progress: Double = 0.0,
) {
    fun toPreview(): ShelfBookPreview {
        require(id.isNotBlank() && title.isNotBlank() && progress.isFinite() && progress in 0.0..100.0)
        return ShelfBookPreview(id, title, author, coverUrl, progress)
    }
}
@Serializable private data class ShelfWire(
    val id: String, val name: String, val kind: String,
    val description: String? = null, val bookCount: Int? = null, val shelfCount: Int? = null,
    val books: List<BookWire>? = null, val collectionIds: List<String> = emptyList(),
    val shelves: List<ShelfWire>? = null, val rulesStatus: String = "VALID",
    val page: Int? = null, val totalPages: Int? = null,
) {
    fun toEntry(): ShelfCatalogEntry {
        require(id.isNotBlank() && name.isNotBlank())
        val shelfKind = when (kind) {
            "STATIC" -> ShelfKind.Static
            "SMART" -> ShelfKind.Smart
            "COLLECTION" -> ShelfKind.Collection
            else -> throw IllegalArgumentException("Unknown shelf kind")
        }
        val count = requireNotNull(if (shelfKind == ShelfKind.Collection) shelfCount else bookCount)
        require(count >= 0 && rulesStatus in setOf("VALID", "UNSUPPORTED"))
        val previews = if (shelfKind == ShelfKind.Collection) emptyList() else requireNotNull(books).map { it.toPreview() }
        return ShelfCatalogEntry(id, name, description, shelfKind, count, previews, collectionIds, rulesStatus == "VALID")
    }
}
