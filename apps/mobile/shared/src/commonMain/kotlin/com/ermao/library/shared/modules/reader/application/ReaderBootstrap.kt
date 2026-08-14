package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.domain.PublicationFingerprint
import com.ermao.library.shared.modules.servers.domain.ServerProfile

data class ReaderBootstrapRequest(
    val profile: ServerProfile,
    val namespace: ReaderSyncNamespace,
    val volumeId: String,
) {
    init {
        require(profile.serverIdentity == namespace.serverIdentity)
        require(volumeId.isNotBlank())
    }
}

data class ReaderPublicationDownload(
    val profile: ServerProfile,
    val sourceId: String,
    val displayTitle: String,
    val workId: String,
    val volumeId: String,
    val apiPath: String,
    /** Original library format; retained for metadata and compatibility. */
    val originalSourceFormat: ReaderSourceFormat,
    /** Format of the bytes opened by the local reader. */
    val sourceFormat: ReaderSourceFormat,
    val mimeType: String,
    val expectedSizeBytes: Long,
    val expectedContentHash: String?,
    val publicationFingerprint: PublicationFingerprint,
) {
    init {
        require(sourceId == volumeId) { "Reader v4 source id must be its volume id" }
        require(displayTitle.isNotBlank())
        require(workId.isNotBlank())
        require(volumeId.isNotBlank())
        require(apiPath.startsWith("/api/") && !apiPath.contains('#'))
        require(sourceFormat.acceptsMimeType(mimeType)) { "Reader publication MIME type does not match its source format" }
        require(expectedSizeBytes > 0)
        require(expectedContentHash == null || expectedContentHash.matches(SHA256_PATTERN))
    }

    private companion object {
        val SHA256_PATTERN = Regex("^sha256:[0-9a-fA-F]{64}$")
    }
}

data class ReaderBootstrap(
    val target: ReaderProgressSyncTarget,
    val publication: ReaderPublicationDownload,
    val remoteSnapshot: ReaderProgressSnapshotV4?,
    /** Download artifact version from bootstrap; never part of a progress PUT. */
    val artifactVersion: String,
    val comicPages: List<ReaderComicPage> = emptyList(),
    val pageCount: Int? = null,
) {
    init {
        require(artifactVersion.matches(SHA256_PATTERN)) { "Reader artifact version must be a SHA-256 key" }
        require(remoteSnapshot == null || remoteSnapshot.sourceId == target.volumeId) {
            "Reader bootstrap snapshot belongs to another volume"
        }
        require(comicPages.isEmpty() || publication.sourceFormat == ReaderSourceFormat.Cbz)
        require(pageCount == null || pageCount > 0) { "Reader page count must be positive" }
        require(comicPages.map(ReaderComicPage::pageIndex) == comicPages.indices.toList()) {
            "Comic pages are not canonical and contiguous"
        }
    }

    private companion object {
        val SHA256_PATTERN = Regex("^sha256:[0-9a-f]{64}$")
    }
}

data class ReaderComicPage(
    val pageIndex: Int,
    val resourceHref: String,
    val mediaType: String,
    val width: Int? = null,
    val height: Int? = null,
) {
    init {
        require(pageIndex >= 0)
        require(resourceHref.isNotBlank() && !resourceHref.startsWith('/') && '\\' !in resourceHref)
        require(resourceHref.split('/').none { it.isBlank() || it == "." || it == ".." })
        require(mediaType in setOf("image/jpeg", "image/png", "image/gif", "image/webp"))
        require(width == null || width > 0)
        require(height == null || height > 0)
    }
}

sealed interface ReaderBootstrapResult {
    data class Content(val value: ReaderBootstrap) : ReaderBootstrapResult
    data class Failure(val failureCode: String, val recoverable: Boolean) : ReaderBootstrapResult {
        init {
            require(failureCode.isNotBlank())
        }
    }
}

fun interface ReaderBootstrapGateway {
    suspend fun load(request: ReaderBootstrapRequest): ReaderBootstrapResult
}

interface PublicationDownloadSink {
    /** Implementations consume the bytes before returning and never retain the mutable buffer. */
    suspend fun write(bytes: ByteArray, count: Int)
    suspend fun commit(): com.ermao.library.shared.modules.reader.domain.ReaderSource
    suspend fun abort()
}

fun interface PublicationDownloadSinkFactory {
    suspend fun open(download: ReaderPublicationDownload): PublicationDownloadSink
}

sealed interface PublicationDownloadResult {
    data class Content(val source: com.ermao.library.shared.modules.reader.domain.ReaderSource) :
        PublicationDownloadResult

    data class Failure(val failureCode: String, val recoverable: Boolean) : PublicationDownloadResult {
        init {
            require(failureCode.isNotBlank())
        }
    }
}

fun interface PublicationDownloadPort {
    suspend fun download(
        download: ReaderPublicationDownload,
        sinkFactory: PublicationDownloadSinkFactory,
    ): PublicationDownloadResult
}

/** Single authenticated Reader v4 gateway used by native composition roots. */
interface ReaderServerGateway : ReaderBootstrapGateway, PublicationDownloadPort

class BootstrapReaderPublication(
    private val bootstrapGateway: ReaderBootstrapGateway,
    private val downloadPort: PublicationDownloadPort,
    private val sinkFactory: PublicationDownloadSinkFactory,
) {
    suspend fun execute(request: ReaderBootstrapRequest): ReaderPublicationBootstrapResult =
        when (val bootstrap = bootstrapGateway.load(request)) {
            is ReaderBootstrapResult.Failure -> ReaderPublicationBootstrapResult.Failure(
                bootstrap.failureCode,
                bootstrap.recoverable,
            )
            is ReaderBootstrapResult.Content -> when (
                val downloaded = downloadPort.download(bootstrap.value.publication, sinkFactory)
            ) {
                is PublicationDownloadResult.Failure -> ReaderPublicationBootstrapResult.Failure(
                    downloaded.failureCode,
                    downloaded.recoverable,
                )
                is PublicationDownloadResult.Content -> ReaderPublicationBootstrapResult.Content(
                    downloaded.source,
                    bootstrap.value,
                )
            }
        }
}

sealed interface ReaderPublicationBootstrapResult {
    data class Content(
        val source: com.ermao.library.shared.modules.reader.domain.ReaderSource,
        val bootstrap: ReaderBootstrap,
    ) : ReaderPublicationBootstrapResult

    data class Failure(val failureCode: String, val recoverable: Boolean) : ReaderPublicationBootstrapResult
}
