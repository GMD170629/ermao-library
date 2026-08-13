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
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.PublicationFingerprint
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.decodeFromJsonElement
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
                    json.decodeFromJsonElement(ReaderBootstrapWire.serializer(), result.value).toDomain(request)
                } catch (_: IllegalArgumentException) {
                    ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", false)
                }
            }
        } finally {
            client.close()
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
                maximumBytes = download.expectedSizeBytes,
                allowedMimeTypes = EPUB_MIME_TYPES,
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
                    if (result.value.mimeType !in EPUB_MIME_TYPES) {
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

    private fun ReaderBootstrapWire.toDomain(request: ReaderBootstrapRequest): ReaderBootstrapResult {
        if (schemaVersion != READER_SERVER_SCHEMA_VERSION || readerType != "reflowable" || sourceFormat != "epub") {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_UNSUPPORTED", recoverable = false)
        }
        if (userId != request.namespace.userId) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_USER_MISMATCH", recoverable = false)
        }
        if (volume.id != request.volumeId || mediaVersion.workId != book.id) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_IDENTITY_MISMATCH", recoverable = false)
        }
        val publicationFile = files.singleOrNull { file ->
            file.id.isNotBlank() &&
                file.kind.equals("EPUB", ignoreCase = true) &&
                file.mimeType.lowercase() in EPUB_MIME_TYPES &&
                file.sizeBytes > 0
        } ?: return ReaderBootstrapResult.Failure("READER_EPUB_FILE_MISSING", recoverable = false)
        val target = try {
            ReaderProgressSyncTarget(
                namespace = request.namespace,
                workId = book.id,
                volumeId = volume.id,
                sourceFormat = ReaderFormat.Epub,
            )
        } catch (_: IllegalArgumentException) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", false)
        }
        val exactPublicationFingerprint = try {
            PublicationFingerprint(
                originalFileHash = publicationFingerprint.originalFileHash,
                parser = publicationFingerprint.parser,
                normalization = publicationFingerprint.normalization,
            )
        } catch (_: IllegalArgumentException) {
            return ReaderBootstrapResult.Failure("READER_BOOTSTRAP_INVALID", false)
        }
        val remoteSnapshot = progressSnapshot?.let { snapshot ->
            val snapshotSchema = (snapshot["schemaVersion"] as? JsonPrimitive)?.longOrNull
            if (snapshotSchema != READER_SERVER_SCHEMA_VERSION.toLong()) {
                return ReaderBootstrapResult.Failure("READER_PROGRESS_SNAPSHOT_INVALID", false)
            }
            try {
                progressMapper.decodeSnapshot(snapshot, volume.id)
            } catch (_: IllegalArgumentException) {
                return ReaderBootstrapResult.Failure("READER_PROGRESS_SNAPSHOT_INVALID", false)
            }
        }
        return ReaderBootstrapResult.Content(
            ReaderBootstrap(
                target = target,
                publication = ReaderPublicationDownload(
                    profile = request.profile,
                    sourceId = volume.id,
                    displayTitle = volume.title.ifBlank { book.title },
                    workId = book.id,
                    volumeId = volume.id,
                    apiPath = fileUrl,
                    mimeType = publicationFile.mimeType.lowercase(),
                    expectedSizeBytes = publicationFile.sizeBytes,
                    expectedOriginalFileHash = publicationFile.contentHash,
                    publicationFingerprint = exactPublicationFingerprint,
                ),
                remoteSnapshot = remoteSnapshot,
                artifactVersion = exactPublicationFingerprint.stableKey,
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
        val EPUB_MIME_TYPES = setOf("application/epub+zip", "application/octet-stream")
    }
}

@Serializable
private data class ReaderBootstrapWire(
    val schemaVersion: Int,
    val userId: String,
    val readerType: String,
    val sourceFormat: String? = null,
    val publicationFingerprint: PublicationFingerprintWire,
    val book: ReaderBootstrapBookWire,
    val mediaVersion: ReaderBootstrapMediaVersionWire,
    val volume: ReaderBootstrapVolumeWire,
    val availableVolumes: List<JsonObject>,
    val files: List<ReaderBootstrapFileWire>,
    val units: List<JsonObject>,
    val fileUrl: String,
    val capabilities: JsonObject,
    val publication: ReaderPublicationAccessWire? = null,
    val progressSnapshot: JsonObject? = null,
)

@Serializable
private data class PublicationFingerprintWire(
    val originalFileHash: String,
    val parser: String,
    val normalization: String,
)

@Serializable
private data class ReaderPublicationAccessWire(
    val manifestUrl: String,
    val positionsUrl: String,
)

@Serializable
private data class ReaderBootstrapBookWire(val id: String, val title: String, val author: String? = null, val coverUrl: String? = null)

@Serializable
private data class ReaderBootstrapMediaVersionWire(val id: String, val workId: String, val mediaKind: String, val completed: Boolean)

@Serializable
private data class ReaderBootstrapVolumeWire(val id: String, val title: String)

@Serializable
private data class ReaderBootstrapFileWire(
    val id: String,
    val kind: String,
    val mimeType: String,
    val sizeBytes: Long,
    val url: String,
    val contentHash: String? = null,
    val durationMs: Long? = null,
    val discNumber: Int? = null,
    val trackNumber: Int? = null,
    val sortOrder: Int,
    val codec: String? = null,
)
