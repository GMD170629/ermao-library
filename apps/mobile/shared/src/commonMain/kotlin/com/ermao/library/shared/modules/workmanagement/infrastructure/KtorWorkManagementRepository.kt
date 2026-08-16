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
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedMediaKind
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
import com.ermao.library.shared.modules.workmanagement.domain.VolumeMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementError
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import com.ermao.library.shared.modules.workmanagement.domain.WorkMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.WorkTransferTarget
import io.ktor.http.encodeURLPathPart
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
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
        context: WorkManagementContext,
    ): WorkManagementResult<Boolean> = call(context, ApiMethod.Get, "/api/mobile/compatibility") { data ->
        val capabilities = data.objectValue("capabilities") ?: return@call protocolFailure("CAPABILITIES_MISSING")
        WorkManagementResult.Content(capabilities.boolean("workDetailManagement") == true)
    }

    override suspend fun updateWork(
        context: WorkManagementContext,
        workId: String,
        draft: WorkMetadataDraft,
    ): WorkManagementResult<Unit> = callUnit(
        context,
        ApiMethod.Patch,
        workPath(workId),
        encoder.encodeToString(
            WorkMetadataRequest(
                title = draft.title.trim(),
                author = draft.author.trim(),
                description = draft.description.trim(),
                seriesName = draft.seriesName?.trim()?.ifBlank { null },
                seriesIndex = draft.seriesIndex,
                tags = draft.tags.map(String::trim).filter(String::isNotBlank).distinct(),
            ),
        ),
    )

    override suspend fun uploadCover(
        context: WorkManagementContext,
        workId: String,
        upload: CoverUpload,
    ): WorkManagementResult<Unit> {
        val client = clientProvider(context.profile)
        return when (val result = client.executeMultipart(
            ApiMultipartRequest(
                apiPath = "${workPath(workId)}/cover/upload",
                responseDeserializer = JsonElement.serializer(),
                file = ApiMultipartFile("cover", upload.fileName, upload.mimeType, upload.bytes),
            ),
        )) {
            is ApiResult.Failure -> WorkManagementResult.Failure(result.error.toManagementError())
            is ApiResult.Success -> WorkManagementResult.Content(Unit)
        }
    }

    override suspend fun regenerateCover(
        context: WorkManagementContext,
        workId: String,
    ): WorkManagementResult<Unit> = callUnit(context, ApiMethod.Post, "${workPath(workId)}/cover/regenerate")

    override suspend fun deleteWork(
        context: WorkManagementContext,
        workId: String,
    ): WorkManagementResult<WorkMutationOutcome> = call(
        context,
        ApiMethod.Delete,
        workPath(workId),
        encoder.encodeToString(DeleteWorkRequest()),
    ) { WorkManagementResult.Content(WorkMutationOutcome(workId = workId, deletedWork = true)) }

    override suspend fun updateVolume(
        context: WorkManagementContext,
        workId: String,
        volumeId: String,
        draft: VolumeMetadataDraft,
    ): WorkManagementResult<WorkMutationOutcome> = mutationCall(
        context,
        ApiMethod.Patch,
        volumePath(workId, volumeId),
        workId,
        encoder.encodeToString(
            VolumeMetadataRequest(
                title = draft.title.trim(),
                volumeIndex = draft.volumeIndex,
                sortOrder = draft.sortOrder,
                publisher = draft.publisher.normalized(),
                language = draft.language.normalized(),
                isbn = draft.isbn.normalized(),
                identifier = draft.identifier.normalized(),
                narrator = draft.narrator.normalized(),
            ),
        ),
    )

    override suspend fun reclassifyVolume(
        context: WorkManagementContext,
        workId: String,
        volumeId: String,
        mediaKind: ManagedMediaKind,
    ): WorkManagementResult<WorkMutationOutcome> = mutationCall(
        context,
        ApiMethod.Post,
        "${volumePath(workId, volumeId)}/reclassify",
        workId,
        encoder.encodeToString(ReclassifyRequest(mediaKind.wireValue)),
    )

    override suspend fun splitVolume(
        context: WorkManagementContext,
        workId: String,
        volumeId: String,
        title: String,
        author: String?,
    ): WorkManagementResult<WorkMutationOutcome> = mutationCall(
        context,
        ApiMethod.Post,
        "${volumePath(workId, volumeId)}/split",
        workId,
        encoder.encodeToString(SplitRequest(title.trim(), author.normalized())),
    )

    override suspend fun transferVolume(
        context: WorkManagementContext,
        workId: String,
        volumeId: String,
        targetWorkId: String,
    ): WorkManagementResult<WorkMutationOutcome> = mutationCall(
        context,
        ApiMethod.Post,
        "${volumePath(workId, volumeId)}/move-to",
        workId,
        encoder.encodeToString(TransferRequest(targetWorkId)),
    )

    override suspend fun deleteVolume(
        context: WorkManagementContext,
        workId: String,
        volumeId: String,
    ): WorkManagementResult<WorkMutationOutcome> = mutationCall(
        context,
        ApiMethod.Delete,
        volumePath(workId, volumeId),
        workId,
    )

    override suspend fun searchTransferTargets(
        context: WorkManagementContext,
        workId: String,
        query: String,
    ): WorkManagementResult<List<WorkTransferTarget>> = call(
        context,
        ApiMethod.Get,
        "/api/works",
        queryParameters = mapOf(
            "page" to listOf("1"),
            "pageSize" to listOf("20"),
            "view" to listOf("bookshelf"),
            "visibility" to listOf("active"),
            "search" to listOf(query.trim()),
        ),
    ) { data ->
        val books = data.array("books") ?: return@call protocolFailure("TRANSFER_TARGETS_MISSING")
        WorkManagementResult.Content(
            books.mapNotNull { element ->
                val book = element as? JsonObject ?: return@mapNotNull null
                val id = book.string("id") ?: return@mapNotNull null
                if (id == workId) return@mapNotNull null
                WorkTransferTarget(id, book.string("title") ?: id, book.string("author").orEmpty())
            },
        )
    }

    override suspend fun loadMetadataProviders(
        context: WorkManagementContext,
        mediaKind: ManagedMediaKind,
    ): WorkManagementResult<List<MetadataProvider>> = call(
        context,
        ApiMethod.Get,
        "/api/metadata/providers",
    ) { data ->
        val providers = data.array("providers") ?: return@call protocolFailure("METADATA_PROVIDERS_MISSING")
        val enabledIds = data.array("pipelines")
            ?.mapNotNull { it as? JsonObject }
            ?.firstOrNull { it.string("mediaKind") == mediaKind.wireValue }
            ?.array("providers")
            ?.mapNotNull { item ->
                val value = item as? JsonObject ?: return@mapNotNull null
                value.string("providerId")?.takeIf { value.boolean("enabled") == true }
            }
            ?.toSet()
            .orEmpty()
        WorkManagementResult.Content(
            providers.mapNotNull { element ->
                val provider = element as? JsonObject ?: return@mapNotNull null
                val id = provider.string("id") ?: return@mapNotNull null
                val mediaKinds = provider.array("mediaKinds")
                    .orEmpty()
                    .mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.toManagedMediaKind() }
                    .toSet()
                MetadataProvider(
                    id = id,
                    name = provider.string("name") ?: id,
                    enabled = provider.boolean("enabled") == true && id in enabledIds,
                    mediaKinds = mediaKinds,
                )
            }.filter { mediaKind in it.mediaKinds },
        )
    }

    override suspend fun searchMetadata(
        context: WorkManagementContext,
        workId: String,
        providerId: String,
        query: String,
    ): WorkManagementResult<MetadataSearchResult> = call(
        context,
        ApiMethod.Post,
        "${workPath(workId)}/metadata/search",
        encoder.encodeToString(MetadataSearchRequest(providerId, query.trim())),
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
        context: WorkManagementContext,
        workId: String,
        providerId: String,
        candidate: MetadataCandidate,
        fields: Set<MetadataField>,
        volumeId: String?,
        applyToAllVolumes: Boolean,
    ): WorkManagementResult<Unit> {
        require(fields.isNotEmpty())
        return callUnit(
            context,
            ApiMethod.Post,
            "${workPath(workId)}/metadata/apply",
            encoder.encodeToString(
                MetadataApplyRequest(
                    source = providerId,
                    candidate = candidate.toRequest(),
                    fields = fields.map(MetadataField::wireValue),
                    volumeId = volumeId,
                ),
            ),
            queryParameters = mapOf("applyToAllVolumes" to listOf(applyToAllVolumes.toString())),
        )
    }

    override suspend fun loadKindleSettings(
        context: WorkManagementContext,
    ): WorkManagementResult<KindleSettings> = call(context, ApiMethod.Get, "/api/kindle-settings") { data ->
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
        context: WorkManagementContext,
        workId: String,
        fileId: String,
    ): WorkManagementResult<KindleSendOutcome> = call(
        context,
        ApiMethod.Post,
        "/api/kindle-send-tasks",
        encoder.encodeToString(KindleSendRequest(workId, fileId)),
    ) { data -> WorkManagementResult.Content(KindleSendOutcome(data.boolean("alreadyQueued") == true)) }

    override suspend fun setReadingStatus(
        context: WorkManagementContext,
        volumeId: String,
        status: ManagedReadingStatus,
    ): WorkManagementResult<Unit> = callUnit(
        context,
        ApiMethod.Put,
        "/api/reader/v4/volumes/${volumeId.encodeURLPathPart()}/reading-status",
        encoder.encodeToString(ReadingStatusRequest(status.wireValue)),
    )

    private suspend fun mutationCall(
        context: WorkManagementContext,
        method: ApiMethod,
        path: String,
        workId: String,
        body: String? = null,
    ): WorkManagementResult<WorkMutationOutcome> = call(context, method, path, body) { data ->
        WorkManagementResult.Content(
            WorkMutationOutcome(
                workId = data.string("workId") ?: workId,
                deletedWork = data.boolean("deletedWork") == true,
                targetWorkId = data.string("targetWorkId"),
                targetMediaVersionId = data.string("targetMediaVersionId"),
                operationId = data.objectValue("operation")?.string("id"),
            ),
        )
    }

    private suspend fun callUnit(
        context: WorkManagementContext,
        method: ApiMethod,
        path: String,
        body: String? = null,
        queryParameters: Map<String, List<String>> = emptyMap(),
    ): WorkManagementResult<Unit> = call(context, method, path, body, queryParameters) {
        WorkManagementResult.Content(Unit)
    }

    private suspend fun <T> call(
        context: WorkManagementContext,
        method: ApiMethod,
        path: String,
        body: String? = null,
        queryParameters: Map<String, List<String>> = emptyMap(),
        transform: (JsonObject) -> WorkManagementResult<T>,
    ): WorkManagementResult<T> = when (val result = clientProvider(context.profile).execute(
        ApiRequest(
            method = method,
            apiPath = path,
            responseDeserializer = JsonElement.serializer(),
            requestBody = body,
            queryParameters = queryParameters,
        ),
    )) {
        is ApiResult.Failure -> WorkManagementResult.Failure(result.error.toManagementError())
        is ApiResult.Success -> {
            val data = result.value as? JsonObject ?: return protocolFailure("MANAGEMENT_RESPONSE_INVALID")
            transform(data)
        }
    }

    private fun workPath(workId: String) = "/api/works/${workId.encodeURLPathPart()}"
    private fun volumePath(workId: String, volumeId: String) =
        "${workPath(workId)}/volumes/${volumeId.encodeURLPathPart()}"
}

@Serializable
private data class WorkMetadataRequest(
    val title: String,
    val author: String,
    val description: String,
    val seriesName: String?,
    val seriesIndex: Double?,
    val tags: List<String>,
    val organized: Boolean = true,
)

@Serializable
private data class DeleteWorkRequest(val deleteSource: Boolean = false)

@Serializable
private data class VolumeMetadataRequest(
    val title: String,
    val volumeIndex: Double?,
    val sortOrder: Int,
    val publisher: String?,
    val language: String?,
    val isbn: String?,
    val identifier: String?,
    val narrator: String?,
)

@Serializable
private data class ReclassifyRequest(val targetMediaKind: String, val applyTo: String = "VOLUME")

@Serializable
private data class SplitRequest(val title: String, val author: String?)

@Serializable
private data class TransferRequest(val targetWorkId: String)

@Serializable
private data class MetadataSearchRequest(val source: String, val query: String)

@Serializable
private data class MetadataApplyRequest(
    val source: String,
    val candidate: MetadataCandidateRequest,
    val fields: List<String>,
    val volumeId: String?,
)

@Serializable
private data class MetadataCandidateRequest(
    val id: String,
    val source: String,
    val title: String?,
    val author: String?,
    val description: String?,
    val tags: List<String>,
    val seriesName: String?,
    val volumeMetadata: VolumeMetadataCandidateRequest,
    val coverUrl: String?,
    val confidence: Double,
)

@Serializable
private data class VolumeMetadataCandidateRequest(
    val publisher: String?,
    val publishedAt: String?,
    val language: String?,
    val isbn: String?,
)

@Serializable
private data class KindleSendRequest(val workId: String, val fileId: String)

@Serializable
private data class ReadingStatusRequest(val status: String)

private fun metadataCandidate(element: JsonElement): MetadataCandidate? {
    val value = element as? JsonObject ?: return null
    val id = value.string("id") ?: return null
    val source = value.string("source") ?: return null
    val volume = value.objectValue("volumeMetadata")
    return MetadataCandidate(
        id = id,
        source = source,
        title = value.string("title"),
        author = value.string("author"),
        description = value.string("description"),
        tags = value.array("tags").orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
        seriesName = value.string("seriesName"),
        publisher = volume?.string("publisher") ?: value.string("publisher"),
        publishedAt = volume?.string("publishedAt") ?: value.string("publishedAt"),
        language = volume?.string("language") ?: value.string("language"),
        isbn = volume?.string("isbn") ?: value.string("isbn"),
        coverUrl = value.string("coverUrl"),
        confidence = (value["confidence"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
    )
}

private fun MetadataCandidate.toRequest() = MetadataCandidateRequest(
    id = id,
    source = source,
    title = title,
    author = author,
    description = description,
    tags = tags,
    seriesName = seriesName,
    volumeMetadata = VolumeMetadataCandidateRequest(publisher, publishedAt, language, isbn),
    coverUrl = coverUrl,
    confidence = confidence,
)

private fun JsonObject.string(name: String): String? =
    (this[name] as? JsonPrimitive)?.contentOrNull

private fun JsonObject.boolean(name: String): Boolean? =
    (this[name] as? JsonPrimitive)?.booleanOrNull

private fun JsonObject.array(name: String): JsonArray? = this[name] as? JsonArray

private fun JsonObject.objectValue(name: String): JsonObject? = this[name] as? JsonObject

private fun String?.normalized(): String? = this?.trim()?.ifBlank { null }

private fun String.toManagedMediaKind(): ManagedMediaKind? =
    ManagedMediaKind.entries.firstOrNull { it.wireValue == this }

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

private fun <T> protocolFailure(code: String): WorkManagementResult<T> =
    WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Protocol, code))
