package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.domain.LocalReaderSource
import com.ermao.library.shared.modules.reader.domain.ReaderSource
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import com.ermao.library.shared.modules.reader.domain.RemoteComicReaderSource
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
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
) {
    init {
        require(sourceId == volumeId) { "Reader v4 source id must be its volume id" }
        require(displayTitle.isNotBlank())
        require(workId.isNotBlank())
        require(volumeId.isNotBlank())
        require(apiPath.startsWith("/api/") && !apiPath.contains('#'))
        require(sourceFormat.acceptsMimeType(mimeType)) { "Reader publication MIME type does not match its source format" }
        require(expectedSizeBytes > 0)
    }
}

data class ReaderBootstrap(
    val target: ReaderProgressSyncTarget,
    val publication: ReaderPublicationDownload,
    val remoteSnapshot: ReaderProgressSnapshotV4?,
    /** Canonical Reader v4 navigation units. Native publications must never replace this list. */
    val units: List<ReaderNavigationUnit> = emptyList(),
    val comicPages: List<ReaderComicPage> = emptyList(),
    val comicAccess: ReaderComicAccess? = null,
    val pdfPages: List<ReaderPdfPage> = emptyList(),
    val pageCount: Int? = null,
) {
    init {
        require(remoteSnapshot == null || remoteSnapshot.sourceId == target.volumeId) {
            "Reader bootstrap snapshot belongs to another volume"
        }
        require(units == units.sortedBy(ReaderNavigationUnit::index)) {
            "Reader navigation units are not in canonical order"
        }
        require(units.map(ReaderNavigationUnit::id).distinct().size == units.size) {
            "Reader navigation unit ids are not unique"
        }
        require(units.map(ReaderNavigationUnit::index).distinct().size == units.size) {
            "Reader navigation unit indexes are not unique"
        }
        require(comicPages.isEmpty() || publication.originalSourceFormat.isComic)
        require((comicAccess == null) == comicPages.isEmpty())
        require(pdfPages.isEmpty() || publication.sourceFormat == ReaderSourceFormat.Pdf)
        require(pageCount == null || pageCount > 0) { "Reader page count must be positive" }
        require(comicPages.map(ReaderComicPage::pageIndex) == comicPages.indices.toList()) {
            "Comic pages are not canonical and contiguous"
        }
        require(pdfPages.map(ReaderPdfPage::pageIndex) == pdfPages.indices.toList()) {
            "PDF pages are not canonical and contiguous"
        }
    }

}

data class ReaderNavigationUnit(
    val id: String,
    val index: Int,
    val title: String,
    val href: String? = null,
    val fileId: String? = null,
    val startMs: Long? = null,
    val endMs: Long? = null,
    val durationMs: Long? = null,
) {
    init {
        require(id.isNotBlank())
        require(index >= 0)
        require(title.isNotBlank())
        require(href == null || href.isNotBlank())
        require(startMs == null || startMs >= 0)
        require(endMs == null || endMs >= 0)
        require(durationMs == null || durationMs >= 0)
    }
}

data class ReaderComicAccess(
    val manifestApiPath: String,
    val pageApiPathTemplate: String,
    val imageVariants: Set<String>,
) {
    init {
        require(manifestApiPath.startsWith("/api/") && '#' !in manifestApiPath)
        require(pageApiPathTemplate.startsWith("/api/") && "{pageIndex}" in pageApiPathTemplate)
        require(imageVariants == setOf("original", "data-saver"))
    }
}

data class ReaderPdfPage(val pageIndex: Int, val title: String) {
    init {
        require(pageIndex >= 0)
        require(title.isNotBlank())
    }
}

data class ReaderComicPage(
    val pageIndex: Int,
    val resourceHref: String,
    val mediaType: String,
    val width: Int? = null,
    val height: Int? = null,
    val title: String? = null,
) {
    init {
        require(pageIndex >= 0)
        require(resourceHref.isNotBlank() && !resourceHref.startsWith('/') && '\\' !in resourceHref)
        require(resourceHref.split('/').none { it.isBlank() || it == "." || it == ".." })
        require(mediaType in setOf("image/jpeg", "image/png", "image/gif", "image/webp"))
        require(width == null || width > 0)
        require(height == null || height > 0)
        require(title == null || title.isNotBlank())
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

fun interface LocalReaderSourceResolver {
    suspend fun resolve(download: ReaderPublicationDownload): LocalReaderSource?
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
    private val localSourceResolver: LocalReaderSourceResolver? = null,
    private val nativePdfiumRangeV1: Boolean = false,
) {
    suspend fun execute(request: ReaderBootstrapRequest): ReaderPublicationBootstrapResult =
        when (val bootstrap = bootstrapGateway.load(request)) {
            is ReaderBootstrapResult.Failure -> ReaderPublicationBootstrapResult.Failure(
                bootstrap.failureCode,
                bootstrap.recoverable,
            )
            is ReaderBootstrapResult.Content -> openPublication(request, bootstrap.value)
        }

    private suspend fun openPublication(
        request: ReaderBootstrapRequest,
        bootstrap: ReaderBootstrap,
    ): ReaderPublicationBootstrapResult {
        val publication = bootstrap.publication
        localSourceResolver?.resolve(publication)?.let { local ->
            return ReaderPublicationBootstrapResult.Content(local, bootstrap)
        }
        if (nativePdfiumRangeV1 && publication.sourceFormat == ReaderSourceFormat.Pdf) {
            return ReaderPublicationBootstrapResult.Content(
                RemoteByteRangeReaderSource(
                    sourceId = publication.sourceId,
                    displayTitle = publication.displayTitle,
                    workId = publication.workId,
                    volumeId = publication.volumeId,
                    namespace = request.namespace,
                    apiPath = publication.apiPath,
                    expectedSizeBytes = publication.expectedSizeBytes,
                ),
                bootstrap,
            )
        }
        if (publication.originalSourceFormat.isComic) {
            val access = bootstrap.comicAccess
                ?: return ReaderPublicationBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
            return ReaderPublicationBootstrapResult.Content(
                RemoteComicReaderSource(
                    sourceId = publication.sourceId,
                    displayTitle = publication.displayTitle,
                    workId = publication.workId,
                    volumeId = publication.volumeId,
                    namespace = request.namespace,
                    sourceFormat = publication.originalSourceFormat,
                    manifestApiPath = access.manifestApiPath,
                    pageApiPathTemplate = access.pageApiPathTemplate,
                    pages = bootstrap.comicPages.map {
                        com.ermao.library.shared.modules.reader.domain.RemoteComicPage(
                            pageIndex = it.pageIndex,
                            resourceHref = it.resourceHref,
                            mediaType = it.mediaType,
                            width = it.width,
                            height = it.height,
                        )
                    },
                ),
                bootstrap,
            )
        }
        return when (val downloaded = downloadPort.download(publication, sinkFactory)) {
            is PublicationDownloadResult.Failure -> ReaderPublicationBootstrapResult.Failure(
                downloaded.failureCode,
                downloaded.recoverable,
            )
            is PublicationDownloadResult.Content -> ReaderPublicationBootstrapResult.Content(
                downloaded.source,
                bootstrap,
            )
        }
    }
}

sealed interface ReaderPublicationBootstrapResult {
    data class Content(
        val source: ReaderSource,
        val bootstrap: ReaderBootstrap,
    ) : ReaderPublicationBootstrapResult

    data class Failure(val failureCode: String, val recoverable: Boolean) : ReaderPublicationBootstrapResult
}
