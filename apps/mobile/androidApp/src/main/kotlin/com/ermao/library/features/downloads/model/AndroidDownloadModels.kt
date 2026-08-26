package com.ermao.library.features.downloads.model

import kotlinx.serialization.Serializable

/** Android's durable namespace mirrors the shared private-data namespace. */
@Serializable
data class AndroidDownloadNamespace(
    val serverIdentity: String,
    val userId: String,
    val authorizationVersion: Long,
) {
    init {
        require(serverIdentity.isNotBlank())
        require(userId.isNotBlank())
        require(authorizationVersion > 0)
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
data class AndroidDownloadMemberRecord(
    val assetId: String,
    val sequenceIndex: Int,
    val sourceApiPath: String,
    val sourceMimeType: String,
    val expectedBytes: Long,
)

/** Book -> Resource -> Asset ownership for catalog v3. */
@Serializable
data class AndroidDownloadRecord(
    val taskId: String,
    val namespace: AndroidDownloadNamespace,
    val bookId: String,
    val bookTitle: String,
    val author: String,
    val coverUrl: String,
    val resourceId: String,
    val resourceTitle: String,
    val format: String,
    val readerType: String,
    val assetId: String,
    val sourceApiPath: String,
    val sourceMimeType: String,
    val expectedBytes: Long,
    /** Source byte count is separate from bundle total in catalog v4. */
    val sourceBytes: Long? = null,
    val artifactKind: String = "SingleOriginalAsset",
    val members: List<AndroidDownloadMemberRecord> = emptyList(),
    val transferredBytes: Long = 0,
    val status: AndroidDownloadStatus = AndroidDownloadStatus.Queued,
    val localReference: String? = null,
    val verified: Boolean = false,
    val errorCode: String? = null,
    val createdAtEpochMillis: Long,
    val updatedAtEpochMillis: Long,
    val lastOpenedAtEpochMillis: Long? = null,
    val resourceIndex: Double? = null,
    val resourceSortOrder: Int? = null,
) {
    init {
        require(taskId.isNotBlank())
        require(bookId.isNotBlank())
        require(resourceId.isNotBlank())
        require(assetId.isNotBlank())
        require(sourceApiPath.startsWith("/api/"))
        require(sourceMimeType.isNotBlank())
        require(expectedBytes > 0)
        require((sourceBytes ?: expectedBytes) > 0)
        require(transferredBytes >= 0 && transferredBytes <= expectedBytes)
        require(verified == (status == AndroidDownloadStatus.Completed))
        require(!verified || !localReference.isNullOrBlank())
    }

    val isReadable: Boolean
        get() = status == AndroidDownloadStatus.Completed && verified && !localReference.isNullOrBlank()

}

/** A completed Book projection used by the Android Downloads screen. */
data class DownloadedBookGroup(
    val bookId: String,
    val title: String,
    val author: String,
    val coverUrl: String,
    val resources: List<DownloadedResourceGroup>,
) {
    val artifacts: List<AndroidDownloadRecord> get() = resources.flatMap { it.artifacts }
    val totalBytes: Long get() = artifacts.sumOf(AndroidDownloadRecord::expectedBytes)
    val lastOpenedAtEpochMillis: Long? get() = artifacts.mapNotNull(AndroidDownloadRecord::lastOpenedAtEpochMillis).maxOrNull()
}

/** A Resource projection; assets remain individual catalog records. */
data class DownloadedResourceGroup(
    val resourceId: String,
    val title: String,
    val artifacts: List<AndroidDownloadRecord>,
) {
    val totalBytes: Long get() = artifacts.sumOf(AndroidDownloadRecord::expectedBytes)
}

fun groupReadableDownloads(
    records: List<AndroidDownloadRecord>,
    query: String,
    localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
): List<DownloadedBookGroup> {
    val normalizedQuery = query.trim()
    return records.asSequence()
        .filter(AndroidDownloadRecord::isReadable)
        .filter(localArtifactIsValid)
        .filter { record ->
            normalizedQuery.isEmpty() || sequenceOf(record.bookTitle, record.author, record.resourceTitle)
                .any { it.contains(normalizedQuery, ignoreCase = true) }
        }
        .groupBy(AndroidDownloadRecord::bookId)
        .values
        .map { bookRecords ->
            val resources = bookRecords.groupBy(AndroidDownloadRecord::resourceId).values
                .map { resourceRecords ->
                    val first = resourceRecords.first()
                    DownloadedResourceGroup(
                        resourceId = first.resourceId,
                        title = first.resourceTitle,
                        artifacts = resourceRecords.sortedWith(compareBy(AndroidDownloadRecord::assetId)),
                    )
                }
                .sortedWith(
                    compareBy<DownloadedResourceGroup> {
                        it.artifacts.firstOrNull()?.resourceSortOrder ?: Int.MAX_VALUE
                    }.thenBy { it.artifacts.firstOrNull()?.resourceIndex ?: Double.MAX_VALUE }
                        .thenBy { it.title }
                        .thenBy(DownloadedResourceGroup::resourceId),
                )
            val first = resources.first().artifacts.first()
            DownloadedBookGroup(first.bookId, first.bookTitle, first.author, first.coverUrl, resources)
        }
        .sortedWith(
            compareByDescending<DownloadedBookGroup> { it.lastOpenedAtEpochMillis ?: Long.MIN_VALUE }
                .thenBy { it.title.lowercase() }
                .thenBy(DownloadedBookGroup::bookId),
        )
        .toList()
}
