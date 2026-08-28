package com.ermao.library.shared.modules.downloads.domain

enum class MultiDownloadEligibility {
    Enqueue,
    Resume,
    Retry,
    Active,
    Completed,
    Unavailable,
}

enum class MultiDownloadSelectionMark { Unselected, Selected, Mixed }

data class MultiDownloadResourceState(
    val resourceId: String,
    val eligibility: MultiDownloadEligibility,
    val failureCode: String? = null,
) {
    init {
        require(resourceId.isNotBlank())
        require(failureCode == null || failureCode.isNotBlank())
    }

    val isSelectable: Boolean
        get() = eligibility in setOf(
            MultiDownloadEligibility.Enqueue,
            MultiDownloadEligibility.Resume,
            MultiDownloadEligibility.Retry,
        )
}

data class MultiDownloadSelectionState(
    val expandedSourceNodeIds: Set<String> = emptySet(),
    val selectedResourceIds: Set<String> = emptySet(),
) {
    fun toggleExpanded(sourceNodeId: String): MultiDownloadSelectionState {
        require(sourceNodeId.isNotBlank())
        return copy(
            expandedSourceNodeIds = expandedSourceNodeIds.toMutableSet().apply {
                if (!add(sourceNodeId)) remove(sourceNodeId)
            },
        )
    }

    fun toggleResource(resource: MultiDownloadResourceState): MultiDownloadSelectionState {
        if (!resource.isSelectable) return this
        return copy(
            selectedResourceIds = selectedResourceIds.toMutableSet().apply {
                if (!add(resource.resourceId)) remove(resource.resourceId)
            },
        )
    }

    fun toggleDirectory(
        descendantResourceIds: Collection<String>,
        resourcesById: Map<String, MultiDownloadResourceState>,
    ): MultiDownloadSelectionState {
        val selectable = descendantResourceIds.asSequence()
            .mapNotNull(resourcesById::get)
            .filter(MultiDownloadResourceState::isSelectable)
            .map(MultiDownloadResourceState::resourceId)
            .toSet()
        if (selectable.isEmpty()) return this
        val shouldSelect = selectable.any { it !in selectedResourceIds }
        return copy(
            selectedResourceIds = selectedResourceIds.toMutableSet().apply {
                if (shouldSelect) addAll(selectable) else removeAll(selectable)
            },
        )
    }

    fun directoryMark(
        descendantResourceIds: Collection<String>,
        resourcesById: Map<String, MultiDownloadResourceState>,
    ): MultiDownloadSelectionMark {
        val selectable = descendantResourceIds.asSequence()
            .mapNotNull(resourcesById::get)
            .filter(MultiDownloadResourceState::isSelectable)
            .map(MultiDownloadResourceState::resourceId)
            .toSet()
        if (selectable.isEmpty() || selectable.none { it in selectedResourceIds }) {
            return MultiDownloadSelectionMark.Unselected
        }
        return if (selectable.all { it in selectedResourceIds }) {
            MultiDownloadSelectionMark.Selected
        } else {
            MultiDownloadSelectionMark.Mixed
        }
    }
}

data class DownloadBatchCommand(
    val bookId: String,
    val resourceIds: Set<String>,
) {
    init {
        require(bookId.isNotBlank())
        require(resourceIds.isNotEmpty())
        require(resourceIds.none(String::isBlank))
    }
}

enum class DownloadBatchOutcomeKind { Enqueued, Resumed, Retried, Skipped, Failed }

data class DownloadBatchResourceResult(
    val resourceId: String,
    val outcome: DownloadBatchOutcomeKind,
    val failureCode: String? = null,
) {
    init {
        require(resourceId.isNotBlank())
        require(failureCode == null || failureCode.isNotBlank())
        require((outcome == DownloadBatchOutcomeKind.Failed) == (failureCode != null))
    }
    val shouldStart: Boolean get() = outcome in setOf(
        DownloadBatchOutcomeKind.Enqueued, DownloadBatchOutcomeKind.Resumed, DownloadBatchOutcomeKind.Retried,
    )
}

/** Shared intent policy; a batch reports accepted actions, never completed transfers. */
object DownloadBatchPolicy {
    fun decide(resourceId: String, status: DownloadTaskStatus?, failureCode: String?, active: Boolean): DownloadBatchResourceResult {
        val outcome = if (active) DownloadBatchOutcomeKind.Skipped else when (status) {
            null, DownloadTaskStatus.Queued -> DownloadBatchOutcomeKind.Enqueued
            DownloadTaskStatus.Paused, DownloadTaskStatus.WaitingForWifi -> DownloadBatchOutcomeKind.Resumed
            DownloadTaskStatus.FailedRetryable, DownloadTaskStatus.InsufficientSpace -> DownloadBatchOutcomeKind.Retried
            DownloadTaskStatus.FailedTerminal, DownloadTaskStatus.Cancelled -> DownloadBatchOutcomeKind.Failed
            DownloadTaskStatus.Downloading, DownloadTaskStatus.Completed -> DownloadBatchOutcomeKind.Skipped
        }
        return DownloadBatchResourceResult(resourceId, outcome,
            if (outcome == DownloadBatchOutcomeKind.Failed) failureCode ?: "DOWNLOAD_NOT_RETRYABLE" else null)
    }
}

data class DownloadBatchResult(
    val results: List<DownloadBatchResourceResult>,
) {
    val requestedResourceIds: List<String> get() = results.filter { it.shouldStart }.map { it.resourceId }
    val succeededCount: Int
        get() = results.count { it.shouldStart }
    val failedCount: Int get() = results.count { it.outcome == DownloadBatchOutcomeKind.Failed }
    val failedResourceIds: Set<String>
        get() = results.filter { it.outcome == DownloadBatchOutcomeKind.Failed }
            .map(DownloadBatchResourceResult::resourceId)
            .toSet()
}

data class DownloadBatchSummary(
    val selectedCount: Int,
    val enqueueCount: Int,
    val resumeCount: Int,
    val retryCount: Int,
)

fun summarizeDownloadBatch(
    selectedResourceIds: Set<String>,
    resourcesById: Map<String, MultiDownloadResourceState>,
): DownloadBatchSummary = DownloadBatchSummary(
    selectedCount = selectedResourceIds.size,
    enqueueCount = selectedResourceIds.count {
        resourcesById[it]?.eligibility == MultiDownloadEligibility.Enqueue
    },
    resumeCount = selectedResourceIds.count {
        resourcesById[it]?.eligibility == MultiDownloadEligibility.Resume
    },
    retryCount = selectedResourceIds.count {
        resourcesById[it]?.eligibility == MultiDownloadEligibility.Retry
    },
)
