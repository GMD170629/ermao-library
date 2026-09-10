package com.ermao.library.shared.modules.downloads.domain

enum class DownloadManagementAction { Download, Pause, Resume, Retry, Remove, Open }

enum class MultiDownloadSelectionMark { Unselected, Selected, Mixed }

enum class DownloadManagementStatus {
    NotDownloaded, Queued, Downloading, Paused, Completed, InvalidLocal,
    FailedRetryable, FailedTerminal, Unavailable,
}

/** Facts supplied by the existing platform catalog and task owner. */
data class DownloadManagementItem(
    val resourceId: String,
    val status: DownloadTaskStatus?,
    val verified: Boolean,
    val active: Boolean,
    val available: Boolean,
    val failureCode: String? = null,
)

data class DownloadManagementResource(
    val resourceId: String,
    val status: DownloadManagementStatus,
    val actions: Set<DownloadManagementAction>,
) {
    val selectable: Boolean get() = actions.any { it != DownloadManagementAction.Open }
    val primaryAction: DownloadManagementAction?
        get() = listOf(
            DownloadManagementAction.Open, DownloadManagementAction.Download,
            DownloadManagementAction.Pause, DownloadManagementAction.Resume,
            DownloadManagementAction.Retry,
        ).firstOrNull { it in actions }
}

/** Shared presentation and action policy for both native download managers. */
object DownloadManagementPolicy {
    fun project(item: DownloadManagementItem): DownloadManagementResource {
        val status = when {
            item.active -> if (item.status == DownloadTaskStatus.Queued) {
                DownloadManagementStatus.Queued
            } else DownloadManagementStatus.Downloading
            item.status != null && item.failureCode == "DOWNLOAD_LOCAL_FILE_INVALID" ->
                DownloadManagementStatus.InvalidLocal
            item.status == null -> if (item.available) DownloadManagementStatus.NotDownloaded
                else DownloadManagementStatus.Unavailable
            else -> when (item.status) {
                DownloadTaskStatus.Queued -> DownloadManagementStatus.Queued
                DownloadTaskStatus.Downloading -> DownloadManagementStatus.Downloading
                DownloadTaskStatus.Paused, DownloadTaskStatus.WaitingForWifi -> DownloadManagementStatus.Paused
                DownloadTaskStatus.Completed -> if (item.verified) DownloadManagementStatus.Completed
                    else DownloadManagementStatus.InvalidLocal
                DownloadTaskStatus.FailedRetryable, DownloadTaskStatus.InsufficientSpace -> DownloadManagementStatus.FailedRetryable
                DownloadTaskStatus.FailedTerminal, DownloadTaskStatus.Cancelled -> DownloadManagementStatus.FailedTerminal
            }
        }
        val actions = buildSet {
            if (item.status != null || item.active) add(DownloadManagementAction.Remove)
            when (status) {
                DownloadManagementStatus.NotDownloaded -> add(DownloadManagementAction.Download)
                DownloadManagementStatus.Queued, DownloadManagementStatus.Downloading -> add(DownloadManagementAction.Pause)
                DownloadManagementStatus.Paused -> if (item.available) add(DownloadManagementAction.Resume)
                DownloadManagementStatus.InvalidLocal, DownloadManagementStatus.FailedRetryable ->
                    if (item.available) add(DownloadManagementAction.Retry)
                DownloadManagementStatus.Completed -> add(DownloadManagementAction.Open)
                DownloadManagementStatus.FailedTerminal, DownloadManagementStatus.Unavailable -> Unit
            }
        }
        return DownloadManagementResource(item.resourceId, status, actions)
    }

    /** Re-evaluated on current facts immediately before executing an action. */
    fun applicable(
        action: DownloadManagementAction,
        selectedResourceIds: Set<String>,
        resources: List<DownloadManagementResource>,
    ): List<String> = resources.asSequence()
        .filter { it.resourceId in selectedResourceIds && action in it.actions }
        .map { it.resourceId }.distinct().sorted().toList()

    fun toggleSelection(
        selected: Set<String>,
        candidates: Set<String>,
        resources: List<DownloadManagementResource>,
    ): Set<String> {
        val eligible = selectableIds(resources)
        val current = selected.intersect(eligible)
        val targets = candidates.intersect(eligible)
        return if (targets.isNotEmpty() && current.containsAll(targets)) current - targets
            else current + targets
    }

    fun selectionMark(
        selected: Set<String>,
        candidates: Set<String>,
        resources: List<DownloadManagementResource>,
    ): MultiDownloadSelectionMark {
        val targets = candidates.intersect(selectableIds(resources))
        return when {
            targets.isEmpty() || targets.none { it in selected } -> MultiDownloadSelectionMark.Unselected
            selected.containsAll(targets) -> MultiDownloadSelectionMark.Selected
            else -> MultiDownloadSelectionMark.Mixed
        }
    }

    private fun selectableIds(resources: List<DownloadManagementResource>): Set<String> =
        resources.filter { it.selectable }.map { it.resourceId }.toSet()
}

enum class DownloadManagementOutcome { Accepted, Completed, Skipped, Failed }

/** Accepted starts a transfer; Completed confirms pause/removal or a verified reader handoff. */
data class DownloadManagementResult(
    val resourceId: String,
    val action: DownloadManagementAction,
    val outcome: DownloadManagementOutcome,
    val failureCode: String? = null,
)
