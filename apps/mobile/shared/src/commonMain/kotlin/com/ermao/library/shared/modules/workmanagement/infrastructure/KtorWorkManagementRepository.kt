package com.ermao.library.shared.modules.workmanagement.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedMediaKind
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

class KtorWorkManagementRepository(
    private val clientProvider: (com.ermao.library.shared.modules.servers.domain.ServerProfile) -> ApiClient,
) : WorkManagementRepository {
    constructor(clients: ApiClientFactory) : this(clients::create)

    private val encoder = Json { explicitNulls = false; encodeDefaults = true }

    override suspend fun supportsNativeManagement(
        context: BookManagementContext,
    ): WorkManagementResult<Boolean> = compatibility(context)

    override suspend fun updateBook(
        context: BookManagementContext,
        bookId: String,
        draft: BookMetadataDraft,
    ): WorkManagementResult<Unit> {
        if (draft.tags.isNotEmpty()) return unavailable("BOOK_TAG_UPDATE_UNAVAILABLE")
        return callUnit(
            context,
            ApiMethod.Patch,
            bookPath(bookId),
            encoder.encodeToString(
                BookMetadataRequest(
                    title = draft.title.trim(),
                    author = draft.author?.trim()?.ifBlank { null },
                    description = draft.description?.trim()?.ifBlank { null },
                    seriesName = draft.seriesName?.trim()?.ifBlank { null },
                    seriesIndex = draft.seriesIndex,
                ),
            ),
        )
    }

    override suspend fun uploadCover(
        context: BookManagementContext,
        bookId: String,
        sourceNodeId: String,
        title: String,
        description: String?,
        upload: CoverUpload,
    ): WorkManagementResult<Unit> =
        // The current source-node presentation endpoint requires title/description form fields
        // in addition to the file. The shared multipart client cannot express those fields yet;
        // keep this operation explicitly disabled instead of issuing a guaranteed 422 request.
        unavailable("BOOK_COVER_UPLOAD_UNAVAILABLE")

    override suspend fun regenerateResourceCover(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
    ): WorkManagementResult<Unit> = callUnit(
        context,
        ApiMethod.Post,
        "${resourcePath(bookId, resourceId)}/cover/regenerate",
    )

    override suspend fun updateResource(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
        draft: ResourceMetadataDraft,
    ): WorkManagementResult<BookMutationOutcome> = mutationCall(
        context,
        ApiMethod.Patch,
        resourcePath(bookId, resourceId),
        bookId,
        encoder.encodeToString(
            ResourceMetadataRequest(
                title = draft.title.normalized(),
                description = draft.description.normalized(),
                publisher = draft.publisher.normalized(),
                publishedAt = draft.publishedAt.normalized(),
                language = draft.language.normalized(),
                isbn = draft.isbn.normalized(),
                identifier = draft.identifier.normalized(),
                narrator = draft.narrator.normalized(),
                abridged = draft.abridged,
                resourceIndex = draft.resourceIndex,
            ),
        ),
    )

    override suspend fun reclassifyResource(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
        mediaKind: ManagedMediaKind,
    ): WorkManagementResult<BookMutationOutcome> = mutationCall(
        context,
        ApiMethod.Post,
        "${resourcePath(bookId, resourceId)}/reclassify",
        bookId,
        encoder.encodeToString(ReclassifyRequest(mediaKind.wireValue)),
    )

    override suspend fun loadMetadataProviders(
        context: BookManagementContext,
        mediaKind: ManagedMediaKind,
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
                val mediaKinds = provider.array("mediaKinds")
                    .orEmpty()
                    .mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.toManagedMediaKind() }
                    .toSet()
                if (mediaKind !in mediaKinds) return@mapNotNull null
                MetadataProvider(
                    id = id,
                    name = provider.string("name") ?: id,
                    enabled = provider.boolean("enabled") == true,
                    mediaKinds = mediaKinds,
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

    override suspend fun applyMetadata(
        context: BookManagementContext,
        bookId: String,
        sourceNodeId: String,
        providerId: String,
        candidate: MetadataCandidate,
        fields: Set<MetadataField>,
        resourceId: String?,
        applyToAllResources: Boolean,
    ): WorkManagementResult<Unit> =
        // There is no current apply-candidate endpoint. Do not emulate it with multiple patches.
        unavailable("METADATA_APPLY_UNAVAILABLE")

    override suspend fun loadKindleSettings(
        context: BookManagementContext,
    ): WorkManagementResult<KindleSettings> = call(
        context,
        ApiMethod.Get,
        "/api/kindle-settings",
        requiresBookManagement = false,
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
        requiresBookManagement = false,
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
        requiresBookManagement = false,
    )

    private suspend fun mutationCall(
        context: BookManagementContext,
        method: ApiMethod,
        path: String,
        bookId: String,
        body: String? = null,
    ): WorkManagementResult<BookMutationOutcome> = call(context, method, path, body) { data ->
        WorkManagementResult.Content(
            BookMutationOutcome(
                bookId = data.string("bookId") ?: bookId,
                operationId = data.objectValue("operation")?.string("id"),
            ),
        )
    }

    private suspend fun callUnit(
        context: BookManagementContext,
        method: ApiMethod,
        path: String,
        body: String? = null,
        requiresBookManagement: Boolean = true,
    ): WorkManagementResult<Unit> = call(
        context,
        method,
        path,
        body,
        requiresBookManagement = requiresBookManagement,
    ) { WorkManagementResult.Content(Unit) }

    private suspend fun <T> call(
        context: BookManagementContext,
        method: ApiMethod,
        path: String,
        body: String? = null,
        requiresBookManagement: Boolean = true,
        transform: (JsonObject) -> WorkManagementResult<T>,
    ): WorkManagementResult<T> {
        if (requiresBookManagement) {
            when (val capability = checkBookManagement(context)) {
                is WorkManagementResult.Failure -> return WorkManagementResult.Failure(capability.error)
                is WorkManagementResult.Content -> Unit
            }
        }
        val client = clientProvider(context.profile)
        return when (val result = try {
            client.execute(
                ApiRequest(
                    method = method,
                    apiPath = path,
                    responseDeserializer = JsonElement.serializer(),
                    requestBody = body,
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

    private suspend fun compatibility(context: BookManagementContext): WorkManagementResult<Boolean> {
        val client = clientProvider(context.profile)
        return when (val result = try {
            client.execute(
                ApiRequest(
                    method = ApiMethod.Get,
                    apiPath = "/api/mobile/compatibility",
                    responseDeserializer = JsonElement.serializer(),
                ),
            )
        } finally {
            client.close()
        }) {
            is ApiResult.Failure -> WorkManagementResult.Failure(result.error.toManagementError())
            is ApiResult.Success -> {
                val data = result.value as? JsonObject ?: return protocolFailure("COMPATIBILITY_RESPONSE_INVALID")
                val capabilities = data.objectValue("capabilities")
                    ?: return protocolFailure("CAPABILITIES_MISSING")
                WorkManagementResult.Content(capabilities.boolean("bookDetailManagement") == true)
            }
        }
    }

    private suspend fun checkBookManagement(context: BookManagementContext): WorkManagementResult<Unit> =
        when (val result = compatibility(context)) {
            is WorkManagementResult.Failure -> WorkManagementResult.Failure(result.error)
            is WorkManagementResult.Content -> if (result.value) {
                WorkManagementResult.Content(Unit)
            } else {
                unavailable("BOOK_DETAIL_MANAGEMENT_UNAVAILABLE")
            }
        }

    private fun bookPath(bookId: String) = "/api/books/${bookId.encodeURLPathPart()}"
    private fun resourcePath(bookId: String, resourceId: String) =
        "${bookPath(bookId)}/resources/${resourceId.encodeURLPathPart()}"
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
private data class ReclassifyRequest(
    val targetMediaKind: String,
    val applyTo: String = "RESOURCE",
)

@Serializable
private data class MetadataSearchRequest(val providerId: String, val query: String?)

@Serializable
private data class KindleSendRequest(val bookId: String, val assetId: String)

@Serializable
private data class ReadingStatusRequest(val status: String)

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
    )
}

private fun JsonObject.string(name: String): String? = (this[name] as? JsonPrimitive)?.contentOrNull
private fun JsonObject.boolean(name: String): Boolean? = (this[name] as? JsonPrimitive)?.booleanOrNull
private fun JsonObject.array(name: String): JsonArray? = this[name] as? JsonArray
private fun JsonObject.objectValue(name: String): JsonObject? = this[name] as? JsonObject
private fun String?.normalized(): String? = this?.trim()?.ifBlank { null }
private fun String.toManagedMediaKind(): ManagedMediaKind? = ManagedMediaKind.entries.firstOrNull { it.wireValue == this }

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
