package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.domain.readerErrorCodeForFailure
import com.ermao.library.shared.modules.reader.domain.ReaderSource
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import com.ermao.library.shared.modules.reader.domain.RemoteComicReaderSource
import com.ermao.library.shared.modules.reader.domain.RemoteReflowableReaderSource
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.servers.domain.ServerProfile

data class ReaderBootstrapRequest(
    val profile: ServerProfile,
    val namespace: ReaderSyncNamespace,
    val resourceId: String,
) {
    init {
        require(profile.serverIdentity == namespace.serverIdentity)
        require(resourceId.isNotBlank())
    }
}

/** Identity of an online publication; never an offline transfer request. */
data class ReaderRemotePublicationAccess(
    val resourceId: String,
    val displayTitle: String,
    val bookId: String,
    val sourceFormat: ReaderSourceFormat,
    val assetId: String? = null,
) {
    init {
        require(resourceId.isNotBlank())
        require(displayTitle.isNotBlank())
        require(bookId.isNotBlank())
        require(assetId == null || assetId.isNotBlank())
        require(sourceFormat == ReaderSourceFormat.ImageDir || assetId != null) {
            "A single-file Reader source must retain its original Asset identity"
        }
        require(sourceFormat != ReaderSourceFormat.ImageDir || assetId == null) {
            "IMAGE_DIR must not advertise one PAGE Asset as the publication"
        }
    }
}

data class ReaderBootstrap(
    val target: ReaderProgressSyncTarget,
    val remoteAccess: ReaderRemotePublicationAccess,
    val publicationAccess: ReaderPublicationAccess? = null,
    val pdfAccess: ReaderPdfAccess? = null,
    val remoteSnapshot: ReaderProgressSnapshotV4?,
    /** Canonical Reader v4 navigation units. Native publications must never replace this list. */
    val units: List<ReaderNavigationUnit> = emptyList(),
    val comicPages: List<ReaderComicPage> = emptyList(),
    val comicAccess: ReaderComicAccess? = null,
    val pdfPages: List<ReaderPdfPage> = emptyList(),
    val pageCount: Int? = null,
) {
    init {
        require(remoteSnapshot == null || remoteSnapshot.resourceId == target.resourceId) {
            "Reader bootstrap snapshot belongs to another resource"
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
        require(target.resourceId == remoteAccess.resourceId)
        require(target.bookId == remoteAccess.bookId)
        require(target.sourceFormat == remoteAccess.sourceFormat.readerFormat)
        require(comicPages.isEmpty() || remoteAccess.sourceFormat.isComic)
        require((comicAccess == null) == comicPages.isEmpty())
        require(pdfPages.isEmpty() || remoteAccess.sourceFormat == ReaderSourceFormat.Pdf)
        require((publicationAccess != null) == (remoteAccess.sourceFormat.readerFormat in
            setOf(com.ermao.library.shared.modules.reader.domain.ReaderFormat.Epub,
                com.ermao.library.shared.modules.reader.domain.ReaderFormat.Mobi,
                com.ermao.library.shared.modules.reader.domain.ReaderFormat.Text)))
        require((pdfAccess != null) == (remoteAccess.sourceFormat == ReaderSourceFormat.Pdf))
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
    val assetId: String? = null,
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

        val readerErrorCode: ReaderErrorCode = readerErrorCodeForFailure(failureCode, recoverable)
    }
}

fun interface ReaderBootstrapGateway {
    suspend fun load(request: ReaderBootstrapRequest): ReaderBootstrapResult
}

data class ReaderPublicationAccess(val manifestApiPath: String, val positionsApiPath: String) {
    init {
        require(manifestApiPath.startsWith("/api/") && '#' !in manifestApiPath)
        require(positionsApiPath.startsWith("/api/") && '#' !in positionsApiPath)
    }
}

data class ReaderPdfAccess(val apiPath: String, val expectedSizeBytes: Long) {
    init {
        require(apiPath.startsWith("/api/") && '#' !in apiPath)
        require(expectedSizeBytes > 0)
    }
}

class BootstrapReaderPublication(
    private val bootstrapGateway: ReaderBootstrapGateway,
) {
    suspend fun execute(request: ReaderBootstrapRequest): ReaderPublicationBootstrapResult =
        when (val bootstrap = bootstrapGateway.load(request)) {
            is ReaderBootstrapResult.Failure -> ReaderPublicationBootstrapResult.Failure(
                bootstrap.failureCode,
                bootstrap.recoverable,
            )
            is ReaderBootstrapResult.Content -> resolve(request, bootstrap.value)
        }

    fun resolve(
        request: ReaderBootstrapRequest,
        bootstrap: ReaderBootstrap,
    ): ReaderPublicationBootstrapResult {
        val access = bootstrap.remoteAccess
        if (access.sourceFormat == ReaderSourceFormat.Pdf) {
            val pdf = requireNotNull(bootstrap.pdfAccess)
            return ReaderPublicationBootstrapResult.Content(
                RemoteByteRangeReaderSource(
                    resourceId = access.resourceId,
                    displayTitle = access.displayTitle,
                    bookId = access.bookId,
                    assetId = requireNotNull(access.assetId),
                    namespace = request.namespace,
                    apiPath = pdf.apiPath,
                    expectedSizeBytes = pdf.expectedSizeBytes,
                ), bootstrap,
            )
        }
        if (access.sourceFormat.isComic) {
            val access = bootstrap.comicAccess
                ?: return ReaderPublicationBootstrapResult.Failure("READER_COMIC_MANIFEST_INVALID", false)
            return ReaderPublicationBootstrapResult.Content(
                RemoteComicReaderSource(
                    resourceId = bootstrap.remoteAccess.resourceId,
                    displayTitle = bootstrap.remoteAccess.displayTitle,
                    bookId = bootstrap.remoteAccess.bookId,
                    assetId = bootstrap.remoteAccess.assetId,
                    namespace = request.namespace,
                    sourceFormat = bootstrap.remoteAccess.sourceFormat,
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
        val publication = bootstrap.publicationAccess
            ?: return ReaderPublicationBootstrapResult.Failure("READER_PUBLICATION_UNSUPPORTED", false)
        return ReaderPublicationBootstrapResult.Content(
            RemoteReflowableReaderSource(
                resourceId = access.resourceId,
                displayTitle = access.displayTitle,
                bookId = access.bookId,
                assetId = requireNotNull(access.assetId),
                sourceFormat = access.sourceFormat,
                namespace = request.namespace,
                manifestApiPath = publication.manifestApiPath,
                positionsApiPath = publication.positionsApiPath,
            ), bootstrap,
        )
    }
}

sealed interface ReaderPublicationBootstrapResult {
    data class Content(
        val source: ReaderSource,
        val bootstrap: ReaderBootstrap,
    ) : ReaderPublicationBootstrapResult

    data class Failure(val failureCode: String, val recoverable: Boolean) : ReaderPublicationBootstrapResult {
        init {
            require(failureCode.isNotBlank())
        }

        val readerErrorCode: ReaderErrorCode = readerErrorCodeForFailure(failureCode, recoverable)
    }
}
