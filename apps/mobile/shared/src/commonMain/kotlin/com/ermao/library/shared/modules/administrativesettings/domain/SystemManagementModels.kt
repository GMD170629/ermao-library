package com.ermao.library.shared.modules.administrativesettings.domain

data class OpdsSettings(
    val enabled: Boolean,
    val configured: Boolean,
    val publicBaseUrl: String?,
    val catalogUrl: String?,
)

data class BackupArchive(
    val id: String,
    val kind: String?,
    val name: String,
    val fileName: String?,
    val sizeBytes: Long,
    val createdAt: String,
    val counts: Map<String, Int>,
)

data class BackupDownload(
    val bytes: ByteArray,
    val fileName: String,
    val contentType: String,
) {
    override fun equals(other: Any?): Boolean =
        this === other ||
            other is BackupDownload &&
            bytes.contentEquals(other.bytes) &&
            fileName == other.fileName &&
            contentType == other.contentType

    override fun hashCode(): Int = 31 * bytes.contentHashCode() + fileName.hashCode()
}

data class BackupRestoreResult(
    val id: String,
    val restored: Boolean,
    val restoredAt: String,
    val restoredCounts: Map<String, Int>,
    val actualCounts: Map<String, Int>,
)

enum class BackupRestoreConfirmation(val wireValue: String) {
    Restore("RESTORE"),
}

enum class WorkDetailTab(val wireValue: String) {
    Ebook("EBOOK"),
    Comic("COMIC"),
    Audiobook("AUDIOBOOK"),
    Structure("STRUCTURE"),
}

data class WorkDetailTabOrder(
    val tabs: List<WorkDetailTab>,
)

enum class HealthRunStatus(val wireValue: String) {
    Running("running"),
    Completed("completed"),
    Warning("warning"),
    Error("error"),
    Failed("failed"),
}

enum class HealthCheckStatus(val wireValue: String) {
    Pending("pending"),
    Running("running"),
    Ok("ok"),
    Warning("warning"),
    Error("error"),
    Skipped("skipped"),
}

data class HealthRunGroup(
    val id: String,
    val labelCode: String,
)

data class HealthRunItem(
    val id: String,
    val group: String,
    val labelCode: String,
    val kind: String,
    val status: HealthCheckStatus,
    val messageCode: String,
    val detailCodes: Map<String, String>,
    val startedAt: Long?,
    val finishedAt: Long?,
    val durationMilliseconds: Long?,
)

data class HealthRunSummary(
    val total: Int,
    val completed: Int,
    val ok: Int,
    val warning: Int,
    val error: Int,
    val skipped: Int,
)

data class HealthRun(
    val runId: String,
    val status: HealthRunStatus,
    val version: Long,
    val startedAt: Long,
    val finishedAt: Long?,
    val groups: List<HealthRunGroup>,
    val items: List<HealthRunItem>,
    val summary: HealthRunSummary,
)

data class QueueOperation(
    val id: String,
    val queueName: String,
    val action: String,
    val status: String,
    val messageCode: String,
    val requestedAt: String,
    val startedAt: String?,
    val finishedAt: String?,
    val updatedAt: String,
)

data class ManagementEventFilter(
    val page: Int = 1,
    val pageSize: Int = 20,
    val level: String? = null,
    val source: String? = null,
    val targetType: String? = null,
    val search: String? = null,
    /** Inclusive RFC 3339 lower boundary, normally the local day's start converted to an offset timestamp. */
    val dateFrom: String? = null,
    /** Inclusive RFC 3339 upper boundary, normally the local day's end converted to an offset timestamp. */
    val dateTo: String? = null,
)

data class ManagementEvent(
    val id: String,
    val level: String,
    val source: String,
    val actorType: String,
    val actorId: String?,
    val action: String,
    val targetType: String?,
    val targetId: String?,
    val message: String,
    val metadata: Map<String, String>,
    val createdAt: String?,
)

data class EventStorage(
    val sizeBytes: Long,
    val maximumBytes: Long,
    val lastPrunedAt: String?,
)

data class EventFacet(
    val value: String,
    val count: Int,
)

data class ManagementEventPage(
    val events: List<ManagementEvent>,
    val pageInfo: PageInfo,
    val storage: EventStorage,
    val sources: List<EventFacet>,
    val levels: List<EventFacet>,
)

data class ClearedManagementEvents(
    val deleted: Int,
    val storage: EventStorage?,
)

data class LogSettings(
    val storage: EventStorage,
    val minimumBytes: Long?,
    val maximumBytes: Long?,
)
