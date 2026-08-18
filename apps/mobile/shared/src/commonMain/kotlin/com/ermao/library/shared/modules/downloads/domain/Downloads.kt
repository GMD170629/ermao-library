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

const val IMPLICIT_DOWNLOAD_VERSION_SOURCE_KEY = "__implicit__"

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

data class DownloadIdentity(
    val namespace: DownloadNamespace,
    val workId: String,
    val volumeId: String,
) {
    init {
        require(workId.isNotBlank())
        require(volumeId.isNotBlank())
    }
}

data class DownloadDescriptor(
    val identity: DownloadIdentity,
    val workTitle: String,
    val workAuthor: String?,
    val coverApiPath: String?,
    val volumeTitle: String,
    val format: String,
    val readerType: DownloadReaderType,
    val source: DownloadSource,
    val versionId: String,
    val versionSourceKey: String,
    val versionSourceName: String?,
    val versionCompleted: Boolean? = null,
    val volumeIndex: Double? = null,
    val volumeSortOrder: Int? = null,
) {
    init {
        require(workTitle.isNotBlank())
        require(volumeTitle.isNotBlank())
        require(format.isNotBlank())
        require(versionId.isNotBlank())
        require(versionSourceKey.isNotBlank())
        require(coverApiPath == null || coverApiPath.isSafeApiPath())
        require(volumeIndex == null || volumeIndex.isFinite())
        require(volumeSortOrder == null || volumeSortOrder >= 0)
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

data class DownloadedWork(
    val workId: String,
    val title: String,
    val author: String?,
    val coverApiPath: String?,
    val versions: List<DownloadedVersion>,
    val artifacts: List<CompletedDownloadArtifact>,
) {
    init {
        require(workId.isNotBlank())
        require(title.isNotBlank())
        require(versions.isNotEmpty())
        require(artifacts.isNotEmpty())
        require(artifacts.all { it.identity.workId == workId })
        require(versions.flatMap(DownloadedVersion::artifacts) == artifacts)
    }

    val totalBytes: Long = artifacts.sumOf { it.verifiedBytes }
    val lastOpenedAtEpochMillis: Long? = artifacts.mapNotNull { it.lastOpenedAtEpochMillis }.maxOrNull()
}

data class DownloadedVersion(
    val versionId: String,
    val sourceKey: String,
    val sourceName: String?,
    val isServerComplete: Boolean?,
    val artifacts: List<CompletedDownloadArtifact>,
) {
    init {
        require(versionId.isNotBlank())
        require(sourceKey.isNotBlank())
        require(artifacts.isNotEmpty())
        require(artifacts.all { it.descriptor.versionId == versionId })
    }

    val totalBytes: Long = artifacts.sumOf { it.verifiedBytes }
}

fun completedDownloadsByWork(
    namespace: DownloadNamespace,
    artifacts: List<CompletedDownloadArtifact>,
    query: String = "",
): List<DownloadedWork> {
    val normalizedQuery = query.trim().lowercase()
    return artifacts
        .asSequence()
        .filter { it.identity.namespace == namespace }
        .groupBy { it.identity.workId }
        .values
        .map { workArtifacts ->
            val versions = workArtifacts
                .groupBy { it.descriptor.versionId }
                .values
                .map { versionArtifacts ->
                    val orderedVolumes = versionArtifacts.sortedWith(volumeArtifactComparator)
                    val version = orderedVolumes.first().descriptor
                    DownloadedVersion(
                        versionId = version.versionId,
                        sourceKey = version.versionSourceKey,
                        sourceName = version.versionSourceName,
                        isServerComplete = version.versionCompleted,
                        artifacts = orderedVolumes,
                    )
                }
                .sortedWith(downloadedVersionComparator)
            val ordered = versions.flatMap(DownloadedVersion::artifacts)
            val first = ordered.first().descriptor
            DownloadedWork(
                workId = first.identity.workId,
                title = first.workTitle,
                author = first.workAuthor,
                coverApiPath = first.coverApiPath,
                versions = versions,
                artifacts = ordered,
            )
        }
        .filter { work ->
            normalizedQuery.isEmpty() || (
                listOfNotNull(work.title, work.author) + work.artifacts.map { it.descriptor.volumeTitle }
                )
                .any { normalizedQuery in it.lowercase() }
        }
        .sortedWith(compareByDescending<DownloadedWork> { it.lastOpenedAtEpochMillis ?: 0 }.thenBy { it.title.lowercase() })
        .toList()
}

private val volumeArtifactComparator =
    compareBy<CompletedDownloadArtifact> { it.descriptor.volumeSortOrder ?: Int.MAX_VALUE }
        .thenBy { it.descriptor.volumeIndex ?: Double.MAX_VALUE }
        .thenBy { it.descriptor.volumeTitle.lowercase() }
        .thenBy { it.identity.volumeId }

private val downloadedVersionComparator =
    compareBy<DownloadedVersion> { if (it.sourceKey == IMPLICIT_DOWNLOAD_VERSION_SOURCE_KEY) 0 else 1 }
        .thenBy(nullsLast(String.CASE_INSENSITIVE_ORDER)) { it.sourceName }
        .thenBy { it.sourceKey.lowercase() }
        .thenBy { it.versionId }

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
        matches(Regex("^/api/files/[^/?#]+$")) ||
            matches(Regex("^/api/volumes/[^/?#]+/file$")) ||
            matches(Regex("^/api/reader/v4/volumes/[^/?#]+/comic/archive$"))
        )

internal fun String.isSafeApiPath(): Boolean =
    startsWith("/api/") && !contains('#') && !contains('?') && !contains("//") &&
        split('/').none { it == "." || it == ".." }
