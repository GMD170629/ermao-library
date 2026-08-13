package com.ermao.library.features.downloads.model

import kotlinx.serialization.Serializable

@Serializable
data class AndroidDownloadNamespace(
    val serverIdentity: String,
    val userId: String,
    val authorizationVersion: Long,
) {
    init {
        require(serverIdentity.isNotBlank())
        require(userId.isNotBlank())
        require(authorizationVersion >= 0)
    }
}

@Serializable
enum class AndroidDownloadStatus {
    Queued,
    Downloading,
    Paused,
    Verifying,
    Completed,
    FailedRetryable,
    FailedTerminal,
}

@Serializable
data class AndroidDownloadRecord(
    val taskId: String,
    val namespace: AndroidDownloadNamespace,
    val workId: String,
    val workTitle: String,
    val author: String,
    val coverUrl: String,
    val volumeId: String,
    val volumeTitle: String,
    val format: String,
    val readerType: String,
    val mediaVersionId: String = "legacy-volume:$volumeId",
    val mediaKind: String = readerType.toLegacyMediaKind(),
    val mediaVersionCompleted: Boolean? = null,
    val contentFingerprint: String,
    val sourceApiPath: String,
    val sourceMimeType: String,
    val expectedBytes: Long,
    val transferredBytes: Long = 0,
    val status: AndroidDownloadStatus = AndroidDownloadStatus.Queued,
    val localReference: String? = null,
    val verified: Boolean = false,
    val errorCode: String? = null,
    val createdAtEpochMillis: Long,
    val updatedAtEpochMillis: Long,
    val lastOpenedAtEpochMillis: Long? = null,
    val volumeIndex: Double? = null,
    val volumeSortOrder: Int? = null,
) {
    init {
        require(taskId.isNotBlank())
        require(workId.isNotBlank())
        require(volumeId.isNotBlank())
        require(contentFingerprint.isNotBlank())
        require(sourceApiPath.startsWith("/api/"))
        require(sourceMimeType.isNotBlank())
        require(expectedBytes >= 0)
        require(transferredBytes >= 0)
        require(transferredBytes <= expectedBytes || expectedBytes == 0L)
        require(verified == (status == AndroidDownloadStatus.Completed))
        require(!verified || !localReference.isNullOrBlank())
    }

    val isReadable: Boolean
        get() = status == AndroidDownloadStatus.Completed && verified && !localReference.isNullOrBlank()
}

data class DownloadedWorkGroup(
    val workId: String,
    val title: String,
    val author: String,
    val coverUrl: String,
    val mediaVersions: List<DownloadedMediaVersionGroup>,
) {
    val volumes: List<AndroidDownloadRecord> get() = mediaVersions.flatMap(DownloadedMediaVersionGroup::volumes)
    val totalBytes: Long get() = volumes.sumOf(AndroidDownloadRecord::expectedBytes)
    val lastOpenedAtEpochMillis: Long? get() = volumes.mapNotNull(AndroidDownloadRecord::lastOpenedAtEpochMillis).maxOrNull()
}

data class DownloadedMediaVersionGroup(
    val mediaVersionId: String,
    val mediaKind: String,
    val isServerComplete: Boolean?,
    val volumes: List<AndroidDownloadRecord>,
) {
    val totalBytes: Long get() = volumes.sumOf(AndroidDownloadRecord::expectedBytes)
}

fun groupReadableDownloads(
    records: List<AndroidDownloadRecord>,
    query: String,
    localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
): List<DownloadedWorkGroup> {
    val normalizedQuery = query.trim()
    return records.asSequence()
        .filter(AndroidDownloadRecord::isReadable)
        .filter(localArtifactIsValid)
        .filter { record ->
            normalizedQuery.isEmpty() || sequenceOf(record.workTitle, record.author, record.volumeTitle)
                .any { it.contains(normalizedQuery, ignoreCase = true) }
        }
        .groupBy(AndroidDownloadRecord::workId)
        .values
        .map { volumes ->
            val sorted = volumes.sortedWith(
                compareBy<AndroidDownloadRecord> { it.volumeSortOrder ?: Int.MAX_VALUE }
                    .thenBy { it.volumeIndex ?: Double.MAX_VALUE }
                    .thenBy(AndroidDownloadRecord::volumeTitle)
                    .thenBy(AndroidDownloadRecord::volumeId),
            )
            val first = sorted.first()
            val mediaVersions = sorted.groupBy(AndroidDownloadRecord::mediaVersionId).values.map { mediaVolumes ->
                val media = mediaVolumes.first()
                DownloadedMediaVersionGroup(
                    mediaVersionId = media.mediaVersionId,
                    mediaKind = media.mediaKind,
                    isServerComplete = media.mediaVersionCompleted,
                    volumes = mediaVolumes,
                )
            }
            DownloadedWorkGroup(first.workId, first.workTitle, first.author, first.coverUrl, mediaVersions)
        }
        .sortedWith(
            compareByDescending<DownloadedWorkGroup> { it.lastOpenedAtEpochMillis ?: Long.MIN_VALUE }
                .thenBy { it.title.lowercase() }
                .thenBy(DownloadedWorkGroup::workId),
        )
        .toList()
}

private fun String.toLegacyMediaKind(): String = when {
    equals("comic", true) -> "COMIC"
    equals("audio", true) -> "AUDIOBOOK"
    else -> "EBOOK"
}
