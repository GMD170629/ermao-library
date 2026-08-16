package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiClient
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
import com.ermao.library.shared.modules.reader.application.ReaderPublicationDownload
import com.ermao.library.shared.modules.reader.application.ReaderServerGateway
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

class KtorReaderBootstrapGateway internal constructor(
    private val createClient: (com.ermao.library.shared.modules.servers.domain.ServerProfile) -> ApiClient,
    private val json: Json = Json { encodeDefaults = true; explicitNulls = false; ignoreUnknownKeys = true },
    private val progressMapper: ReaderServerWireMapper = ReaderServerWireMapper(),
) : ReaderServerGateway {
    constructor(clients: ApiClientFactory) : this(clients::create)

    override suspend fun load(request: ReaderBootstrapRequest): ReaderBootstrapResult {
        val client = createClient(request.profile)
        return try {
            when (val result = client.execute(
                ApiRequest(
                    ApiMethod.Get,
                    "/api/reader/v4/volumes/${encodePathSegment(request.volumeId)}/bootstrap",
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
        val expectedPath = "/api/reader/v4/volumes/${encodePathSegment(bootstrap.volume.id)}/comic/manifest"
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
            readerType != exactSourceFormat.readerType
        ) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_UNSUPPORTED", recoverable = false)
        }
        if (userId != request.namespace.userId) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_USER_MISMATCH", recoverable = false)
        }
        if (volume.id != request.volumeId || mediaVersion.workId != book.id) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_IDENTITY_MISMATCH", recoverable = false)
        }
        if (!volume.format.equals(exactSourceFormat.wireValue, ignoreCase = true)) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", recoverable = false)
        }
        if (fileUrl != "/api/volumes/${volume.id}/file") {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_IDENTITY_MISMATCH", recoverable = false)
        }
        val publicationFile = files
            .sortedWith(compareBy<ReaderBootstrapFileWire>({ it.sortOrder }, { it.id }))
            .firstOrNull { file ->
            file.id.isNotBlank() &&
                (file.kind.equals(exactSourceFormat.fileKind, ignoreCase = true) ||
                    exactSourceFormat.isComic && file.kind.equals("COMIC", ignoreCase = true)) &&
                exactSourceFormat.acceptsMimeType(file.mimeType) &&
                file.url.startsWith("/api/") && !file.url.contains('#') &&
                file.sizeBytes > 0
        } ?: return ReaderBootstrapResult.Failure("READER_PUBLICATION_FILE_MISSING", recoverable = false)
        val orderedUnits = units.asSequence()
            .filter(ReaderBootstrapUnitWire::isStructurallyValid)
            .sortedBy { requireNotNull(it.index) }
            .distinctBy { requireNotNull(it.id) }
            .distinctBy { requireNotNull(it.index) }
            .toList()
        val target = try {
            ReaderProgressSyncTarget(
                namespace = request.namespace,
                workId = book.id,
                volumeId = volume.id,
                sourceFormat = exactSourceFormat.readerFormat,
            )
        } catch (_: IllegalArgumentException) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", false)
        }
        val comicAccess = publication?.takeIf { exactSourceFormat.isComic }?.let { access ->
            val artifact = access.downloadArtifact
                ?: return ReaderBootstrapResult.Failure("READER_COMIC_ARCHIVE_INVALID", false)
            if (access.kind != "comic" || access.positionsUrl != null ||
                access.manifestUrl != "/api/reader/v4/volumes/${volume.id}/comic/manifest" ||
                access.pageUrlTemplate != "/api/reader/v4/volumes/${volume.id}/comic/pages/{pageIndex}" ||
                access.imageVariants != listOf("original", "data-saver") ||
                artifact.url != "/api/reader/v4/volumes/${volume.id}/comic/archive" ||
                artifact.sourceFormat != exactSourceFormat.wireValue ||
                artifact.sizeBytes <= 0 ||
                !exactSourceFormat.acceptsMimeType(artifact.mimeType)
            ) {
                return ReaderBootstrapResult.Failure("READER_COMIC_ARCHIVE_INVALID", false)
            }
            com.ermao.library.shared.modules.reader.application.ReaderComicAccess(
                manifestApiPath = access.manifestUrl,
                pageApiPathTemplate = access.pageUrlTemplate,
                imageVariants = access.imageVariants.toSet(),
            )
        }
        val comicPages = if (exactSourceFormat.isComic) {
            val manifest = comicManifest
                ?: return ReaderBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
            try {
                require(
                    manifest.schemaVersion == 1 && manifest.kind == "comic" &&
                        manifest.volumeId == volume.id &&
                        manifest.sourceFormat == exactSourceFormat.wireValue &&
                        manifest.pageCount == manifest.readingOrder.size && manifest.pageCount > 0
                )
                manifest.readingOrder.mapIndexed { index, page ->
                    require(page.pageIndex == index && page.resourceHref == "pages/$index")
                    val unitTitle = orderedUnits.firstOrNull { it.pageIndexOrNull() == index }?.title
                    com.ermao.library.shared.modules.reader.application.ReaderComicPage(
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
                com.ermao.library.shared.modules.reader.application.ReaderPdfPage(
                    pageIndex = index,
                    title = requireNotNull(unit.title).takeIf(String::isNotBlank) ?: "${index + 1}",
                )
            }
        } else emptyList()
        val remoteSnapshot = progressSnapshot?.let { snapshot -> runCatching {
            val snapshotSchema = (snapshot["schemaVersion"] as? JsonPrimitive)?.longOrNull
            require(snapshotSchema == READER_SERVER_SCHEMA_VERSION.toLong())
            progressMapper.decodeSnapshot(snapshot, volume.id)
        }.getOrNull() }
        val comicArtifact = publication?.downloadArtifact?.takeIf { exactSourceFormat.isComic }
        return ReaderBootstrapResult.Content(
            ReaderBootstrap(
                target = target,
                publication = ReaderPublicationDownload(
                    profile = request.profile,
                    sourceId = volume.id,
                    displayTitle = volume.title.ifBlank { book.title },
                    workId = book.id,
                    volumeId = volume.id,
                    apiPath = comicArtifact?.url ?: fileUrl,
                    originalSourceFormat = exactSourceFormat,
                    sourceFormat = exactSourceFormat,
                    mimeType = comicArtifact?.mimeType ?: publicationFile.mimeType.lowercase(),
                    expectedSizeBytes = comicArtifact?.sizeBytes ?: publicationFile.sizeBytes,
                ),
                remoteSnapshot = remoteSnapshot,
                units = orderedUnits.map { unit ->
                    com.ermao.library.shared.modules.reader.application.ReaderNavigationUnit(
                        id = requireNotNull(unit.id),
                        index = requireNotNull(unit.index),
                        title = requireNotNull(unit.title).trim().ifEmpty { requireNotNull(unit.id) },
                        href = unit.href?.trim()?.takeIf(String::isNotEmpty),
                        fileId = unit.fileId?.trim()?.takeIf(String::isNotEmpty),
                        startMs = unit.startMs,
                        endMs = unit.endMs,
                        durationMs = unit.durationMs,
                    )
                },
                comicPages = comicPages,
                comicAccess = comicAccess,
                pdfPages = pdfPages,
                pageCount = volume.pageCount,
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
            else {
                append('%')
                append(HEX[unsigned ushr 4])
                append(HEX[unsigned and 0x0f])
            }
        }
    }

    private companion object {
        const val READER_SERVER_SCHEMA_VERSION = 4
        const val HEX = "0123456789ABCDEF"
        const val MAXIMUM_PUBLICATION_DOWNLOAD_BYTES = 512L * 1024 * 1024
    }
}

private val ReaderSourceFormat.readerType: String
    get() = when (readerFormat) {
        com.ermao.library.shared.modules.reader.domain.ReaderFormat.Epub,
        com.ermao.library.shared.modules.reader.domain.ReaderFormat.Mobi,
        com.ermao.library.shared.modules.reader.domain.ReaderFormat.Text,
        -> "reflowable"
        com.ermao.library.shared.modules.reader.domain.ReaderFormat.Comic -> "comic"
        com.ermao.library.shared.modules.reader.domain.ReaderFormat.Pdf -> "pdf"
        com.ermao.library.shared.modules.reader.domain.ReaderFormat.Audio -> "audio"
    }

@Serializable
private data class ReaderBootstrapWire(
    val schemaVersion: Int,
    val userId: String,
    val readerType: String,
    val sourceFormat: String? = null,
    val book: ReaderBootstrapBookWire,
    val mediaVersion: ReaderBootstrapMediaVersionWire,
    val volume: ReaderBootstrapVolumeWire,
    val availableVolumes: List<JsonObject>,
    val files: List<ReaderBootstrapFileWire>,
    val units: List<ReaderBootstrapUnitWire>,
    val fileUrl: String,
    val capabilities: JsonObject,
    val publication: ReaderPublicationAccessWire? = null,
    val progressSnapshot: JsonObject? = null,
)

@Serializable
private data class ReaderBootstrapUnitWire(
    val id: String? = null,
    val index: Int? = null,
    val title: String? = null,
    val href: String? = null,
    val fileId: String? = null,
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

    fun pageNumberOrNull(): Int? {
        val value = metadata["pageNumber"] ?: return null
        val primitive = value as? JsonPrimitive
            ?: throw IllegalArgumentException("Reader PDF page number must be an integer")
        return primitive.takeUnless(JsonPrimitive::isString)?.intOrNull
            ?: throw IllegalArgumentException("Reader PDF page number must be an integer")
    }

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
    val volumeId: String,
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
private data class ReaderBootstrapBookWire(val id: String, val title: String, val author: String? = null, val coverUrl: String? = null)

@Serializable
private data class ReaderBootstrapMediaVersionWire(val id: String, val workId: String, val mediaKind: String, val completed: Boolean)

@Serializable
private data class ReaderBootstrapVolumeWire(
    val id: String,
    val title: String,
    val format: String,
    val pageCount: Int? = null,
)

@Serializable
private data class ReaderBootstrapFileWire(
    val id: String,
    val kind: String,
    val mimeType: String,
    val sizeBytes: Long,
    val url: String,
    val durationMs: Long? = null,
    val discNumber: Int? = null,
    val trackNumber: Int? = null,
    val sortOrder: Int,
    val codec: String? = null,
)
