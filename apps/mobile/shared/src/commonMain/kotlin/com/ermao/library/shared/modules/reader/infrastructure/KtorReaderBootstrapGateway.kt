package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.reader.application.ReaderBootstrap
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapGateway
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.application.ReaderPdfAccess
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult
import com.ermao.library.shared.modules.reader.application.ReaderComicAccess
import com.ermao.library.shared.modules.reader.application.ReaderComicPage
import com.ermao.library.shared.modules.reader.application.ReaderNavigationUnit
import com.ermao.library.shared.modules.reader.application.ReaderPdfPage
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResource
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.domain.isValidComicRevision
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/** Resource-first Reader v4 gateway. It deliberately rejects the retired Work/Version/Volume wire. */
class KtorReaderBootstrapGateway internal constructor(
    private val createClient: (com.ermao.library.shared.modules.servers.domain.ServerProfile) -> ApiClient,
    private val json: Json = Json { encodeDefaults = true; explicitNulls = false; ignoreUnknownKeys = false },
    private val progressMapper: ReaderServerWireMapper = ReaderServerWireMapper(),
) : com.ermao.library.shared.modules.reader.application.ReaderBootstrapGateway {
    constructor(clients: ApiClientFactory) : this(clients::create)

    override suspend fun load(request: ReaderBootstrapRequest): ReaderBootstrapResult {
        val client = createClient(request.profile)
        return try {
            when (val result = client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    "/api/reader/v4/resources/${encodePathSegment(request.resourceId)}/bootstrap",
                    JsonObject.serializer(),
                ),
            )) {
                is ApiResult.Failure -> ReaderBootstrapResult.Failure(
                    result.error.code,
                    result.error.kind.isRecoverableReaderFailure(),
                )
                is ApiResult.Success -> try {
                    val bootstrap = json.decodeFromJsonElement(ReaderBootstrapWire.serializer(), result.value)
                    when (val preflight = bootstrap.validateBeforeSecondaryRequest(request)) {
                        is ReaderBootstrapPreflight.Failure -> preflight.value
                        is ReaderBootstrapPreflight.Content -> when (val manifest = loadComicManifest(
                            client,
                            preflight.comicAccess,
                        )) {
                            is ComicManifestLoad.Failure -> ReaderBootstrapResult.Failure(
                                manifest.code,
                                manifest.recoverable,
                            )
                            is ComicManifestLoad.Content -> bootstrap.toDomain(
                                request,
                                preflight.sourceFormat,
                                preflight.comicAccess,
                                manifest.value,
                            )
                        }
                    }
                } catch (_: IllegalArgumentException) {
                    ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", false)
                }
            }
        } finally {
            client.close()
        }
    }

    private suspend fun loadComicManifest(
        client: ApiClient,
        access: ReaderPublicationAccessWire?,
    ): ComicManifestLoad {
        if (access == null) return ComicManifestLoad.Content(null)
        return when (val result = client.execute(
            ApiRequest(ApiMethod.Get, requireNotNull(access.manifestUrl), JsonObject.serializer()),
        )) {
            is ApiResult.Failure -> ComicManifestLoad.Failure(
                result.error.code,
                result.error.kind.isRecoverableReaderFailure(),
            )
            is ApiResult.Success -> try {
                ComicManifestLoad.Content(
                    json.decodeFromJsonElement(ReaderComicManifestWire.serializer(), result.value),
                )
            } catch (_: IllegalArgumentException) {
                ComicManifestLoad.Failure("READER_COMIC_MANIFEST_INVALID", false)
            }
        }
    }

    private fun ReaderBootstrapWire.validateBeforeSecondaryRequest(
        request: ReaderBootstrapRequest,
    ): ReaderBootstrapPreflight {
        val exactSourceFormat = ReaderSourceFormat.entries.firstOrNull { it.wireValue == sourceFormat }
        if (schemaVersion != READER_SERVER_SCHEMA_VERSION || exactSourceFormat == null ||
            readerType != exactSourceFormat.readerTypeWire()
        ) {
            return ReaderBootstrapPreflight.Failure(
                ReaderBootstrapResult.Failure("READER_BOOTSTRAP_UNSUPPORTED", recoverable = false),
            )
        }
        if (userId != request.namespace.userId) {
            return ReaderBootstrapPreflight.Failure(
                ReaderBootstrapResult.Failure("READER_BOOTSTRAP_USER_MISMATCH", recoverable = false),
            )
        }
        val expectedResourcePath = "/api/resources/${encodePathSegment(request.resourceId)}"
        if (book.id.isBlank() || resource.id != request.resourceId || resource.bookId != book.id ||
            resource.sourceNodeId.isBlank() || resourceUrl != expectedResourcePath ||
            availableResources.any { it.id.isBlank() || it.bookId != book.id || it.sourceNodeId.isBlank() } ||
            availableResources.map(ReaderBootstrapResourceWire::id).distinct().size != availableResources.size ||
            assets.any { it.id.isBlank() || it.resourceId != resource.id || it.sourceNodeId.isBlank() } ||
            assets.map(ReaderBootstrapAssetWire::id).distinct().size != assets.size ||
            units.any { unit -> unit.assetId != null && assets.none { asset -> asset.id == unit.assetId } }
        ) {
            return ReaderBootstrapPreflight.Failure(
                ReaderBootstrapResult.Failure("READER_BOOTSTRAP_IDENTITY_MISMATCH", recoverable = false),
            )
        }
        if (resource.format != exactSourceFormat.fileKind || resource.readerType != readerType ||
            availableResources.any { !it.hasExactFormatAndMorphology() }
        ) {
            return ReaderBootstrapPreflight.Failure(
                ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", recoverable = false),
            )
        }
        if (!exactSourceFormat.isComic) {
            return if (publication == null) {
                ReaderBootstrapPreflight.Content(exactSourceFormat, comicAccess = null)
            } else {
                ReaderBootstrapPreflight.Failure(
                    ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", recoverable = false),
                )
            }
        }
        val access = publication
            ?: return ReaderBootstrapPreflight.Failure(
                ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", recoverable = false),
            )
        val readerPath = "/api/reader/v4/resources/${encodePathSegment(request.resourceId)}/comic"
        if (access.kind != "comic" || access.positionsUrl != null ||
            access.manifestUrl != "$readerPath/manifest" ||
            access.pageUrlTemplate != "$readerPath/pages/{pageIndex}" ||
            access.imageVariants != listOf("original", "data-saver")
        ) {
            return ReaderBootstrapPreflight.Failure(
                ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", recoverable = false),
            )
        }
        return ReaderBootstrapPreflight.Content(exactSourceFormat, access)
    }

    private fun ReaderBootstrapWire.toDomain(
        request: ReaderBootstrapRequest,
        exactSourceFormat: ReaderSourceFormat,
        validatedComicAccess: ReaderPublicationAccessWire?,
        comicManifest: ReaderComicManifestWire?,
    ): ReaderBootstrapResult {
        val orderedAssets = assets.sortedWith(compareBy<ReaderBootstrapAssetWire>({ it.sortOrder }, { it.id }))
        val primaryAsset = orderedAssets.firstOrNull { it.role.equals("PRIMARY", ignoreCase = true) }
            ?: orderedAssets.firstOrNull()
            ?: return ReaderBootstrapResult.Failure("READER_PUBLICATION_ASSET_MISSING", recoverable = false)
        if (primaryAsset.sizeBytes <= 0 || !primaryAsset.url.isSafeReaderMediaApiPath()) {
            return ReaderBootstrapResult.Failure("READER_PUBLICATION_ASSET_INVALID", recoverable = false)
        }
        val orderedUnits = units.asSequence()
            .filter(ReaderBootstrapUnitWire::isStructurallyValid)
            .sortedBy { requireNotNull(it.index) }
            .distinctBy { requireNotNull(it.id) }
            .distinctBy { requireNotNull(it.index) }
            .toList()
        val target = try {
            ReaderProgressSyncTarget(
                namespace = request.namespace,
                bookId = book.id,
                resourceId = resource.id,
                sourceFormat = exactSourceFormat.readerFormat,
            )
        } catch (_: IllegalArgumentException) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", false)
        }
        val comicAccess = validatedComicAccess?.let { access ->
            val manifest = comicManifest
                ?: return ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
            if (!isValidComicRevision(manifest.revision)) {
                return ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
            }
            ReaderComicAccess(
                manifestApiPath = requireNotNull(access.manifestUrl),
                pageApiPathTemplate = requireNotNull(access.pageUrlTemplate),
                imageVariants = access.imageVariants.toSet(),
                revision = manifest.revision,
            )
        }
        val comicPages = if (exactSourceFormat.isComic) {
            val manifest = comicManifest
                ?: return ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
            try {
                require(
                    manifest.schemaVersion == 2 && manifest.kind == "comic" &&
                        manifest.resourceId == resource.id &&
                        manifest.sourceFormat == exactSourceFormat.wireValue &&
                        isValidComicRevision(manifest.revision) &&
                        manifest.pageCount == manifest.readingOrder.size && manifest.pageCount > 0
                )
                manifest.readingOrder.mapIndexed { index, page ->
                    require(page.pageIndex == index && page.resourceHref == "pages/$index")
                    val unitTitle = orderedUnits.firstOrNull { it.pageIndexOrNull() == index }?.title
                    ReaderComicPage(
                        pageIndex = index,
                        resourceHref = page.resourceHref,
                        mediaType = page.mediaType,
                        width = page.width,
                        height = page.height,
                        title = page.title?.trim()?.takeIf(String::isNotEmpty)
                            ?: unitTitle?.trim()?.takeIf(String::isNotEmpty)
                            ?: (index + 1).toString(),
                    )
                }.also { require(it.isNotEmpty()) }
            } catch (_: IllegalArgumentException) {
                return ReaderBootstrapResult.Failure("READER_COMIC_INDEX_INVALID", false)
            }
        } else emptyList()
        val pdfPages = if (exactSourceFormat == ReaderSourceFormat.Pdf) {
            orderedUnits.mapIndexed { index, unit ->
                ReaderPdfPage(
                    pageIndex = index,
                    title = unit.title?.trim().orEmpty().ifEmpty { "${index + 1}" },
                )
            }
        } else emptyList()
        val remoteSnapshot = progressSnapshot?.let { snapshot -> runCatching {
            val snapshotSchema = (snapshot["schemaVersion"] as? JsonPrimitive)?.longOrNull
            require(snapshotSchema == READER_SERVER_SCHEMA_VERSION.toLong())
            progressMapper.decodeSnapshot(snapshot, resource.id)
        }.getOrNull() }
        if (!exactSourceFormat.acceptsMimeType(primaryAsset.mimeType)) {
            return ReaderBootstrapResult.Failure("READER_PUBLICATION_ASSET_INVALID", false)
        }
        val displayTitle = resource.title.ifBlank { book.title }
        val pdfAccess = if (exactSourceFormat == ReaderSourceFormat.Pdf) {
            ReaderPdfAccess(primaryAsset.url, primaryAsset.sizeBytes)
        } else null
        return ReaderBootstrapResult.Content(
            ReaderBootstrap(
                target = target,
                resource = ReaderBootstrapResource(
                    resourceId = resource.id,
                    displayTitle = displayTitle,
                    bookId = book.id,
                    sourceFormat = exactSourceFormat,
                    assetId = primaryAsset.id.takeUnless { exactSourceFormat == ReaderSourceFormat.ImageDir },
                ),
                pdfAccess = pdfAccess,
                remoteSnapshot = remoteSnapshot,
                units = orderedUnits.map { unit ->
                    ReaderNavigationUnit(
                        id = requireNotNull(unit.id),
                        index = requireNotNull(unit.index),
                        title = requireNotNull(unit.title).trim().ifEmpty { requireNotNull(unit.id) },
                        href = unit.href?.trim()?.takeIf(String::isNotEmpty),
                        assetId = unit.assetId?.trim()?.takeIf(String::isNotEmpty),
                        startMs = unit.startMs,
                        endMs = unit.endMs,
                        durationMs = unit.durationMs,
                    )
                },
                comicPages = comicPages,
                comicAccess = comicAccess,
                pdfPages = pdfPages,
                pageCount = resource.pageCount,
            ),
        )
    }

    private fun AppErrorKind.isRecoverableReaderFailure(): Boolean = this in setOf(
        AppErrorKind.NetworkUnavailable,
        AppErrorKind.Timeout,
        AppErrorKind.RateLimited,
        AppErrorKind.ServiceUnavailable,
        AppErrorKind.ServerFailure,
        AppErrorKind.TlsFailure,
        AppErrorKind.Unauthorized,
    )

    private fun encodePathSegment(value: String): String = buildString {
        value.encodeToByteArray().forEach { byte ->
            val unsigned = byte.toInt() and 0xff
            val character = unsigned.toChar()
            if (character.isLetterOrDigit() || character in setOf('-', '_', '.', '~')) append(character)
            else append('%').append(HEX[unsigned ushr 4]).append(HEX[unsigned and 0x0f])
        }
    }

    private companion object {
        const val READER_SERVER_SCHEMA_VERSION = 4
        const val HEX = "0123456789ABCDEF"
    }
}

private val ReaderFormat.wireReaderType: String
    get() = when (this) {
        ReaderFormat.Epub, ReaderFormat.Mobi, ReaderFormat.Text -> "reflowable"
        ReaderFormat.Comic -> "comic"
        ReaderFormat.Pdf -> "pdf"
        ReaderFormat.Audio -> "audio"
    }

private fun String.isSafeReaderMediaApiPath(): Boolean =
    startsWith("/api/") && !contains('#') && !contains('?') && !contains("//") &&
        split('/').none { it == "." || it == ".." } &&
        (matches(Regex("^/api/assets/[^/?#]+$")) ||
            matches(Regex("^/api/resources/[^/?#]+/asset$")))

private fun ReaderSourceFormat.readerTypeWire(): String = readerFormat.wireReaderType

private fun ReaderBootstrapResourceWire.hasExactFormatAndMorphology(): Boolean =
    ReaderSourceFormat.entries.any { sourceFormat ->
        format == sourceFormat.fileKind && readerType == sourceFormat.readerTypeWire()
    }

@Serializable
private data class ReaderBootstrapWire(
    val schemaVersion: Int,
    val userId: String,
    val readerType: String,
    val sourceFormat: String,
    val book: ReaderBootstrapBookWire,
    val resource: ReaderBootstrapResourceWire,
    val availableResources: List<ReaderBootstrapResourceWire>,
    val assets: List<ReaderBootstrapAssetWire>,
    val units: List<ReaderBootstrapUnitWire>,
    val resourceUrl: String,
    val capabilities: JsonObject,
    val publication: ReaderPublicationAccessWire? = null,
    val progressSnapshot: JsonObject? = null,
)

@Serializable
private data class ReaderBootstrapResourceWire(
    val id: String,
    val bookId: String,
    val sourceNodeId: String,
    val title: String,
    val resourceIndex: Double? = null,
    val sortOrder: Int,
    val format: String,
    val readerType: String,
    val pageCount: Int? = null,
    val chapterCount: Int? = null,
    val durationMs: Long? = null,
    val trackCount: Int? = null,
    val progress: Double = 0.0,
    val resourceCompleted: Boolean = false,
    val lastReadAt: String? = null,
)

@Serializable
private data class ReaderBootstrapAssetWire(
    val id: String,
    val title: String,
    val resourceId: String,
    val sourceNodeId: String,
    val role: String,
    val mimeType: String,
    val sizeBytes: Long,
    val durationMs: Long? = null,
    val discNumber: Int? = null,
    val trackNumber: Int? = null,
    val sortOrder: Int,
    val url: String,
    val codec: String? = null,
)

@Serializable
private data class ReaderBootstrapUnitWire(
    val id: String? = null,
    val index: Int? = null,
    val title: String? = null,
    val href: String? = null,
    val assetId: String? = null,
    val startMs: Long? = null,
    val endMs: Long? = null,
    val durationMs: Long? = null,
    val metadata: JsonObject = JsonObject(emptyMap()),
) {
    fun isStructurallyValid(): Boolean =
        !id.isNullOrBlank() && index != null && index >= 0 && title != null &&
            startMs?.let { it >= 0 } != false &&
            endMs?.let { it >= 0 } != false &&
            durationMs?.let { it >= 0 } != false

    fun pageIndexOrNull(): Int? {
        val value = metadata["pageIndex"] ?: return null
        val primitive = value as? JsonPrimitive
            ?: throw IllegalArgumentException("Reader comic page index must be an integer")
        return primitive.takeUnless(JsonPrimitive::isString)?.intOrNull
            ?: throw IllegalArgumentException("Reader comic page index must be an integer")
    }
}

@Serializable
private data class ReaderPublicationAccessWire(
    val kind: String? = null,
    val manifestUrl: String? = null,
    val positionsUrl: String? = null,
    val pageUrlTemplate: String? = null,
    val imageVariants: List<String> = emptyList(),
)

@Serializable
private data class ReaderComicManifestWire(
    val schemaVersion: Int,
    val revision: String,
    val kind: String,
    val resourceId: String,
    val sourceFormat: String,
    val pageCount: Int,
    val readingOrder: List<ReaderComicManifestPageWire>,
)

@Serializable
private data class ReaderComicManifestPageWire(
    val pageIndex: Int,
    val resourceHref: String,
    val title: String? = null,
    val mediaType: String,
    val width: Int? = null,
    val height: Int? = null,
    val sizeBytes: Long? = null,
)

private sealed interface ComicManifestLoad {
    data class Content(val value: ReaderComicManifestWire?) : ComicManifestLoad
    data class Failure(val code: String, val recoverable: Boolean) : ComicManifestLoad
}

private sealed interface ReaderBootstrapPreflight {
    data class Content(
        val sourceFormat: ReaderSourceFormat,
        val comicAccess: ReaderPublicationAccessWire?,
    ) : ReaderBootstrapPreflight

    data class Failure(val value: ReaderBootstrapResult.Failure) : ReaderBootstrapPreflight
}

@Serializable
private data class ReaderBootstrapBookWire(
    val id: String,
    val title: String,
    val author: String? = null,
    val coverUrl: String? = null,
)
