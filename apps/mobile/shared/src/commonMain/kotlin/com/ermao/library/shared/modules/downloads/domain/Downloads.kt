package com.ermao.library.shared.modules.downloads.domain

data class DownloadNamespace(
    val serverIdentity: String,
    val userId: String,
    val authorizationVersion: Long,
) {
    init {
        require(serverIdentity.isNotBlank())
        require(userId.isNotBlank())
        require(authorizationVersion > 0)
    }

    val stableKey: String = listOf(serverIdentity, userId, authorizationVersion.toString())
        .joinToString(":") { it.encodeForKey() }
}

enum class DownloadReaderType { Reflowable, Pdf, Comic, Audio }

data class DownloadSource(
    val apiPath: String,
    val mimeType: String,
    val totalBytes: Long,
) {
    init {
        require(apiPath.isSafeMediaApiPath())
        require(mimeType.isNotBlank())
        require(totalBytes > 0)
    }
}

/** Stable completed-artifact identity: Book -> Resource -> Asset. */
data class DownloadIdentity(
    val namespace: DownloadNamespace,
    val bookId: String,
    val resourceId: String,
    val assetId: String,
) {
    init {
        require(bookId.isNotBlank())
        require(resourceId.isNotBlank())
        require(assetId.isNotBlank())
    }
}

data class DownloadDescriptor(
    val identity: DownloadIdentity,
    val bookTitle: String,
    val bookAuthor: String?,
    val coverApiPath: String?,
    val resourceTitle: String,
    val format: String,
    val readerType: DownloadReaderType,
    val source: DownloadSource,
    val resourceIndex: Double? = null,
    val resourceSortOrder: Int? = null,
    /** False when the server exposes only a streaming representation (for example IMAGE_DIR). */
    val isDownloadable: Boolean = true,
) {
    init {
        require(bookTitle.isNotBlank())
        require(resourceTitle.isNotBlank())
        require(format.isNotBlank())
        require(coverApiPath == null || coverApiPath.isSafeApiPath())
        require(resourceIndex == null || resourceIndex.isFinite())
        require(resourceSortOrder == null || resourceSortOrder >= 0)
    }
}

data class CompletedDownloadArtifact(
    val descriptor: DownloadDescriptor,
    val localReference: String,
    val verifiedBytes: Long,
    val completedAtEpochMillis: Long,
    val lastOpenedAtEpochMillis: Long? = null,
) {
    init {
        require(localReference.isNotBlank())
        require(verifiedBytes == descriptor.source.totalBytes)
        require(completedAtEpochMillis > 0)
        require(lastOpenedAtEpochMillis == null || lastOpenedAtEpochMillis > 0)
    }

    val identity: DownloadIdentity get() = descriptor.identity
}

enum class DownloadTaskStatus {
    Queued,
    Downloading,
    Paused,
    WaitingForWifi,
    InsufficientSpace,
    FailedRetryable,
    FailedTerminal,
    Completed,
    Cancelled,
}

data class DownloadTask(
    val id: String,
    val descriptor: DownloadDescriptor,
    val status: DownloadTaskStatus = DownloadTaskStatus.Queued,
    val transferredBytes: Long = 0,
    val failureCode: String? = null,
    val artifact: CompletedDownloadArtifact? = null,
) {
    init {
        require(id.isNotBlank())
        require(transferredBytes in 0..descriptor.source.totalBytes)
        require((status == DownloadTaskStatus.Completed) == (artifact != null))
        require(artifact == null || artifact.identity == descriptor.identity)
        require(failureCode == null || failureCode.isNotBlank())
    }
}

sealed interface DownloadTaskEvent {
    data object Start : DownloadTaskEvent
    data class BytesTransferred(val totalTransferredBytes: Long) : DownloadTaskEvent
    data object Pause : DownloadTaskEvent
    data object Resume : DownloadTaskEvent
    data object WaitForWifi : DownloadTaskEvent
    data object ReportInsufficientSpace : DownloadTaskEvent
    data class Fail(val code: String, val retryable: Boolean) : DownloadTaskEvent
    data class Complete(val artifact: CompletedDownloadArtifact) : DownloadTaskEvent
    data object Cancel : DownloadTaskEvent
}

fun DownloadTask.transition(event: DownloadTaskEvent): DownloadTask = when (event) {
    DownloadTaskEvent.Start -> {
        require(status == DownloadTaskStatus.Queued)
        copy(status = DownloadTaskStatus.Downloading, failureCode = null)
    }
    is DownloadTaskEvent.BytesTransferred -> {
        require(status == DownloadTaskStatus.Downloading)
        require(event.totalTransferredBytes in transferredBytes..descriptor.source.totalBytes)
        copy(transferredBytes = event.totalTransferredBytes)
    }
    DownloadTaskEvent.Pause -> {
        require(status == DownloadTaskStatus.Downloading)
        copy(status = DownloadTaskStatus.Paused)
    }
    DownloadTaskEvent.Resume -> {
        require(status in resumableStatuses)
        copy(status = DownloadTaskStatus.Downloading, failureCode = null)
    }
    DownloadTaskEvent.WaitForWifi -> {
        require(status in activeStatuses)
        copy(status = DownloadTaskStatus.WaitingForWifi)
    }
    DownloadTaskEvent.ReportInsufficientSpace -> {
        require(status in activeStatuses)
        copy(status = DownloadTaskStatus.InsufficientSpace, failureCode = "INSUFFICIENT_SPACE")
    }
    is DownloadTaskEvent.Fail -> {
        require(status in activeStatuses)
        require(event.code.isNotBlank())
        copy(
            status = if (event.retryable) DownloadTaskStatus.FailedRetryable else DownloadTaskStatus.FailedTerminal,
            failureCode = event.code,
        )
    }
    is DownloadTaskEvent.Complete -> {
        require(status == DownloadTaskStatus.Downloading)
        require(event.artifact.identity == descriptor.identity)
        copy(
            status = DownloadTaskStatus.Completed,
            transferredBytes = descriptor.source.totalBytes,
            failureCode = null,
            artifact = event.artifact,
        )
    }
    DownloadTaskEvent.Cancel -> {
        require(status !in terminalStatuses)
        copy(status = DownloadTaskStatus.Cancelled, artifact = null)
    }
}

data class DownloadedBook(
    val bookId: String,
    val title: String,
    val author: String?,
    val coverApiPath: String?,
    val resources: List<DownloadedResource>,
    val artifacts: List<CompletedDownloadArtifact>,
) {
    init {
        require(bookId.isNotBlank())
        require(title.isNotBlank())
        require(resources.isNotEmpty())
        require(artifacts.isNotEmpty())
        require(artifacts.all { it.identity.bookId == bookId })
        require(resources.flatMap(DownloadedResource::artifacts) == artifacts)
    }

    val totalBytes: Long = artifacts.sumOf { it.verifiedBytes }
    val lastOpenedAtEpochMillis: Long? = artifacts.mapNotNull { it.lastOpenedAtEpochMillis }.maxOrNull()
}

data class DownloadedResource(
    val resourceId: String,
    val title: String,
    val format: String,
    val readerType: DownloadReaderType,
    val resourceIndex: Double?,
    val resourceSortOrder: Int?,
    val artifacts: List<CompletedDownloadArtifact>,
) {
    init {
        require(resourceId.isNotBlank())
        require(title.isNotBlank())
        require(format.isNotBlank())
        require(artifacts.isNotEmpty())
        require(artifacts.all { it.identity.resourceId == resourceId })
    }

    val totalBytes: Long = artifacts.sumOf { it.verifiedBytes }
}

fun completedDownloadsByBook(
    namespace: DownloadNamespace,
    artifacts: List<CompletedDownloadArtifact>,
    query: String = "",
): List<DownloadedBook> {
    val normalizedQuery = query.trim().lowercase()
    return artifacts
        .asSequence()
        .filter { it.identity.namespace == namespace }
        .groupBy { it.identity.bookId }
        .values
        .map { bookArtifacts ->
            val resources = bookArtifacts
                .groupBy { it.identity.resourceId }
                .values
                .map { resourceArtifacts ->
                    val orderedAssets = resourceArtifacts.sortedWith(assetArtifactComparator)
                    val descriptor = orderedAssets.first().descriptor
                    DownloadedResource(
                        resourceId = descriptor.identity.resourceId,
                        title = descriptor.resourceTitle,
                        format = descriptor.format,
                        readerType = descriptor.readerType,
                        resourceIndex = descriptor.resourceIndex,
                        resourceSortOrder = descriptor.resourceSortOrder,
                        artifacts = orderedAssets,
                    )
                }
                .sortedWith(resourceComparator)
            val ordered = resources.flatMap(DownloadedResource::artifacts)
            val first = ordered.first().descriptor
            DownloadedBook(
                bookId = first.identity.bookId,
                title = first.bookTitle,
                author = first.bookAuthor,
                coverApiPath = first.coverApiPath,
                resources = resources,
                artifacts = ordered,
            )
        }
        .filter { book ->
            normalizedQuery.isEmpty() ||
                (listOfNotNull(book.title, book.author) + book.resources.map(DownloadedResource::title))
                    .any { normalizedQuery in it.lowercase() }
        }
        .sortedWith(compareByDescending<DownloadedBook> { it.lastOpenedAtEpochMillis ?: 0 }.thenBy { it.title.lowercase() })
        .toList()
}

private val assetArtifactComparator =
    compareBy<CompletedDownloadArtifact> { it.identity.assetId }

private val resourceComparator =
    compareBy<DownloadedResource> { it.resourceSortOrder ?: Int.MAX_VALUE }
        .thenBy { it.resourceIndex ?: Double.MAX_VALUE }
        .thenBy { it.title.lowercase() }
        .thenBy { it.resourceId }

private val activeStatuses = setOf(
    DownloadTaskStatus.Queued,
    DownloadTaskStatus.Downloading,
    DownloadTaskStatus.Paused,
    DownloadTaskStatus.WaitingForWifi,
    DownloadTaskStatus.InsufficientSpace,
    DownloadTaskStatus.FailedRetryable,
)
private val resumableStatuses = setOf(
    DownloadTaskStatus.Paused,
    DownloadTaskStatus.WaitingForWifi,
    DownloadTaskStatus.InsufficientSpace,
    DownloadTaskStatus.FailedRetryable,
)
private val terminalStatuses = setOf(
    DownloadTaskStatus.Completed,
    DownloadTaskStatus.Cancelled,
    DownloadTaskStatus.FailedTerminal,
)

private fun String.encodeForKey(): String = encodeToByteArray().joinToString("") { byte ->
    byte.toUByte().toString(16).padStart(2, '0')
}

internal fun String.isSafeMediaApiPath(): Boolean =
    isSafeApiPath() && (
        matches(Regex("^/api/assets/[^/?#]+$")) ||
            matches(Regex("^/api/resources/[^/?#]+/asset$"))
        )

internal fun String.isSafeApiPath(): Boolean =
    startsWith("/api/") && !contains('#') && !contains('?') && !contains("//") &&
        split('/').none { it == "." || it == ".." }
