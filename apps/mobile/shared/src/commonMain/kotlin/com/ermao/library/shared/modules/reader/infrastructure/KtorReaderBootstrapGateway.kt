package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.reader.application.PublicationDownloadPort
import com.ermao.library.shared.modules.reader.application.PublicationDownloadResult
import com.ermao.library.shared.modules.reader.application.PublicationDownloadSinkFactory
import com.ermao.library.shared.modules.reader.application.ReaderBootstrap
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapGateway
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult
import com.ermao.library.shared.modules.reader.application.ReaderComicAccess
import com.ermao.library.shared.modules.reader.application.ReaderComicPage
import com.ermao.library.shared.modules.reader.application.ReaderNavigationUnit
import com.ermao.library.shared.modules.reader.application.ReaderPdfPage
import com.ermao.library.shared.modules.reader.application.ReaderPublicationDownload
import com.ermao.library.shared.modules.reader.application.ReaderRemotePublicationAccess
import com.ermao.library.shared.modules.reader.application.ReaderServerGateway
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
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
) : ReaderServerGateway {
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
                    when (val manifest = loadComicManifest(client, bootstrap)) {
                        is ComicManifestLoad.Failure -> ReaderBootstrapResult.Failure(
                            manifest.code,
                            manifest.recoverable,
                        )
                        is ComicManifestLoad.Content -> bootstrap.toDomain(request, manifest.value)
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
        bootstrap: ReaderBootstrapWire,
    ): ComicManifestLoad {
        if (bootstrap.readerType != "comic") return ComicManifestLoad.Content(null)
        val access = bootstrap.publication
            ?: return ComicManifestLoad.Failure("READER_COMIC_MANIFEST_INVALID", false)
        val expectedPath = "/api/reader/v4/resources/${encodePathSegment(bootstrap.resource.id)}/comic/manifest"
        if (access.kind != "comic" || access.manifestUrl != expectedPath) {
            return ComicManifestLoad.Failure("READER_COMIC_MANIFEST_INVALID", false)
        }
        return when (val result = client.execute(
            ApiRequest(ApiMethod.Get, access.manifestUrl, JsonObject.serializer()),
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

    override suspend fun download(
        download: ReaderPublicationDownload,
        sinkFactory: PublicationDownloadSinkFactory,
    ): PublicationDownloadResult {
        val sink = try {
            sinkFactory.open(download)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            return PublicationDownloadResult.Failure("PUBLICATION_SINK_OPEN_FAILED", recoverable = false)
        }
        val client = createClient(download.profile)
        return try {
            when (val result = client.streamAuthenticatedDownload(
                apiPath = download.apiPath,
                maximumBytes = MAXIMUM_PUBLICATION_DOWNLOAD_BYTES,
                allowedMimeTypes = download.sourceFormat.allowedMimeTypes,
                writeChunk = sink::write,
            )) {
                is ApiResult.Failure -> {
                    sink.abort()
                    PublicationDownloadResult.Failure(
                        result.error.code,
                        result.error.kind.isRecoverableReaderFailure(),
                    )
                }
                is ApiResult.Success -> {
                    if (!download.sourceFormat.acceptsMimeType(result.value.mimeType)) {
                        sink.abort()
                        PublicationDownloadResult.Failure("DOWNLOAD_CONTENT_TYPE_INVALID", false)
                    } else {
                        PublicationDownloadResult.Content(sink.commit())
                    }
                }
            }
        } catch (cancelled: CancellationException) {
            sink.abort()
            throw cancelled
        } catch (_: Throwable) {
            sink.abort()
            PublicationDownloadResult.Failure("PUBLICATION_DOWNLOAD_FAILED", recoverable = true)
        } finally {
            client.close()
        }
    }

    private fun ReaderBootstrapWire.toDomain(
        request: ReaderBootstrapRequest,
        comicManifest: ReaderComicManifestWire?,
    ): ReaderBootstrapResult {
        val exactSourceFormat = ReaderSourceFormat.fromWireValue(sourceFormat)
        if (schemaVersion != READER_SERVER_SCHEMA_VERSION || exactSourceFormat == null ||
            readerType != exactSourceFormat.readerFormat.wireReaderType
        ) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_UNSUPPORTED", recoverable = false)
        }
        if (userId != request.namespace.userId) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_USER_MISMATCH", recoverable = false)
        }
        if (resource.id != request.resourceId || resource.bookId != book.id) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_IDENTITY_MISMATCH", recoverable = false)
        }
        if (!resource.format.equals(exactSourceFormat.wireValue, ignoreCase = true) ||
            !resource.readerType.equals(readerType, ignoreCase = true)
        ) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", recoverable = false)
        }
        if (availableResources.any { it.bookId != book.id } ||
            assets.any { it.resourceId != resource.id } ||
            units.any { it.assetId != null && assets.none { asset -> asset.id == it.assetId } }
        ) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_IDENTITY_MISMATCH", recoverable = false)
        }
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
        val comicAccess = publication?.takeIf { exactSourceFormat.isComic }?.let { access ->
            if (access.kind != "comic" || access.positionsUrl != null ||
                access.manifestUrl != "/api/reader/v4/resources/${resource.id}/comic/manifest" ||
                access.pageUrlTemplate != "/api/reader/v4/resources/${resource.id}/comic/pages/{pageIndex}" ||
                access.imageVariants != listOf("original", "data-saver")
            ) {
                return ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
            }
            val artifact = access.downloadArtifact
            if (exactSourceFormat == ReaderSourceFormat.ImageDir) {
                // IMAGE_DIR is a server-owned directory. It has canonical online pages but no
                // original archive to download; never synthesize a ZIP for native clients.
                if (artifact != null) {
                    return ReaderBootstrapResult.Failure("READER_COMIC_ARCHIVE_INVALID", false)
                }
            } else {
                if (artifact == null || artifact.url != "/api/reader/v4/resources/${resource.id}/comic/archive" ||
                    artifact.sourceFormat != exactSourceFormat.wireValue ||
                    artifact.sizeBytes <= 0 ||
                    !exactSourceFormat.acceptsMimeType(artifact.mimeType)
                ) {
                    return ReaderBootstrapResult.Failure("READER_COMIC_ARCHIVE_INVALID", false)
                }
            }
            ReaderComicAccess(
                manifestApiPath = access.manifestUrl,
                pageApiPathTemplate = access.pageUrlTemplate,
                imageVariants = access.imageVariants.toSet(),
            )
        } ?: if (exactSourceFormat.isComic) {
            return ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
        } else null
        val comicPages = if (exactSourceFormat.isComic) {
            val manifest = comicManifest
                ?: return ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
            try {
                require(
                    manifest.schemaVersion == 1 && manifest.kind == "comic" &&
                        manifest.resourceId == resource.id &&
                        manifest.sourceFormat == exactSourceFormat.wireValue &&
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
        // A non-directory resource has one downloadable original Asset. IMAGE_DIR is different:
        // its first PAGE may be the bootstrap's primary Asset, but that PAGE must never be
        // advertised as the whole publication. The downloads capability owns its page-set bundle.
        val apiPath = primaryAsset.url
        val mimeType = primaryAsset.mimeType.lowercase()
        val expectedSizeBytes = primaryAsset.sizeBytes
        if (!exactSourceFormat.acceptsMimeType(mimeType) || expectedSizeBytes <= 0) {
            return ReaderBootstrapResult.Failure("READER_PUBLICATION_ASSET_INVALID", false)
        }
        val displayTitle = resource.title.ifBlank { book.title }
        val downloadableOriginal = if (exactSourceFormat == ReaderSourceFormat.ImageDir) {
            null
        } else {
            ReaderPublicationDownload(
                profile = request.profile,
                resourceId = resource.id,
                displayTitle = displayTitle,
                bookId = book.id,
                assetId = primaryAsset.id,
                apiPath = apiPath,
                originalSourceFormat = exactSourceFormat,
                sourceFormat = exactSourceFormat,
                mimeType = mimeType,
                expectedSizeBytes = expectedSizeBytes,
            )
        }
        return ReaderBootstrapResult.Content(
            ReaderBootstrap(
                target = target,
                remoteAccess = ReaderRemotePublicationAccess(
                    resourceId = resource.id,
                    displayTitle = displayTitle,
                    bookId = book.id,
                    sourceFormat = exactSourceFormat,
                    assetId = primaryAsset.id.takeUnless { exactSourceFormat == ReaderSourceFormat.ImageDir },
                ),
                downloadableOriginal = downloadableOriginal,
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
        const val MAXIMUM_PUBLICATION_DOWNLOAD_BYTES = 512L * 1024 * 1024
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
    val downloadArtifact: ReaderComicDownloadArtifactWire? = null,
)

@Serializable
private data class ReaderComicDownloadArtifactWire(
    val url: String,
    val sourceFormat: String,
    val mimeType: String,
    val sizeBytes: Long,
)

@Serializable
private data class ReaderComicManifestWire(
    val schemaVersion: Int,
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

@Serializable
private data class ReaderBootstrapBookWire(
    val id: String,
    val title: String,
    val author: String? = null,
    val coverUrl: String? = null,
)
