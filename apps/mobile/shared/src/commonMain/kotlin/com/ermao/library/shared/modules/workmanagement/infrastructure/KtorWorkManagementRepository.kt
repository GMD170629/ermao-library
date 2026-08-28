package com.ermao.library.shared.modules.workmanagement.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiMultipartFile
import com.ermao.library.shared.core.network.ApiMultipartRequest
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.BookDeletionOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.CoverMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
import com.ermao.library.shared.modules.workmanagement.domain.ResourceMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementError
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import io.ktor.http.encodeURLPathPart
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import com.ermao.library.shared.modules.workmanagement.domain.ManagementTarget
import com.ermao.library.shared.modules.workmanagement.domain.ManagementObject
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSnapshot
import com.ermao.library.shared.modules.workmanagement.domain.ManagementField
import com.ermao.library.shared.modules.workmanagement.domain.ManagementFieldValue
import com.ermao.library.shared.modules.workmanagement.domain.ManagedBook
import com.ermao.library.shared.modules.workmanagement.domain.ManagedResource
import com.ermao.library.shared.modules.workmanagement.domain.ManagedAsset
import com.ermao.library.shared.modules.workmanagement.domain.ManagedDirectory
import com.ermao.library.shared.modules.workmanagement.domain.RecognizedField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataApplyOutcome

class KtorWorkManagementRepository(
    private val clientProvider: (com.ermao.library.shared.modules.servers.domain.ServerProfile) -> ApiClient,
) : WorkManagementRepository {
    constructor(clients: ApiClientFactory) : this(clients::create)

    private val encoder = Json { explicitNulls = false; encodeDefaults = true }
    private val nullableEncoder = Json { explicitNulls = true; encodeDefaults = true }

    override suspend fun loadBookCompleted(context: BookManagementContext, bookId: String): WorkManagementResult<Boolean> =
        call(context, ApiMethod.Get, bookPath(bookId)) { payload ->
            val book = payload.objectValue("book") ?: return@call protocolFailure("BOOK_MISSING")
            if (book.string("id") != bookId) return@call protocolFailure("BOOK_IDENTITY_MISMATCH")
            val completed = book.boolean("completed") ?: return@call protocolFailure("BOOK_READING_STATUS_MISSING")
            WorkManagementResult.Content(completed)
        }

    override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> {
        val bookResult = call(context, ApiMethod.Get, bookPath(target.bookId)) { payload ->
            val book = payload.objectValue("book") ?: return@call protocolFailure("BOOK_MISSING")
            val id = book.string("id") ?: return@call protocolFailure("BOOK_ID_MISSING")
            val source = book.string("sourceNodeId") ?: return@call protocolFailure("SOURCE_NODE_MISSING")
            if (id != target.bookId) return@call protocolFailure("BOOK_IDENTITY_MISMATCH")
            WorkManagementResult.Content(ManagedBook(id, source, book.string("title").orEmpty(),
                book.string("author").orEmpty(), book.string("description").orEmpty(),
                book.string("seriesName").orEmpty(), (book["seriesIndex"] as? JsonPrimitive)?.doubleOrNull,
                book.array("tags").orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
                book.string("coverUrl").orEmpty(), book.boolean("completed") == true))
        }
        if (bookResult is WorkManagementResult.Failure) return bookResult
        val book = (bookResult as WorkManagementResult.Content).value
        val resources = mutableListOf<ManagedResource>()
        var page = 1
        do {
            val result = call(context, ApiMethod.Get, "${bookPath(target.bookId)}/resources",
                query = mapOf("page" to listOf(page.toString()), "pageSize" to listOf("100"))) { payload ->
                val values = payload.array("resources") ?: return@call protocolFailure("RESOURCES_MISSING")
                val mapped = values.map(::managedResource)
                if (mapped.any { it == null || it.bookId != target.bookId }) return@call protocolFailure("RESOURCE_IDENTITY_MISMATCH")
                val pages = (payload["totalPages"] as? JsonPrimitive)?.intOrNull
                    ?: (payload.objectValue("pagination")?.get("totalPages") as? JsonPrimitive)?.intOrNull
                    ?: return@call protocolFailure("RESOURCE_PAGINATION_MISSING")
                if (pages < 0) return@call protocolFailure("RESOURCE_PAGINATION_INVALID")
                WorkManagementResult.Content(mapped.filterNotNull() to pages)
            }
            if (result is WorkManagementResult.Failure) return result
            val (values, pages) = (result as WorkManagementResult.Content).value
            if (page < pages && values.isEmpty()) return protocolFailure("RESOURCE_PAGINATION_INVALID")
            resources.addAll(values)
            page++
        } while (page <= pages)
        if (target.kind == ManagementObject.Resource && resources.none { it.id == target.id }) return inaccessible()
        var directory: ManagedDirectory? = null
        if (target.kind == ManagementObject.Directory) {
            val result = call(context, ApiMethod.Get, "${bookPath(target.bookId)}/contents",
                query = mapOf("sourceNodeId" to listOf(target.id), "pageSize" to listOf("1"))) { payload ->
                val node = payload.objectValue("currentNode") ?: return@call protocolFailure("SOURCE_NODE_MISSING")
                if (node.string("sourceNodeId") != target.id || !node.string("resourceId").isNullOrBlank()) return@call inaccessible()
                WorkManagementResult.Content(ManagedDirectory(target.id, node.string("title").orEmpty(),
                    node.string("description").orEmpty(), node.string("coverUrl").orEmpty(), node.string("representativeResourceId")))
            }
            if (result is WorkManagementResult.Failure) return result
            directory = (result as WorkManagementResult.Content).value
        }
        return WorkManagementResult.Content(ManagementSnapshot(book, resources.distinctBy { it.id }, directory))
    }

    override suspend fun saveBookFields(context: BookManagementContext, bookId: String, draft: BookMetadataDraft): WorkManagementResult<Unit> =
        callUnit(context, ApiMethod.Patch, bookPath(bookId), nullableEncoder.encodeToString(BookMetadataRequest(
            draft.title.trim(), draft.author.orEmpty().trim(), draft.description.orEmpty().trim(),
            draft.seriesName?.trim()?.ifBlank { null }, draft.seriesIndex)))

    override suspend fun replaceBookTags(context: BookManagementContext, bookId: String, current: List<String>, next: List<String>): WorkManagementResult<Unit> {
        val before = current.associateBy { it.trim().lowercase() }
        val after = next.associateBy { it.trim().lowercase() }
        val add = after.filterKeys { it !in before }.values.toList()
        val remove = before.filterKeys { it !in after }.values.toList()
        return if (add.isEmpty() && remove.isEmpty()) WorkManagementResult.Content(Unit)
        else callUnit(context, ApiMethod.Post, "/api/library/operations/books/metadata",
            encoder.encodeToString(BulkBookMetadataRequest(listOf(bookId), add, remove)))
    }

    override suspend fun saveResourceFields(context: BookManagementContext, bookId: String, resourceId: String, fields: List<ManagementFieldValue>): WorkManagementResult<Unit> =
        callUnit(context, ApiMethod.Patch, resourcePath(bookId, resourceId), buildJsonObject {
            fields.forEach { (field, raw) ->
                val value = raw.trim()
                put(field.wireName, when {
                    field == ManagementField.ResourceIndex -> value.toDoubleOrNull()?.let(::JsonPrimitive) ?: JsonNull
                    value.isEmpty() && field != ManagementField.Title -> JsonNull
                    else -> JsonPrimitive(value)
                })
            }
        }.toString())

    override suspend fun saveSourcePresentation(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String, removeCover: Boolean, upload: CoverUpload?): WorkManagementResult<Unit> =
        multipart(context, ApiMultipartRequest(ApiMethod.Put, "${bookPath(bookId)}/source-nodes/${sourceNodeId.encodeURLPathPart()}",
            JsonElement.serializer(), upload?.let { ApiMultipartFile("cover", it.safeFileName(), it.mimeType, it.bytes) },
            mapOf("title" to title, "description" to description, "removeCover" to removeCover.toString())))

    override suspend fun regenerateBookImage(context: BookManagementContext, bookId: String): WorkManagementResult<Unit> =
        multipart(context, ApiMultipartRequest(ApiMethod.Post, "/api/library/operations/books/covers", JsonElement.serializer(),
            fields = mapOf("ids" to encoder.encodeToString(listOf(bookId)), "action" to "regenerate", "ratio" to "2:3", "quality" to "82", "maxDimension" to "1600")))

    override suspend fun deleteResourceSource(context: BookManagementContext, bookId: String, resourceId: String, confirmation: String, idempotencyKey: String): WorkManagementResult<Unit> =
        call(context, ApiMethod.Delete, "${resourcePath(bookId, resourceId)}/source",
            buildJsonObject { put("confirmation", confirmation) }.toString(), idempotencyKey = idempotencyKey) { WorkManagementResult.Content(Unit) }

    override suspend fun applyDirectoryMetadata(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String): WorkManagementResult<Unit> =
        callUnit(context, ApiMethod.Patch, "${bookPath(bookId)}/source-nodes/${sourceNodeId.encodeURLPathPart()}",
            nullableEncoder.encodeToString(SourceNodeMetadataRequest(title, description.ifBlank { null })))

    override suspend fun applyRecognizedFields(context: BookManagementContext, target: ManagementTarget, candidate: MetadataCandidate, fields: List<RecognizedField>): WorkManagementResult<MetadataApplyOutcome> =
        call(context, ApiMethod.Post, "${bookPath(target.bookId)}/metadata/apply", buildJsonObject {
            put("scope", if (target.kind == ManagementObject.Book) "book" else "resource")
            put("resourceId", if (target.kind == ManagementObject.Resource) JsonPrimitive(target.id) else JsonNull)
            put("fields", JsonArray(fields.map { JsonPrimitive(it.wireValue) }))
            put("candidate", candidateJson(candidate))
        }.toString()) { payload ->
            val status = payload.string("coverStatus")
            if (status !in listOf("notSelected", "applied", "failed")) return@call protocolFailure("METADATA_APPLY_INVALID")
            val applied = payload.array("appliedFields") ?: return@call protocolFailure("METADATA_APPLY_INVALID")
            val skipped = payload.array("skippedFields") ?: return@call protocolFailure("METADATA_APPLY_INVALID")
            WorkManagementResult.Content(MetadataApplyOutcome(applied.mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
                skipped.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }, requireNotNull(status)))
        }

    private suspend fun multipart(context: BookManagementContext, request: ApiMultipartRequest<JsonElement>): WorkManagementResult<Unit> {
        val client = clientProvider(context.profile)
        return when (val result = try { client.executeMultipart(request) } finally { client.close() }) {
            is ApiResult.Success -> WorkManagementResult.Content(Unit)
            is ApiResult.Failure -> WorkManagementResult.Failure(result.error.toManagementError())
        }
    }

    override suspend fun uploadCover(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
        upload: CoverUpload,
    ): WorkManagementResult<CoverMutationOutcome> {
        val client = clientProvider(context.profile)
        val result = try {
            client.executeMultipart(
                ApiMultipartRequest(
                    method = ApiMethod.Put,
                    apiPath = "${resourcePath(bookId, resourceId)}/cover",
                    responseDeserializer = JsonElement.serializer(),
                    file = ApiMultipartFile(
                        fieldName = "cover",
                        fileName = upload.safeFileName(),
                        contentType = upload.mimeType,
                        bytes = upload.bytes,
                    ),
                ),
            )
        } finally {
            client.close()
        }
        return when (result) {
            is ApiResult.Failure -> WorkManagementResult.Failure(result.error.toManagementError())
            is ApiResult.Success -> {
                val data = result.value as? JsonObject
                    ?: return protocolFailure("MANAGEMENT_RESPONSE_INVALID")
                val resource = data.objectValue("resource")
                    ?: return protocolFailure("COVER_RESOURCE_MISSING")
                val returnedResourceId = resource.string("id")
                    ?: return protocolFailure("COVER_RESOURCE_ID_MISSING")
                val returnedBookId = resource.string("bookId")
                    ?: return protocolFailure("COVER_BOOK_ID_MISSING")
                if (returnedResourceId != resourceId || returnedBookId != bookId) {
                    protocolFailure("COVER_RESOURCE_IDENTITY_MISMATCH")
                } else {
                    WorkManagementResult.Content(
                        CoverMutationOutcome(
                            resourceId = returnedResourceId,
                            coverUrl = resource.string("coverUrl").orEmpty(),
                        ),
                    )
                }
            }
        }
    }

    override suspend fun regenerateResourceCover(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
    ): WorkManagementResult<Unit> = callUnit(
        context,
        ApiMethod.Post,
        "${resourcePath(bookId, resourceId)}/cover/regenerate",
    )

    override suspend fun rescanBook(
        context: BookManagementContext,
        sourceNodeId: String,
    ): WorkManagementResult<Unit> = callUnit(
        context,
        ApiMethod.Post,
        "/api/source-nodes/${sourceNodeId.encodeURLPathPart()}/continue",
    )

    override suspend fun deleteBook(
        context: BookManagementContext,
        bookId: String,
    ): WorkManagementResult<BookDeletionOutcome> = call(
        context,
        ApiMethod.Post,
        "/api/library/operations/books/delete-sources",
        encoder.encodeToString(DeleteBookRequest(listOf(bookId))),
    ) { data ->
        val deleted = data.array("deletedBookIds").orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
        if (bookId !in deleted) protocolFailure("BOOK_DELETE_IDENTITY_MISMATCH")
        else WorkManagementResult.Content(BookDeletionOutcome(deleted))
    }

    override suspend fun loadMetadataProviders(
        context: BookManagementContext,
    ): WorkManagementResult<List<MetadataProvider>> = call(
        context,
        ApiMethod.Get,
        "/api/metadata/providers",
    ) { data ->
        val providers = data.array("providers") ?: return@call protocolFailure("METADATA_PROVIDERS_MISSING")
        WorkManagementResult.Content(
            providers.mapNotNull { element ->
                val provider = element as? JsonObject ?: return@mapNotNull null
                val id = provider.string("id") ?: return@mapNotNull null
                MetadataProvider(
                    id = id,
                    name = provider.string("name") ?: id,
                    enabled = provider.boolean("enabled") == true,
                )
            },
        )
    }

    override suspend fun searchMetadata(
        context: BookManagementContext,
        bookId: String,
        sourceNodeId: String,
        providerId: String,
        query: String,
    ): WorkManagementResult<MetadataSearchResult> = call(
        context,
        ApiMethod.Post,
        "${bookPath(bookId)}/source-nodes/${sourceNodeId.encodeURLPathPart()}/metadata/search",
        encoder.encodeToString(MetadataSearchRequest(providerId, query.trim().ifBlank { null })),
    ) { data ->
        val candidates = data.array("candidates") ?: return@call protocolFailure("METADATA_CANDIDATES_MISSING")
        WorkManagementResult.Content(
            MetadataSearchResult(
                candidates = candidates.mapNotNull(::metadataCandidate),
                message = data.string("message"),
            ),
        )
    }

    override suspend fun loadKindleSettings(
        context: BookManagementContext,
    ): WorkManagementResult<KindleSettings> = call(
        context,
        ApiMethod.Get,
        "/api/kindle-settings",
    ) { data ->
        val kindle = data.objectValue("kindle") ?: return@call protocolFailure("KINDLE_SETTINGS_MISSING")
        val smtp = data.objectValue("smtp")
        WorkManagementResult.Content(
            KindleSettings(
                recipientEmail = kindle.string("email").orEmpty(),
                smtpConfigured = smtp?.boolean("configured") == true,
                senderEmail = smtp?.string("fromEmail").orEmpty(),
            ),
        )
    }

    override suspend fun sendToKindle(
        context: BookManagementContext,
        bookId: String,
        assetId: String,
    ): WorkManagementResult<KindleSendOutcome> = call(
        context,
        ApiMethod.Post,
        "/api/kindle-send-tasks",
        encoder.encodeToString(KindleSendRequest(bookId = bookId, assetId = assetId)),
    ) { data -> WorkManagementResult.Content(KindleSendOutcome(data.boolean("alreadyQueued") == true)) }

    override suspend fun setReadingStatus(
        context: BookManagementContext,
        resourceId: String,
        status: ManagedReadingStatus,
    ): WorkManagementResult<Unit> = callUnit(
        context,
        ApiMethod.Put,
        "/api/reader/v4/resources/${resourceId.encodeURLPathPart()}/reading-status",
        encoder.encodeToString(ReadingStatusRequest(status.wireValue)),
    )

    override suspend fun setBookReadingStatus(
        context: BookManagementContext,
        bookId: String,
        status: ManagedReadingStatus,
    ): WorkManagementResult<Unit> = callUnit(
        context,
        ApiMethod.Post,
        "/api/library/operations/books/reading-status",
        encoder.encodeToString(BookReadingStatusRequest(listOf(bookId), status.wireValue)),
    )

    private suspend fun callUnit(
        context: BookManagementContext,
        method: ApiMethod,
        path: String,
        body: String? = null,
    ): WorkManagementResult<Unit> = call(
        context,
        method,
        path,
        body,
    ) { WorkManagementResult.Content(Unit) }

    private suspend fun <T> call(
        context: BookManagementContext,
        method: ApiMethod,
        path: String,
        body: String? = null,
        query: Map<String, List<String>> = emptyMap(),
        idempotencyKey: String? = null,
        transform: (JsonObject) -> WorkManagementResult<T>,
    ): WorkManagementResult<T> {
        val client = clientProvider(context.profile)
        return when (val result = try {
            client.execute(
                ApiRequest(
                    method = method,
                    apiPath = path,
                    responseDeserializer = JsonElement.serializer(),
                    requestBody = body,
                    queryParameters = query,
                    idempotencyKey = idempotencyKey,
                ),
            )
        } finally {
            client.close()
        }) {
            is ApiResult.Failure -> WorkManagementResult.Failure(result.error.toManagementError())
            is ApiResult.Success -> {
                val data = result.value as? JsonObject ?: return protocolFailure("MANAGEMENT_RESPONSE_INVALID")
                transform(data)
            }
        }
    }

    private fun bookPath(bookId: String) = "/api/books/${bookId.encodeURLPathPart()}"
    private fun resourcePath(bookId: String, resourceId: String) =
        "${bookPath(bookId)}/resources/${resourceId.encodeURLPathPart()}"
}

private fun CoverUpload.safeFileName(): String = when (mimeType) {
    "image/png" -> "cover.png"
    "image/webp" -> "cover.webp"
    else -> "cover.jpg"
}

@Serializable
private data class BookMetadataRequest(
    val title: String? = null,
    val author: String? = null,
    val description: String? = null,
    val seriesName: String? = null,
    val seriesIndex: Double? = null,
)

@Serializable
private data class ResourceMetadataRequest(
    val title: String? = null,
    val description: String? = null,
    val publisher: String? = null,
    val publishedAt: String? = null,
    val language: String? = null,
    val isbn: String? = null,
    val identifier: String? = null,
    val narrator: String? = null,
    val abridged: Boolean? = null,
    val resourceIndex: Double? = null,
)

@Serializable
private data class MetadataSearchRequest(val providerId: String, val query: String?)

@Serializable
private data class KindleSendRequest(val bookId: String, val assetId: String)

@Serializable
private data class ReadingStatusRequest(val status: String)

@Serializable
private data class BookReadingStatusRequest(val ids: List<String>, val status: String)

@Serializable
private data class BulkBookMetadataRequest(
    val ids: List<String>,
    val addTags: List<String>,
    val removeTags: List<String>,
    val fields: Map<String, String> = emptyMap(),
)

@Serializable
private data class DeleteBookRequest(
    val ids: List<String>,
    val confirmation: String = "DELETE_SOURCE_FILES",
)

@Serializable
private data class SourceNodeMetadataRequest(val title: String, val description: String? = null)

private fun metadataCandidate(element: JsonElement): MetadataCandidate? {
    val value = element as? JsonObject ?: return null
    val id = value.string("id") ?: return null
    val source = value.string("source") ?: return null
    return MetadataCandidate(
        id = id,
        source = source,
        title = value.string("title"),
        author = value.string("author"),
        description = value.string("description"),
        tags = value.array("tags").orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
        seriesName = value.string("seriesName"),
        publisher = value.string("publisher"),
        publishedAt = value.string("publishedAt"),
        language = value.string("language"),
        isbn = value.string("isbn"),
        coverUrl = value.string("coverUrl"),
        confidence = (value["confidence"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
        seriesIndex = (value["seriesIndex"] as? JsonPrimitive)?.doubleOrNull,
        identifier = value.string("identifier"), narrator = value.string("narrator"),
        abridged = value.boolean("abridged"), resourceIndex = (value["resourceIndex"] as? JsonPrimitive)?.doubleOrNull,
    )
}

private fun JsonObject.string(name: String): String? = (this[name] as? JsonPrimitive)?.contentOrNull
private fun JsonObject.boolean(name: String): Boolean? = (this[name] as? JsonPrimitive)?.booleanOrNull
private fun JsonObject.array(name: String): JsonArray? = this[name] as? JsonArray
private fun JsonObject.objectValue(name: String): JsonObject? = this[name] as? JsonObject
private fun String?.normalized(): String? = this?.trim()?.ifBlank { null }

private fun AppError.toManagementError() = WorkManagementError(
    kind = when (kind) {
        AppErrorKind.Unauthorized -> WorkManagementErrorKind.Unauthorized
        AppErrorKind.Forbidden -> WorkManagementErrorKind.Forbidden
        AppErrorKind.NotFoundOrUnavailable, AppErrorKind.Gone -> WorkManagementErrorKind.Inaccessible
        AppErrorKind.Conflict -> WorkManagementErrorKind.Conflict
        AppErrorKind.InvalidRequest, AppErrorKind.Validation -> WorkManagementErrorKind.Validation
        AppErrorKind.NetworkUnavailable, AppErrorKind.Timeout, AppErrorKind.TlsFailure -> WorkManagementErrorKind.Offline
        AppErrorKind.StorageFailure -> WorkManagementErrorKind.Storage
        AppErrorKind.ServerFailure, AppErrorKind.ServiceUnavailable, AppErrorKind.RateLimited -> WorkManagementErrorKind.Server
        else -> WorkManagementErrorKind.Protocol
    },
    code = code,
    fieldErrors = fieldErrors,
)

private fun <T> unavailable(code: String): WorkManagementResult<T> =
    WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Unavailable, code))

private fun <T> protocolFailure(code: String): WorkManagementResult<T> =
    WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Protocol, code))

private fun <T> inaccessible(): WorkManagementResult<T> =
    WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Inaccessible, "CONTENT_NOT_ACCESSIBLE"))

private fun managedResource(element: JsonElement): ManagedResource? {
    val resource = element as? JsonObject ?: return null
    val id = resource.string("id")?.takeIf(String::isNotBlank) ?: return null
    val book = resource.string("bookId")?.takeIf(String::isNotBlank) ?: return null
    val node = resource.string("sourceNodeId")?.takeIf(String::isNotBlank) ?: return null
    val assets = resource.array("assets")?.map { raw ->
        val asset = raw as? JsonObject ?: return null
        ManagedAsset(asset.string("id") ?: return null, asset.string("title").orEmpty(),
            asset.string("role").orEmpty(), asset.string("size").orEmpty())
    }.orEmpty()
    return ManagedResource(id, book, node, resource.string("title").orEmpty(), resource.string("description").orEmpty(),
        resource.string("format").orEmpty(), resource.boolean("kindleSendAvailable") == true,
        ManagementField.entries.map { ManagementFieldValue(it, resource.string(it.wireName).orEmpty()) },
        resource.string("coverUrl").orEmpty(), assets)
}

private fun candidateJson(candidate: MetadataCandidate): JsonObject = buildJsonObject {
    put("id", candidate.id); put("source", candidate.source); put("title", candidate.title)
    put("author", candidate.author); put("description", candidate.description)
    put("tags", JsonArray(candidate.tags.map(::JsonPrimitive))); put("seriesName", candidate.seriesName)
    put("seriesIndex", candidate.seriesIndex); put("publisher", candidate.publisher); put("publishedAt", candidate.publishedAt)
    put("language", candidate.language); put("isbn", candidate.isbn); put("identifier", candidate.identifier)
    put("narrator", candidate.narrator); put("abridged", candidate.abridged); put("resourceIndex", candidate.resourceIndex)
    put("coverUrl", candidate.coverUrl); put("confidence", candidate.confidence)
}
