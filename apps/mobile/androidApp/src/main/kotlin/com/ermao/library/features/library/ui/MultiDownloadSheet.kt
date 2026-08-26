package com.ermao.library.features.library.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TriStateCheckbox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.shared.modules.downloads.DownloadBatchResult
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.ui.components.WarmPageErrorState
import com.ermao.library.ui.components.WarmPageLoadingState
import com.ermao.library.ui.components.WarmPageModalBottomSheet
import com.ermao.library.ui.theme.WarmPageThemeValues

private data class MultiDownloadTreeRow(
    val entry: BookContentEntry,
    val depth: Int,
)

private enum class MultiDownloadResourceEligibility { Enqueue, Resume, Retry, Active, Completed, Terminal, Unavailable }

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun MultiDownloadSheet(
    state: WorkDetailUiState,
    recordsByResource: Map<String, AndroidDownloadRecord>,
    onDismiss: () -> Unit,
    onRetryTree: () -> Unit,
    onToggleFolder: (String) -> Unit,
    onEnsureFolderLoaded: (String) -> Unit,
    onPause: (String) -> Unit,
    onResumeOrRetry: (String) -> Unit,
    onRemove: (AndroidDownloadRecord) -> Unit,
    onOpenDownloaded: (AndroidDownloadRecord) -> Unit,
    onPerformBatch: (Set<String>, (DownloadBatchResult) -> Unit) -> Unit,
    onBatchFeedback: (succeeded: Int, failed: Int) -> Unit,
) {
    val theme = WarmPageThemeValues
    var selectedIdsList by rememberSaveable { mutableStateOf(emptyList<String>()) }
    val selectedIds = selectedIdsList.toSet()
    var pendingDirectorySelection by remember { mutableStateOf<String?>(null) }
    var isSubmitting by remember { mutableStateOf(false) }
    val resourcesById = state.multiDownloadResources.associateBy(ResourceContent::id)
    val rows = remember(
        state.multiDownloadRootNodeId,
        state.multiDownloadChildrenByNodeId,
        state.multiDownloadExpandedNodeIds,
    ) {
        flattenMultiDownloadRows(
            state.multiDownloadRootNodeId,
            state.multiDownloadChildrenByNodeId,
            state.multiDownloadExpandedNodeIds,
        )
    }

    LaunchedEffect(pendingDirectorySelection, state.multiDownloadDescendantResourceIdsByNodeId) {
        val nodeId = pendingDirectorySelection ?: return@LaunchedEffect
        val descendants = state.multiDownloadDescendantResourceIdsByNodeId[nodeId] ?: return@LaunchedEffect
        selectedIdsList = toggleDirectorySelection(
            descendants,
            selectedIds,
            resourcesById,
            recordsByResource,
        ).sorted()
        pendingDirectorySelection = null
    }

    WarmPageModalBottomSheet(
        onDismissRequest = { if (!isSubmitting) onDismiss() },
        modifier = Modifier.testTag("multi-download-sheet"),
    ) {
        Column(Modifier.fillMaxWidth()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = theme.components.page.compactGutter),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(stringResource(R.string.multi_download_title), style = theme.typography.sectionTitle)
                    Text(
                        state.content?.book?.title.orEmpty(),
                        style = theme.typography.callout,
                        color = theme.colors.textSecondary,
                    )
                }
                TextButton(onClick = onDismiss, enabled = !isSubmitting) {
                    Text(stringResource(R.string.cancel_action))
                }
            }
            HorizontalDivider(color = theme.colors.divider)
            when {
                state.multiDownloadErrorCode != null -> WarmPageErrorState(
                    title = stringResource(R.string.multi_download_error_title),
                    message = stringResource(R.string.multi_download_error_message),
                    retryLabel = stringResource(R.string.retry_action),
                    onRetry = onRetryTree,
                    modifier = Modifier.fillMaxWidth().weight(1f, fill = false),
                )
                state.multiDownloadRootNodeId == null -> WarmPageLoadingState(
                    title = stringResource(R.string.content_loading_title),
                    message = stringResource(R.string.multi_download_loading),
                    modifier = Modifier.fillMaxWidth().weight(1f, fill = false),
                )
                else -> LazyColumn(
                    modifier = Modifier.fillMaxWidth().weight(1f, fill = false),
                ) {
                    items(rows, key = { it.entry.sourceNodeId }) { row ->
                        if (row.entry.isSourceFolder) {
                            val descendants = state.multiDownloadDescendantResourceIdsByNodeId[row.entry.sourceNodeId]
                                .orEmpty()
                            val mark = directoryToggleState(
                                descendants,
                                selectedIds,
                                resourcesById,
                                recordsByResource,
                            )
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(start = (row.depth * 20).dp, end = theme.components.page.compactGutter),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                TextButton(onClick = { onToggleFolder(row.entry.sourceNodeId) }) {
                                    Icon(
                                        if (row.entry.sourceNodeId in state.multiDownloadExpandedNodeIds) {
                                            Icons.Filled.KeyboardArrowDown
                                        } else {
                                            Icons.AutoMirrored.Filled.KeyboardArrowRight
                                        },
                                        contentDescription = stringResource(R.string.multi_download_toggle_folder),
                                    )
                                }
                                TriStateCheckbox(
                                    state = mark,
                                    onClick = {
                                        if (state.multiDownloadDescendantResourceIdsByNodeId[row.entry.sourceNodeId] == null) {
                                            pendingDirectorySelection = row.entry.sourceNodeId
                                            onEnsureFolderLoaded(row.entry.sourceNodeId)
                                        } else {
                                            selectedIdsList = toggleDirectorySelection(
                                                descendants,
                                                selectedIds,
                                                resourcesById,
                                                recordsByResource,
                                            ).sorted()
                                        }
                                    },
                                    enabled = !state.isMultiDownloadResourcesLoading &&
                                        row.entry.sourceNodeId !in state.multiDownloadLoadingNodeIds,
                                )
                                Column(Modifier.weight(1f)) {
                                    Text(row.entry.title, style = theme.typography.body)
                                    Text(
                                        pluralStringResource(
                                            R.plurals.multi_download_volume_count,
                                            descendants.size,
                                            descendants.size,
                                        ),
                                        style = theme.typography.caption,
                                        color = theme.colors.textSecondary,
                                    )
                                }
                            }
                        } else {
                            val resource = row.entry.resourceId?.let(resourcesById::get)
                            if (resource != null) {
                                val record = recordsByResource[resource.id]
                                val eligibility = resourceEligibility(resource, record)
                                var menuExpanded by remember(resource.id) { mutableStateOf(false) }
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .combinedClickable(
                                            onClick = {
                                                when {
                                                    eligibility == MultiDownloadResourceEligibility.Completed &&
                                                        record?.isReadable == true -> menuExpanded = true
                                                    eligibility.isSelectable() -> {
                                                        selectedIdsList = selectedIds.toMutableSet().apply {
                                                            if (!add(resource.id)) remove(resource.id)
                                                        }.sorted()
                                                    }
                                                }
                                            },
                                            onLongClick = { if (record != null) menuExpanded = true },
                                        )
                                        .padding(
                                            start = (row.depth * 20 + 44).dp,
                                            end = theme.components.page.compactGutter,
                                            top = theme.spacing.one,
                                            bottom = theme.spacing.one,
                                        ),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    androidx.compose.material3.Checkbox(
                                        checked = resource.id in selectedIds,
                                        onCheckedChange = {
                                            if (eligibility.isSelectable()) {
                                                selectedIdsList = selectedIds.toMutableSet().apply {
                                                    if (!add(resource.id)) remove(resource.id)
                                                }.sorted()
                                            }
                                        },
                                        enabled = eligibility.isSelectable() && !isSubmitting,
                                    )
                                    Column(Modifier.weight(1f)) {
                                        Text(resource.title, style = theme.typography.body)
                                        Text(
                                            listOfNotNull(
                                                resource.format,
                                                resource.sizeBytes.takeIf { it > 0 }?.let(::formatBytes),
                                            ).joinToString(" · "),
                                            style = theme.typography.caption,
                                            color = theme.colors.textSecondary,
                                        )
                                    }
                                    TextButton(onClick = { if (record != null) menuExpanded = true }) {
                                        Text(resourceStatusText(eligibility, record))
                                    }
                                    DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                                        DownloadStatusMenuItems(
                                            record = record,
                                            onDismiss = { menuExpanded = false },
                                            onPause = onPause,
                                            onResumeOrRetry = onResumeOrRetry,
                                            onRemove = onRemove,
                                            onOpenDownloaded = onOpenDownloaded,
                                        )
                                    }
                                }
                            }
                        }
                        HorizontalDivider(color = theme.colors.divider)
                    }
                }
            }
            val summary = batchSummary(selectedIds, resourcesById, recordsByResource)
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = theme.components.page.compactGutter, vertical = theme.spacing.one),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        pluralStringResource(
                            R.plurals.multi_download_selected_count,
                            summary.selected,
                            summary.selected,
                        ),
                        style = theme.typography.headline,
                    )
                    Spacer(Modifier.weight(1f))
                    Text(
                        stringResource(
                            R.string.multi_download_summary,
                            summary.enqueue,
                            summary.resume,
                            summary.retry,
                        ),
                        style = theme.typography.caption,
                        color = theme.colors.textSecondary,
                    )
                }
                Button(
                    onClick = {
                        isSubmitting = true
                        onPerformBatch(selectedIds) { result ->
                            isSubmitting = false
                            selectedIdsList = result.failedResourceIds.sorted()
                            onBatchFeedback(result.succeededCount, result.failedCount)
                            if (result.failedCount == 0) onDismiss()
                        }
                    },
                    enabled = selectedIds.isNotEmpty() && !isSubmitting,
                    modifier = Modifier.fillMaxWidth().heightIn(min = theme.metrics.androidMinimumTouchTarget),
                ) {
                    Text(stringResource(R.string.multi_download_confirm))
                }
            }
        }
    }
}

private fun flattenMultiDownloadRows(
    rootNodeId: String?,
    childrenByNodeId: Map<String, List<BookContentEntry>>,
    expandedNodeIds: Set<String>,
): List<MultiDownloadTreeRow> {
    if (rootNodeId == null) return emptyList()
    fun children(nodeId: String, depth: Int): List<MultiDownloadTreeRow> =
        childrenByNodeId[nodeId].orEmpty().flatMap { entry ->
            val row = MultiDownloadTreeRow(entry, depth)
            if (entry.isSourceFolder && entry.sourceNodeId in expandedNodeIds) {
                listOf(row) + children(entry.sourceNodeId, depth + 1)
            } else {
                listOf(row)
            }
        }
    return children(rootNodeId, 0)
}

private fun resourceEligibility(
    resource: ResourceContent,
    record: AndroidDownloadRecord?,
): MultiDownloadResourceEligibility {
    if (!resource.readable) return MultiDownloadResourceEligibility.Unavailable
    return when (record?.status) {
        null -> MultiDownloadResourceEligibility.Enqueue
        AndroidDownloadStatus.Paused -> MultiDownloadResourceEligibility.Resume
        AndroidDownloadStatus.FailedRetryable -> MultiDownloadResourceEligibility.Retry
        AndroidDownloadStatus.Queued,
        AndroidDownloadStatus.Downloading,
        AndroidDownloadStatus.Verifying,
        -> MultiDownloadResourceEligibility.Active
        AndroidDownloadStatus.Completed -> MultiDownloadResourceEligibility.Completed
        AndroidDownloadStatus.FailedTerminal -> MultiDownloadResourceEligibility.Terminal
    }
}

private fun MultiDownloadResourceEligibility.isSelectable() =
    this in setOf(
        MultiDownloadResourceEligibility.Enqueue,
        MultiDownloadResourceEligibility.Resume,
        MultiDownloadResourceEligibility.Retry,
    )

private fun toggleDirectorySelection(
    descendants: Set<String>,
    selected: Set<String>,
    resourcesById: Map<String, ResourceContent>,
    recordsByResource: Map<String, AndroidDownloadRecord>,
): Set<String> {
    val selectable = descendants.filter { id ->
        resourcesById[id]?.let { resourceEligibility(it, recordsByResource[id]).isSelectable() } == true
    }.toSet()
    if (selectable.isEmpty()) return selected
    return selected.toMutableSet().apply {
        if (selectable.all(::contains)) removeAll(selectable) else addAll(selectable)
    }
}

private fun directoryToggleState(
    descendants: Set<String>,
    selected: Set<String>,
    resourcesById: Map<String, ResourceContent>,
    recordsByResource: Map<String, AndroidDownloadRecord>,
): ToggleableState {
    val selectable = descendants.filter { id ->
        resourcesById[id]?.let { resourceEligibility(it, recordsByResource[id]).isSelectable() } == true
    }
    if (selectable.isEmpty() || selectable.none(selected::contains)) return ToggleableState.Off
    return if (selectable.all(selected::contains)) ToggleableState.On else ToggleableState.Indeterminate
}

private data class MultiDownloadBatchSummary(
    val selected: Int,
    val enqueue: Int,
    val resume: Int,
    val retry: Int,
)

private fun batchSummary(
    selected: Set<String>,
    resourcesById: Map<String, ResourceContent>,
    recordsByResource: Map<String, AndroidDownloadRecord>,
): MultiDownloadBatchSummary {
    var enqueue = 0
    var resume = 0
    var retry = 0
    selected.forEach { id ->
        when (resourcesById[id]?.let { resourceEligibility(it, recordsByResource[id]) }) {
            MultiDownloadResourceEligibility.Enqueue -> enqueue += 1
            MultiDownloadResourceEligibility.Resume -> resume += 1
            MultiDownloadResourceEligibility.Retry -> retry += 1
            else -> Unit
        }
    }
    return MultiDownloadBatchSummary(selected.size, enqueue, resume, retry)
}

@Composable
private fun resourceStatusText(
    eligibility: MultiDownloadResourceEligibility,
    record: AndroidDownloadRecord?,
): String = when (eligibility) {
    MultiDownloadResourceEligibility.Enqueue -> stringResource(R.string.multi_download_not_downloaded)
    MultiDownloadResourceEligibility.Resume -> stringResource(R.string.multi_download_paused)
    MultiDownloadResourceEligibility.Retry,
    MultiDownloadResourceEligibility.Terminal,
    -> stringResource(R.string.multi_download_failed)
    MultiDownloadResourceEligibility.Completed -> stringResource(R.string.multi_download_downloaded)
    MultiDownloadResourceEligibility.Unavailable -> stringResource(R.string.multi_download_unavailable)
    MultiDownloadResourceEligibility.Active -> when (record?.status) {
        AndroidDownloadStatus.Queued -> stringResource(R.string.multi_download_queued)
        AndroidDownloadStatus.Verifying -> stringResource(R.string.multi_download_verifying)
        else -> record?.let { value ->
            if (value.expectedBytes > 0) "${(value.transferredBytes * 100 / value.expectedBytes).coerceIn(0, 100)}%"
            else null
        } ?: stringResource(R.string.multi_download_downloading)
    }
}

@Composable
private fun DownloadStatusMenuItems(
    record: AndroidDownloadRecord?,
    onDismiss: () -> Unit,
    onPause: (String) -> Unit,
    onResumeOrRetry: (String) -> Unit,
    onRemove: (AndroidDownloadRecord) -> Unit,
    onOpenDownloaded: (AndroidDownloadRecord) -> Unit,
) {
    if (record == null) return
    when (record.status) {
        AndroidDownloadStatus.Queued,
        AndroidDownloadStatus.Downloading,
        AndroidDownloadStatus.Verifying,
        -> DropdownMenuItem(
            text = { Text(stringResource(R.string.multi_download_pause)) },
            onClick = { onDismiss(); onPause(record.resourceId) },
        )
        AndroidDownloadStatus.Paused,
        AndroidDownloadStatus.FailedRetryable,
        -> DropdownMenuItem(
            text = { Text(stringResource(R.string.multi_download_resume)) },
            onClick = { onDismiss(); onResumeOrRetry(record.resourceId) },
        )
        else -> Unit
    }
    if (record.status == AndroidDownloadStatus.Completed && record.isReadable) {
        DropdownMenuItem(
            text = { Text(stringResource(R.string.work_download_open_offline)) },
            onClick = { onDismiss(); onOpenDownloaded(record) },
        )
    }
    DropdownMenuItem(
        text = {
            Text(
                stringResource(
                    if (record.status == AndroidDownloadStatus.Completed) {
                        R.string.downloads_remove_action
                    } else {
                        R.string.multi_download_delete_task
                    },
                ),
            )
        },
        onClick = { onDismiss(); onRemove(record) },
    )
}

private fun formatBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024L * 1024L -> "%.1f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
    bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
    bytes >= 1024L -> "%.1f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}
