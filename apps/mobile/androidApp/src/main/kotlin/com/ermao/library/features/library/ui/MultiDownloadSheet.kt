package com.ermao.library.features.library.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Checklist
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.FileDownload
import androidx.compose.material.icons.outlined.Pause
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.SelectAll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.LocalResources
import com.ermao.library.shared.core.feedback.OperationFeedbackKind
import com.ermao.library.ui.components.WarmPageSnackbarHost
import com.ermao.library.ui.components.showFeedback
import kotlinx.coroutines.launch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.downloads.DownloadRecord as AndroidDownloadRecord
import com.ermao.library.features.downloads.downloadFailureMessage
import com.ermao.library.features.downloads.downloadManagementItem
import com.ermao.library.features.library.application.DownloadPanelScope
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.shared.modules.downloads.DownloadManagementAction
import com.ermao.library.shared.modules.downloads.DownloadManagementOutcome
import com.ermao.library.shared.modules.downloads.DownloadManagementPolicy
import com.ermao.library.shared.modules.downloads.DownloadManagementResource
import com.ermao.library.shared.modules.downloads.DownloadManagementResult
import com.ermao.library.shared.modules.downloads.MultiDownloadSelectionMark
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.ui.components.LocalWarmPageModalSheetDismiss
import com.ermao.library.ui.components.WarmPageErrorState
import com.ermao.library.ui.components.WarmPageIconAction
import com.ermao.library.ui.components.WarmPageLoadingState
import com.ermao.library.ui.components.WarmPageMenuItem
import com.ermao.library.ui.components.WarmPageModalBottomSheet
import com.ermao.library.ui.components.WarmPagePopup
import com.ermao.library.ui.theme.WarmPageThemeValues

private data class MultiDownloadTreeRow(
    val entry: BookContentEntry,
    val depth: Int,
)

/**
 * One native download manager for Book, Directory and Resource detail pages.
 * The normal presentation is a status list with explicit primary actions. A
 * separate selection mode owns checkboxes and the batch action bar.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun MultiDownloadSheet(
    state: WorkDetailUiState,
    recordsByResource: Map<String, AndroidDownloadRecord>,
    activeResourceIds: Set<String> = emptySet(),
    onDismiss: () -> Unit,
    onRetryTree: () -> Unit,
    onRetryFolder: (String?) -> Unit = { onRetryTree() },
    onToggleFolder: (String) -> Unit,
    onEnsureFolderLoaded: (String) -> Unit,
    onRefreshLocalFacts: (Set<String>) -> Unit = {},
    onExecuteAction: (
        DownloadManagementAction,
        Set<String>,
        Set<String>,
        (List<DownloadManagementResult>) -> Unit,
    ) -> Unit,
    onOpenDownloaded: (AndroidDownloadRecord) -> Unit,
) {
    val theme = WarmPageThemeValues
    var selectionMode by rememberSaveable(state.multiDownloadScope) { mutableStateOf(false) }
    var selectedIdsList by rememberSaveable(state.multiDownloadScope) { mutableStateOf(emptyList<String>()) }
    var pendingDirectorySelection by remember { mutableStateOf<String?>(null) }
    var pendingRemovalIds by remember { mutableStateOf<Set<String>?>(null) }
    var isSubmitting by remember { mutableStateOf(false) }
    val feedbackHost = remember { SnackbarHostState() }
    val feedbackScope = rememberCoroutineScope()
    val feedbackResources = LocalResources.current
    var actionResults by remember { mutableStateOf<List<DownloadManagementResult>>(emptyList()) }
    val selectedIds = selectedIdsList.toSet()
    val panelBookId = state.content?.book?.id
    val knownDirectoryResourceIds = if (state.multiDownloadScope == DownloadPanelScope.Directory) {
        state.multiDownloadRootNodeId
            ?.let { state.multiDownloadDescendantResourceIdsByNodeId[it].orEmpty() }
            .orEmpty()
    } else {
        emptySet()
    }
    val panelRecordsByResourceId = recordsByResource.filterValues { record ->
        when (state.multiDownloadScope) {
            DownloadPanelScope.Book -> panelBookId != null && record.bookId == panelBookId
            DownloadPanelScope.Resource -> record.resourceId == state.multiDownloadResourceId &&
                (panelBookId == null || record.bookId == panelBookId)
            DownloadPanelScope.Directory -> record.resourceId in knownDirectoryResourceIds &&
                (panelBookId == null || record.bookId == panelBookId)
            null -> false
        }
    }
    val panelResources = remember(
        state.multiDownloadResources,
        panelRecordsByResourceId,
    ) {
        val remoteIds = state.multiDownloadResources.map(ResourceContent::id).toSet()
        val localOnlyResources = panelRecordsByResourceId.values
            .filter { it.resourceId !in remoteIds }
            .map(AndroidDownloadRecord::toPanelResource)
        state.multiDownloadResources + localOnlyResources
    }
    val resourcesById = panelResources.associateBy(ResourceContent::id)
    val managementById = remember(
        panelResources,
        panelRecordsByResourceId,
        activeResourceIds,
    ) {
        panelResources.associate { resource ->
            resource.id to managementResource(
                resource,
                panelRecordsByResourceId[resource.id],
                resource.id in activeResourceIds,
            )
        }
    }
    val rows = remember(
        state.multiDownloadScope,
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
    val localBookResourceIds = if (state.multiDownloadScope == DownloadPanelScope.Book) {
        panelRecordsByResourceId.keys
    } else {
        emptySet()
    }
    val scopeResourceIds = when (state.multiDownloadScope) {
        DownloadPanelScope.Resource -> state.multiDownloadResourceId?.let(::setOf).orEmpty()
        DownloadPanelScope.Book -> {
            val treeResourceIds = state.multiDownloadRootNodeId
                ?.let { state.multiDownloadDescendantResourceIdsByNodeId[it].orEmpty() }
                .orEmpty()
            when {
                treeResourceIds.isNotEmpty() -> treeResourceIds + localBookResourceIds
                state.multiDownloadErrorCode != null -> panelResources.map(ResourceContent::id).toSet()
                else -> localBookResourceIds
            }
        }
        DownloadPanelScope.Directory -> state.multiDownloadRootNodeId
            ?.let { state.multiDownloadDescendantResourceIdsByNodeId[it].orEmpty() }
            .orEmpty()
        null -> emptySet()
    }
    val scopeResources = panelResources.filter { it.id in scopeResourceIds }
    val scopeManagement = scopeResources.mapNotNull { managementById[it.id] }
    val availableScopeIds = scopeResources.filter(ResourceContent::readable).map(ResourceContent::id).toSet()
    val visibleTreeResourceIds = rows.mapNotNull { it.entry.resourceId }.toSet()
    val loadedTreeResourceIds = state.multiDownloadChildrenByNodeId.values
        .asSequence()
        .flatMap { it.asSequence() }
        .mapNotNull(BookContentEntry::resourceId)
        .toSet()
    val localOnlyBookResourceIds = if (state.multiDownloadScope == DownloadPanelScope.Book) {
        panelRecordsByResourceId.keys - loadedTreeResourceIds
    } else {
        emptySet()
    }
    val displayedResourceIds = when (state.multiDownloadScope) {
        DownloadPanelScope.Resource -> state.multiDownloadResourceId?.let(::setOf).orEmpty()
        else -> visibleTreeResourceIds + localOnlyBookResourceIds
    }.ifEmpty {
        if (scopeResourceIds.isNotEmpty() && rows.isEmpty()) {
            // A root whose direct children are resources can have a valid
            // currentResourceIds set even when the contents page has no entry
            // rows. Show that loaded scope without flattening collapsed folders.
            scopeResourceIds
        } else {
            emptySet()
        }
    }
    val displayedResources = panelResources.filter { it.id in displayedResourceIds }
    val selectableIds = scopeManagement.filter(DownloadManagementResource::selectable)
        .map(DownloadManagementResource::resourceId)
        .toSet()
    val scopedSelectedIds = selectedIds.intersect(selectableIds)
    val scopeIsReady = when (state.multiDownloadScope) {
        DownloadPanelScope.Resource -> !state.isMultiDownloadResourcesLoading
        DownloadPanelScope.Book,
        DownloadPanelScope.Directory,
        -> state.multiDownloadRootNodeId != null &&
            state.multiDownloadRootNodeId in state.multiDownloadDescendantResourceIdsByNodeId &&
            state.multiDownloadRootNodeId !in state.multiDownloadLoadingNodeIds &&
            !state.isMultiDownloadResourcesLoading
        null -> false
    }

    LaunchedEffect(state.multiDownloadScope, scopeResourceIds) {
        if (scopeResourceIds.isNotEmpty()) onRefreshLocalFacts(scopeResourceIds)
    }

    LaunchedEffect(selectedIdsList, selectableIds, scopeIsReady) {
        if (!scopeIsReady) return@LaunchedEffect
        if (scopedSelectedIds.size != selectedIds.size) {
            selectedIdsList = scopedSelectedIds.sorted()
        }
    }

    LaunchedEffect(
        pendingDirectorySelection,
        state.multiDownloadDescendantResourceIdsByNodeId,
        scopeManagement,
        scopeIsReady,
    ) {
        if (!scopeIsReady) return@LaunchedEffect
        val nodeId = pendingDirectorySelection ?: return@LaunchedEffect
        val descendants = state.multiDownloadDescendantResourceIdsByNodeId[nodeId]
            ?: return@LaunchedEffect
        selectedIdsList = DownloadManagementPolicy.toggleSelection(
            selected = scopedSelectedIds,
            candidates = descendants,
            resources = scopeManagement,
        ).sorted()
        pendingDirectorySelection = null
    }

    fun submitAction(
        action: DownloadManagementAction,
        ids: Set<String>,
        availableIds: Set<String>,
        onResults: (List<DownloadManagementResult>) -> Unit = {},
    ) {
        if (!isSubmitting && ids.isNotEmpty()) {
            isSubmitting = true
            actionResults = emptyList()
            onExecuteAction(action, ids, availableIds) { results ->
                isSubmitting = false
                val successful = results.isNotEmpty() && results.all {
                    it.outcome == DownloadManagementOutcome.Accepted || it.outcome == DownloadManagementOutcome.Completed
                }
                if (successful && action != DownloadManagementAction.Open) {
                    val acceptedCount = results.count { it.outcome == DownloadManagementOutcome.Accepted }
                    val completedCount = results.count { it.outcome == DownloadManagementOutcome.Completed }
                    val message = listOfNotNull(
                        if (acceptedCount > 0) feedbackResources.getString(R.string.download_management_accepted, acceptedCount) else null,
                        if (completedCount > 0) feedbackResources.getString(R.string.download_management_completed, completedCount) else null,
                    ).joinToString(" · ")
                    feedbackScope.launch { feedbackHost.showFeedback(message, OperationFeedbackKind.Success) }
                } else if (!successful) {
                    actionResults = results
                }
                val completed = results.asSequence()
                    .filter { it.outcome == DownloadManagementOutcome.Completed }
                    .map(DownloadManagementResult::resourceId)
                    .toSet()
                if (action == DownloadManagementAction.Remove && completed.isNotEmpty()) {
                    selectedIdsList = (selectedIdsList.toSet() - completed).sorted()
                }
                if (action == DownloadManagementAction.Remove) pendingRemovalIds = null
                onResults(results)
            }
        }
    }

    WarmPageModalBottomSheet(
        onDismissRequest = { if (!isSubmitting) onDismiss() },
        skipPartiallyExpanded = true,
        canDismiss = { !isSubmitting },
        modifier = Modifier
            .fillMaxWidth()
            .fillMaxHeight(0.92f)
            .testTag("multi-download-sheet"),
    ) {
        val dismissSheet = LocalWarmPageModalSheetDismiss.current ?: onDismiss
        fun requestOpen(resource: ResourceContent, record: AndroidDownloadRecord) {
            submitAction(
                action = DownloadManagementAction.Open,
                ids = setOf(resource.id),
                availableIds = if (resource.readable) setOf(resource.id) else emptySet(),
            ) { results ->
                if (results.any {
                        it.resourceId == resource.id &&
                            it.action == DownloadManagementAction.Open &&
                            it.outcome == DownloadManagementOutcome.Completed
                    }
                ) {
                    // The parent queues navigation until the real sheet hide
                    // callback has completed; this request only starts that
                    // dismissal after fresh Open validation succeeds.
                    dismissSheet()
                    onOpenDownloaded(record)
                }
            }
        }
        Column(Modifier.fillMaxWidth().fillMaxHeight()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = theme.components.page.compactGutter),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedButton(
                    onClick = {
                        if (selectionMode) {
                            selectionMode = false
                            selectedIdsList = emptyList()
                        } else dismissSheet()
                    },
                    enabled = !isSubmitting,
                    modifier = Modifier.testTag("download-panel-close"),
                ) {
                    Icon(Icons.Outlined.Check, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(stringResource(if (selectionMode) R.string.cancel_action else R.string.download_selection_done))
                }
                Column(Modifier.weight(1f)) {
                    Text(stringResource(R.string.book_download_title), style = theme.typography.sectionTitle)
                }
                if (selectionMode) {
                    OutlinedButton(
                        onClick = {
                            selectionMode = false
                            selectedIdsList = emptyList()
                        },
                        enabled = !isSubmitting,
                        modifier = Modifier.testTag("download-selection-cancel"),
                    ) {
                        Icon(Icons.Outlined.Check, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                        Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                        Text(stringResource(R.string.download_selection_done)) }
                } else {
                    OutlinedButton(
                        onClick = { selectionMode = true },
                        enabled = !isSubmitting && selectableIds.isNotEmpty(),
                        modifier = Modifier.testTag("download-selection-enter"),
                    ) {
                        Icon(Icons.Outlined.Checklist, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                        Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                        Text(stringResource(R.string.download_selection_action)) }
                }
            }
            HorizontalDivider(color = theme.colors.divider)

            if (actionResults.isNotEmpty()) {
                val accepted = actionResults.count { it.outcome == DownloadManagementOutcome.Accepted }
                val completed = actionResults.count { it.outcome == DownloadManagementOutcome.Completed }
                val skipped = actionResults.count { it.outcome == DownloadManagementOutcome.Skipped }
                val failed = actionResults.count { it.outcome == DownloadManagementOutcome.Failed }
                Column(
                    Modifier.fillMaxWidth()
                        .padding(horizontal = theme.components.page.compactGutter, vertical = theme.spacing.one)
                        .testTag("download-management-feedback"),
                ) {
                    Text(
                        listOfNotNull(
                            if (accepted > 0) stringResource(R.string.download_management_accepted, accepted) else null,
                            if (completed > 0) stringResource(R.string.download_management_completed, completed) else null,
                            if (skipped > 0) stringResource(R.string.download_management_skipped, skipped) else null,
                            if (failed > 0) stringResource(R.string.download_management_failed, failed) else null,
                        ).joinToString(" · "),
                        style = theme.typography.callout,
                        color = theme.colors.textSecondary,
                    )
                    actionResults.firstOrNull { it.outcome == DownloadManagementOutcome.Failed }
                        ?.failureCode?.let { code ->
                            Text(downloadFailureMessage(code), style = theme.typography.caption,
                                color = theme.colors.textSecondary)
                        }
                }
            }

            when {
                state.multiDownloadErrorCode != null && displayedResources.isEmpty() &&
                    state.multiDownloadScope != DownloadPanelScope.Resource ->
                    WarmPageErrorState(
                        title = stringResource(R.string.multi_download_error_title),
                        message = stringResource(R.string.multi_download_error_message),
                        retryLabel = stringResource(R.string.retry_action),
                        onRetry = { onRetryFolder(null) },
                        modifier = Modifier.fillMaxWidth().weight(1f),
                    )
                state.multiDownloadScope == DownloadPanelScope.Resource &&
                    state.isMultiDownloadResourcesLoading ->
                    WarmPageLoadingState(
                        title = stringResource(R.string.content_loading_title),
                        message = stringResource(R.string.multi_download_loading),
                        modifier = Modifier.fillMaxWidth().weight(1f),
                    )
                state.multiDownloadScope != DownloadPanelScope.Resource &&
                    state.multiDownloadRootNodeId == null ->
                    WarmPageLoadingState(
                        title = stringResource(R.string.content_loading_title),
                        message = stringResource(R.string.multi_download_loading),
                        modifier = Modifier.fillMaxWidth().weight(1f),
                    )
                else -> {
                    if (state.multiDownloadErrorCode != null) {
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = theme.components.page.compactGutter),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                stringResource(R.string.multi_download_known_records_warning),
                                color = theme.colors.textSecondary,
                                style = theme.typography.caption,
                                modifier = Modifier.weight(1f),
                            )
                            OutlinedButton(onClick = { onRetryFolder(null) }) {
                                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                                Text(stringResource(R.string.retry_action))
                            }
                        }
                    }
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().weight(1f),
                        verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
                    ) {
                        state.content?.book?.title
                            ?.takeIf(String::isNotBlank)
                            ?.let { title ->
                                item(key = "download-book-title") {
                                    Text(
                                        title,
                                        style = theme.typography.callout,
                                        color = theme.colors.textSecondary,
                                        maxLines = 1,
                                        modifier = Modifier.padding(horizontal = theme.components.page.compactGutter),
                                    )
                                }
                            }
                        if (state.multiDownloadScope == DownloadPanelScope.Resource) {
                            displayedResources.forEach { resource ->
                                item(key = "resource-${resource.id}") {
                                    DownloadResourceRow(
                                        resource = resource,
                                        management = managementById.getValue(resource.id),
                                        record = panelRecordsByResourceId[resource.id],
                                        depth = 0,
                                        selectionMode = selectionMode,
                                        selected = resource.id in scopedSelectedIds,
                                        isSubmitting = isSubmitting,
                                        onToggleSelection = {
                                            selectedIdsList = DownloadManagementPolicy.toggleSelection(
                                                scopedSelectedIds,
                                                setOf(resource.id),
                                                scopeManagement,
                                            ).sorted()
                                        },
                                        onSubmitAction = { action ->
                                            submitAction(
                                                action,
                                                setOf(resource.id),
                                                if (resource.readable) setOf(resource.id) else emptySet(),
                                            )
                                        },
                                        onRequestRemoval = { pendingRemovalIds = setOf(resource.id) },
                                        onOpenDownloaded = { recordValue -> requestOpen(resource, recordValue) },
                                    )
                                    HorizontalDivider(color = theme.colors.divider)
                                }
                            }
                        } else if (rows.isEmpty() && displayedResources.isNotEmpty()) {
                            // The tree can legitimately contain no entry rows
                            // while the loaded root still advertises resources
                            // (including a known snapshot after a network
                            // failure). Render those scoped resources directly.
                            displayedResources.forEach { resource ->
                                item(key = "fallback-resource-${resource.id}") {
                                    DownloadResourceRow(
                                        resource = resource,
                                        management = managementById.getValue(resource.id),
                                        record = panelRecordsByResourceId[resource.id],
                                        depth = 0,
                                        selectionMode = selectionMode,
                                        selected = resource.id in scopedSelectedIds,
                                        isSubmitting = isSubmitting,
                                        onToggleSelection = {
                                            selectedIdsList = DownloadManagementPolicy.toggleSelection(
                                                scopedSelectedIds,
                                                setOf(resource.id),
                                                scopeManagement,
                                            ).sorted()
                                        },
                                        onSubmitAction = { action ->
                                            submitAction(
                                                action,
                                                setOf(resource.id),
                                                if (resource.readable) setOf(resource.id) else emptySet(),
                                            )
                                        },
                                        onRequestRemoval = { pendingRemovalIds = setOf(resource.id) },
                                        onOpenDownloaded = { recordValue -> requestOpen(resource, recordValue) },
                                    )
                                    HorizontalDivider(color = theme.colors.divider)
                                }
                            }
                        } else {
                            items(rows, key = { it.entry.sourceNodeId }) { row ->
                                if (row.entry.isSourceFolder) {
                                    DownloadFolderRow(
                                        row = row,
                                        state = state,
                                        management = scopeManagement,
                                        selected = scopedSelectedIds,
                                        selectionMode = selectionMode,
                                        isSubmitting = isSubmitting,
                                        onToggleFolder = onToggleFolder,
                                        onEnsureFolderLoaded = onEnsureFolderLoaded,
                                        onRetryFolder = onRetryFolder,
                                        onToggleSelection = { candidates ->
                                            if (state.multiDownloadDescendantResourceIdsByNodeId[row.entry.sourceNodeId] == null) {
                                                pendingDirectorySelection = row.entry.sourceNodeId
                                                onEnsureFolderLoaded(row.entry.sourceNodeId)
                                            } else {
                                                selectedIdsList = DownloadManagementPolicy.toggleSelection(
                                                    scopedSelectedIds,
                                                    candidates,
                                                    scopeManagement,
                                                ).sorted()
                                            }
                                        },
                                    )
                                } else {
                                    val resource = row.entry.resourceId?.let(resourcesById::get)
                                    if (resource != null) {
                                        DownloadResourceRow(
                                            resource = resource,
                                            management = managementById.getValue(resource.id),
                                            record = panelRecordsByResourceId[resource.id],
                                            depth = row.depth,
                                            selectionMode = selectionMode,
                                            selected = resource.id in scopedSelectedIds,
                                            isSubmitting = isSubmitting,
                                            onToggleSelection = {
                                                selectedIdsList = DownloadManagementPolicy.toggleSelection(
                                                    scopedSelectedIds,
                                                    setOf(resource.id),
                                                    scopeManagement,
                                                ).sorted()
                                            },
                                            onSubmitAction = { action ->
                                                submitAction(
                                                    action,
                                                    setOf(resource.id),
                                                    if (resource.readable) setOf(resource.id) else emptySet(),
                                                )
                                            },
                                            onRequestRemoval = { pendingRemovalIds = setOf(resource.id) },
                                            onOpenDownloaded = { recordValue -> requestOpen(resource, recordValue) },
                                        )
                                    }
                                }
                                HorizontalDivider(color = theme.colors.divider)
                            }
                        }
                        if (displayedResources.isEmpty() && state.multiDownloadErrorCode == null) {
                            item {
                                Text(
                                    stringResource(R.string.multi_download_no_resources),
                                    color = theme.colors.textSecondary,
                                    modifier = Modifier.padding(theme.components.page.compactGutter),
                                )
                            }
                        }
                    }
                }
            }

            WarmPageSnackbarHost(feedbackHost)

            if (selectionMode) {
                SelectionBatchBar(
                    selected = scopedSelectedIds,
                    candidates = selectableIds,
                    resources = scopeManagement,
                    isSubmitting = isSubmitting,
                    onSelectAll = {
                        selectedIdsList = DownloadManagementPolicy.toggleSelection(
                            scopedSelectedIds,
                            selectableIds,
                            scopeManagement,
                        ).sorted()
                    },
                    onRequestRemoval = {
                        if (scopedSelectedIds.isNotEmpty()) pendingRemovalIds = scopedSelectedIds
                    },
                    onExecuteAction = { action ->
                        val applicable = DownloadManagementPolicy.applicable(
                            action,
                            scopedSelectedIds,
                            scopeManagement,
                        ).toSet()
                        submitAction(action, applicable, applicable.intersect(availableScopeIds))
                    },
                )
            }
        }
    }

    pendingRemovalIds?.let { ids ->
        val title = if (ids.size == 1) {
            stringResource(R.string.downloads_remove_title)
        } else {
            stringResource(R.string.multi_download_remove_title)
        }
        val message = if (ids.size == 1) {
            val resource = resourcesById[ids.first()]
            stringResource(R.string.downloads_remove_message, resource?.title ?: state.content?.book?.title.orEmpty())
        } else {
            pluralStringResource(R.plurals.multi_download_remove_message, ids.size, ids.size)
        }
        AlertDialog(
            onDismissRequest = { if (!isSubmitting) pendingRemovalIds = null },
            title = { Text(title) },
            text = { Text(message) },
            confirmButton = {
                OutlinedButton(
                    onClick = {
                        submitAction(
                            DownloadManagementAction.Remove,
                            ids,
                            ids.intersect(availableScopeIds),
                        )
                    },
                    enabled = !isSubmitting,
                ) {
                    Icon(Icons.Outlined.Delete, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(stringResource(R.string.downloads_remove_action)) }
            },
            dismissButton = {
                OutlinedButton(onClick = { pendingRemovalIds = null }, enabled = !isSubmitting) {
                    Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(stringResource(R.string.cancel_action))
                }
            },
        )
    }
}

@Composable
private fun DownloadFolderRow(
    row: MultiDownloadTreeRow,
    state: WorkDetailUiState,
    management: List<DownloadManagementResource>,
    selected: Set<String>,
    selectionMode: Boolean,
    isSubmitting: Boolean,
    onToggleFolder: (String) -> Unit,
    onEnsureFolderLoaded: (String) -> Unit,
    onRetryFolder: (String?) -> Unit,
    onToggleSelection: (Set<String>) -> Unit,
) {
    val theme = WarmPageThemeValues
    val nodeId = row.entry.sourceNodeId
    val descendantsLoaded = nodeId in state.multiDownloadDescendantResourceIdsByNodeId
    val descendants = state.multiDownloadDescendantResourceIdsByNodeId[nodeId].orEmpty()
    val mark = DownloadManagementPolicy.selectionMark(
        selected = selected,
        candidates = descendants,
        resources = management,
    )
    Column(
        Modifier.fillMaxWidth().padding(start = (row.depth * 20).dp, end = theme.components.page.compactGutter),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(
                onClick = { onToggleFolder(nodeId) },
                enabled = !isSubmitting,
                modifier = Modifier.size(theme.components.controls.minimumTouchTarget),
            ) {
                Icon(
                    if (nodeId in state.multiDownloadExpandedNodeIds) Icons.Filled.KeyboardArrowDown
                    else Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = stringResource(R.string.multi_download_toggle_folder),
                )
            }
            if (selectionMode) {
                Checkbox(
                    checked = mark == MultiDownloadSelectionMark.Selected,
                    onCheckedChange = { onToggleSelection(descendants) },
                    enabled = !descendantsLoaded ||
                        mark != MultiDownloadSelectionMark.Unselected ||
                        descendants.any { resourceId -> management.any { it.resourceId == resourceId && it.selectable } },
                    modifier = Modifier.testTag("download-folder-checkbox-$nodeId"),
                )
            }
            Column(Modifier.weight(1f).padding(vertical = theme.spacing.one)) {
                Text(row.entry.title, style = theme.typography.body)
                Text(
                    pluralStringResource(R.plurals.multi_download_volume_count, descendants.size, descendants.size),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                )
            }
        }
        state.multiDownloadNodeErrorCodes[nodeId]?.let { code ->
            Row(
                Modifier.fillMaxWidth().padding(start = 44.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    stringResource(R.string.multi_download_folder_error, code),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                    modifier = Modifier.weight(1f),
                )
                OutlinedButton(onClick = { onRetryFolder(nodeId) }) {
                    Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(stringResource(R.string.retry_action))
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun DownloadResourceRow(
    resource: ResourceContent,
    management: DownloadManagementResource,
    record: AndroidDownloadRecord?,
    depth: Int,
    selectionMode: Boolean,
    selected: Boolean,
    isSubmitting: Boolean,
    onToggleSelection: () -> Unit,
    onSubmitAction: (DownloadManagementAction) -> Unit,
    onRequestRemoval: () -> Unit,
    onOpenDownloaded: (AndroidDownloadRecord) -> Unit,
) {
    val theme = WarmPageThemeValues
    val rowAction = management.listAction
    val isDownloaded = management.status == com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Completed
    val useStackedActions = LocalDensity.current.fontScale >= MULTI_DOWNLOAD_STACKED_ACTION_FONT_SCALE
    val actionContent: @Composable RowScope.() -> Unit = {
        androidx.compose.material3.IconButton(
            onClick = {
                if (rowAction == DownloadManagementAction.Remove) onRequestRemoval()
                else rowAction?.let(onSubmitAction)
            },
            enabled = !isSubmitting && rowAction != null,
            modifier = Modifier.testTag("download-resource-primary-${resource.id}"),
        ) {
            Icon(
                if (isDownloaded) Icons.Outlined.Delete else Icons.Outlined.FileDownload,
                contentDescription = stringResource(if (isDownloaded) R.string.download_management_delete else R.string.work_quick_download),
            )
        }
    }
    val rowModifier = Modifier
        .fillMaxWidth()
        .clickable(
            enabled = !isSubmitting,
            onClick = {
                when {
                    selectionMode && management.selectable -> onToggleSelection()
                    !selectionMode && DownloadManagementAction.Open in management.actions && record != null ->
                        onOpenDownloaded(record)
                }
            },
        )
        .padding(
            start = theme.components.page.compactGutter + (depth * 20).dp,
            end = theme.components.page.compactGutter,
            top = theme.spacing.one,
            bottom = theme.spacing.one,
        )
    Row(rowModifier, verticalAlignment = Alignment.CenterVertically) {
        if (selectionMode) {
            Checkbox(
                checked = selected,
                onCheckedChange = { onToggleSelection() },
                enabled = management.selectable && !isSubmitting,
                modifier = Modifier.testTag("download-resource-checkbox-${resource.id}"),
            )
        }
        Column(Modifier.weight(1f)) {
            Text(resource.title, style = theme.typography.body)
            Text(
                listOfNotNull(
                    resource.format.takeIf(String::isNotBlank),
                    resource.sizeBytes.takeIf { it > 0 }?.let(::formatBytes),
                ).joinToString(" · "),
                style = theme.typography.caption,
                color = theme.colors.textSecondary,
            )
            if (management.status != com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Completed &&
                management.status != com.ermao.library.shared.modules.downloads.DownloadManagementStatus.NotDownloaded) {
                Text(
                    downloadManagementStatusLabel(management.status),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                    modifier = Modifier.testTag("download-resource-status-${resource.id}"),
                )
            }
            if (!selectionMode && useStackedActions) {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    actionContent()
                }
            }
        }
        if (!selectionMode && !useStackedActions) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                actionContent()
            }
        }
    }
}

@Composable
private fun SelectionBatchBar(
    selected: Set<String>,
    candidates: Set<String>,
    resources: List<DownloadManagementResource>,
    isSubmitting: Boolean,
    onSelectAll: () -> Unit,
    onRequestRemoval: () -> Unit,
    onExecuteAction: (DownloadManagementAction) -> Unit,
) {
    val theme = WarmPageThemeValues
    val mark = DownloadManagementPolicy.selectionMark(selected, candidates, resources)
    Column(
        Modifier.fillMaxWidth().padding(horizontal = theme.components.page.compactGutter, vertical = theme.spacing.one),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = onSelectAll, enabled = !isSubmitting) {
                Icon(Icons.Outlined.SelectAll, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(
                    stringResource(
                        if (mark == MultiDownloadSelectionMark.Selected) {
                            R.string.download_selection_clear_all
                        } else {
                            R.string.download_selection_select_all
                        },
                    ),
                )
            }
            Spacer(Modifier.weight(1f))
            Text(
                pluralStringResource(R.plurals.multi_download_selected_count, selected.size, selected.size),
                style = theme.typography.caption,
                color = theme.colors.textSecondary,
            )
        }
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(theme.spacing.half),
        ) {
            managementBatchActions.forEach { action ->
                val count = DownloadManagementPolicy.applicable(action, selected, resources).size
                WarmPageIconAction(
                    icon = downloadManagementActionIcon(action),
                    label = batchActionLabel(action, count),
                    onClick = if (action == DownloadManagementAction.Remove) onRequestRemoval else { { onExecuteAction(action) } },
                    enabled = !isSubmitting && count > 0,
                )
            }
        }
    }
}

private fun downloadManagementActionIcon(action: DownloadManagementAction): ImageVector = when (action) {
    DownloadManagementAction.Open -> Icons.AutoMirrored.Outlined.OpenInNew
    DownloadManagementAction.Download -> Icons.Outlined.Download
    DownloadManagementAction.Pause -> Icons.Outlined.Pause
    DownloadManagementAction.Resume -> Icons.Outlined.PlayArrow
    DownloadManagementAction.Retry -> Icons.Outlined.Refresh
    DownloadManagementAction.Remove -> Icons.Outlined.Delete
}

private val managementBatchActions = listOf(
    DownloadManagementAction.Download,
    DownloadManagementAction.Pause,
    DownloadManagementAction.Resume,
    DownloadManagementAction.Retry,
    DownloadManagementAction.Remove,
)

private val managementActionOrder = listOf(
    DownloadManagementAction.Open,
    DownloadManagementAction.Download,
    DownloadManagementAction.Pause,
    DownloadManagementAction.Resume,
    DownloadManagementAction.Retry,
    DownloadManagementAction.Remove,
)

private fun managementResource(
    resource: ResourceContent,
    record: AndroidDownloadRecord?,
    active: Boolean,
): DownloadManagementResource = DownloadManagementPolicy.project(
    downloadManagementItem(
        resourceId = resource.id,
        record = record,
        active = active,
        available = resource.readable,
    ),
)

/**
 * A local catalog row can outlive a failed or incomplete server refresh. Keep
 * it visible in the panel with unavailable server facts while preserving the
 * durable record for Open/Remove and status projection.
 */
private fun AndroidDownloadRecord.toPanelResource(): ResourceContent = ResourceContent(
    id = resourceId,
    sourceNodeId = "",
    title = resourceTitle.ifBlank { resourceId },
    format = format,
    readerType = readerType,
    coverUrl = coverUrl,
    sizeBytes = expectedBytes,
    progressPercent = null,
    readable = false,
    selected = false,
)

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
            } else listOf(row)
        }
    return children(rootNodeId, 0)
}

@Composable
private fun downloadManagementStatusLabel(
    status: com.ermao.library.shared.modules.downloads.DownloadManagementStatus,
): String = stringResource(
    when (status) {
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.NotDownloaded -> R.string.multi_download_not_downloaded
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Queued -> R.string.multi_download_queued
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Downloading -> R.string.multi_download_downloading
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Paused -> R.string.multi_download_paused
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Completed -> R.string.multi_download_downloaded
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.InvalidLocal -> R.string.multi_download_invalid_local
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.FailedRetryable -> R.string.multi_download_failed_retryable
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.FailedTerminal -> R.string.multi_download_failed_terminal
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Unavailable -> R.string.multi_download_unavailable
    },
)

@Composable
private fun downloadManagementActionLabel(action: DownloadManagementAction): String = stringResource(
    when (action) {
        DownloadManagementAction.Download -> R.string.multi_download_download
        DownloadManagementAction.Pause -> R.string.multi_download_pause
        DownloadManagementAction.Resume -> R.string.multi_download_resume
        DownloadManagementAction.Retry -> R.string.multi_download_retry
        DownloadManagementAction.Remove -> R.string.downloads_remove_action
        DownloadManagementAction.Open -> R.string.work_download_open_offline
    },
)

@Composable
private fun batchActionLabel(action: DownloadManagementAction, count: Int): String =
    stringResource(
        when (action) {
            DownloadManagementAction.Download -> R.string.multi_download_batch_download
            DownloadManagementAction.Pause -> R.string.multi_download_batch_pause
            DownloadManagementAction.Resume -> R.string.multi_download_batch_resume
            DownloadManagementAction.Retry -> R.string.multi_download_batch_retry
            DownloadManagementAction.Remove -> R.string.multi_download_batch_remove
            DownloadManagementAction.Open -> R.string.multi_download_batch_download
        },
        count,
    )

private const val MULTI_DOWNLOAD_STACKED_ACTION_FONT_SCALE = 1.3f

private fun formatBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024L * 1024L -> "%.1f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
    bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
    bytes >= 1024L -> "%.1f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}
