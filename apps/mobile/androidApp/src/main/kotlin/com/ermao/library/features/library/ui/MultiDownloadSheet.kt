package com.ermao.library.features.library.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
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
import androidx.compose.material.icons.outlined.Pause
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.SelectAll
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.LinearProgressIndicator
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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.platform.LocalConfiguration
import java.text.NumberFormat
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
import com.ermao.library.ui.components.WarmPageModalBottomSheet
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
            .fillMaxHeight()
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
                modifier = Modifier.fillMaxWidth()
                    .heightIn(min = theme.components.controls.minimumTouchTarget + theme.spacing.one)
                    .padding(horizontal = theme.spacing.one),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.weight(1f), contentAlignment = Alignment.CenterStart) {
                    if (selectionMode) {
                        TextButton(
                            onClick = { selectionMode = false; selectedIdsList = emptyList() },
                            enabled = !isSubmitting,
                            colors = ButtonDefaults.textButtonColors(contentColor = theme.colors.textSecondary),
                            contentPadding = PaddingValues(horizontal = theme.spacing.one),
                            modifier = Modifier.testTag("download-selection-cancel"),
                        ) {
                            Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                            Spacer(Modifier.size(theme.spacing.half))
                            Text(stringResource(R.string.cancel_action))
                        }
                    } else {
                        WarmPageIconAction(
                            icon = Icons.Outlined.Close, label = stringResource(R.string.close_action),
                            onClick = dismissSheet, enabled = !isSubmitting,
                            modifier = Modifier.testTag("download-panel-close"),
                        )
                    }
                }
                Text(
                    if (selectionMode) pluralStringResource(R.plurals.multi_download_selected_count, scopedSelectedIds.size, scopedSelectedIds.size)
                    else stringResource(R.string.book_download_title),
                    style = theme.typography.sectionTitle, textAlign = TextAlign.Center, maxLines = 2,
                    modifier = Modifier.weight(1.3f),
                )
                Box(Modifier.weight(1f), contentAlignment = Alignment.CenterEnd) {
                    TextButton(
                        onClick = {
                            if (selectionMode) {
                                selectedIdsList = DownloadManagementPolicy.toggleSelection(
                                    scopedSelectedIds, selectableIds, scopeManagement,
                                ).sorted()
                            } else selectionMode = true
                        },
                        enabled = !isSubmitting && (selectionMode || selectableIds.isNotEmpty()),
                        colors = ButtonDefaults.textButtonColors(contentColor = theme.colors.textSecondary),
                        contentPadding = PaddingValues(horizontal = theme.spacing.one),
                        modifier = Modifier.testTag(if (selectionMode) "download-selection-all" else "download-selection-enter"),
                    ) {
                        Icon(if (selectionMode) Icons.Outlined.SelectAll else Icons.Outlined.Checklist,
                            contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                        Spacer(Modifier.size(theme.spacing.half))
                        Text(stringResource(
                            if (!selectionMode) R.string.download_selection_action
                            else if (DownloadManagementPolicy.selectionMark(scopedSelectedIds, selectableIds, scopeManagement) == MultiDownloadSelectionMark.Selected)
                                R.string.download_selection_clear_all else R.string.download_selection_select_all,
                        ))
                    }
                }
            }

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
                            TextButton(colors = ButtonDefaults.textButtonColors(contentColor = theme.colors.textSecondary), onClick = { onRetryFolder(null) }) {
                                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                                Text(stringResource(R.string.retry_action))
                            }
                        }
                    }
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().weight(1f),
                        verticalArrangement = Arrangement.Top,
                    ) {
                        state.content?.book?.title
                            ?.takeIf(String::isNotBlank)
                            ?.let { title ->
                                item(key = "download-book-title") {
                                    DownloadBookTitle(title)
                                }
                            }
                        if (state.multiDownloadScope == DownloadPanelScope.Resource) {
                            displayedResources.forEach { resource ->
                                item(key = "resource-${resource.id}") {
                                    DownloadResourceRow(
                                        bookTitle = state.content?.book?.title.orEmpty(),
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
                                        bookTitle = state.content?.book?.title.orEmpty(),
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
                                            bookTitle = state.content?.book?.title.orEmpty(),
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
                                if (row.entry.isSourceFolder) HorizontalDivider(color = theme.colors.divider)
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
                HorizontalDivider(color = theme.colors.divider)
                SelectionBatchBar(
                    selected = scopedSelectedIds,
                    resources = scopeManagement,
                    selectedResources = panelResources.filter { it.id in scopedSelectedIds },
                    isSubmitting = isSubmitting,
                    onRequestRemoval = {
                        DownloadManagementPolicy.applicable(
                            DownloadManagementAction.Remove, scopedSelectedIds, scopeManagement,
                        ).toSet().takeIf { it.isNotEmpty() }?.let { pendingRemovalIds = it }
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
                TextButton(colors = ButtonDefaults.textButtonColors(contentColor = theme.colors.textSecondary),
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
                TextButton(colors = ButtonDefaults.textButtonColors(contentColor = theme.colors.textSecondary), onClick = { pendingRemovalIds = null }, enabled = !isSubmitting) {
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
                TextButton(colors = ButtonDefaults.textButtonColors(contentColor = theme.colors.textSecondary), onClick = { onRetryFolder(nodeId) }) {
                    Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(stringResource(R.string.retry_action))
                }
            }
        }
    }
}

@Composable
private fun DownloadBookTitle(title: String) {
    val theme = WarmPageThemeValues
    var expanded by rememberSaveable(title) { mutableStateOf(false) }
    var truncated by remember(title) { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(horizontal = theme.components.page.compactGutter, vertical = theme.spacing.two)) {
        Text(
            title, style = theme.typography.callout, color = theme.colors.textSecondary,
            maxLines = if (expanded) Int.MAX_VALUE else 2, overflow = TextOverflow.Ellipsis,
            onTextLayout = { if (!expanded) truncated = it.hasVisualOverflow },
        )
        if (expanded || truncated) {
            TextButton(
                onClick = { expanded = !expanded },
                colors = ButtonDefaults.textButtonColors(contentColor = theme.colors.textSecondary),
                modifier = Modifier.align(Alignment.End),
            ) {
                Text(stringResource(if (expanded) R.string.work_collapse else R.string.work_expand))
                Icon(if (expanded) Icons.Filled.KeyboardArrowDown else Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null)
            }
        }
    }
    HorizontalDivider(color = theme.colors.divider)
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
private fun DownloadResourceRow(
    bookTitle: String,
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
    val rowAction = management.primaryAction?.takeUnless { it == DownloadManagementAction.Open }
    val actionContent: @Composable RowScope.() -> Unit = {
        rowAction?.let { action ->
            WarmPageIconAction(
                icon = downloadManagementActionIcon(action),
                label = downloadManagementActionLabel(action),
                onClick = { onSubmitAction(action) },
                enabled = !isSubmitting,
                modifier = Modifier.testTag("download-resource-primary-${resource.id}"),
            )
        }
        if (DownloadManagementAction.Remove in management.actions) {
            WarmPageIconAction(
                icon = Icons.Outlined.Delete,
                label = stringResource(R.string.downloads_remove_action),
                onClick = onRequestRemoval,
                enabled = !isSubmitting,
                modifier = Modifier.testTag("download-resource-remove-${resource.id}"),
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
            start = (if (selectionMode) theme.spacing.one else theme.components.page.compactGutter) + (depth * 20).dp,
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
        Column(
            Modifier.weight(1f).heightIn(min = theme.components.controls.minimumTouchTarget),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                DownloadManagementPolicy.displayTitle(bookTitle, resource.title),
                style = theme.typography.body, maxLines = 1, softWrap = false, overflow = TextOverflow.Clip,
                modifier = Modifier.fillMaxWidth().testTag("download-resource-title-${resource.id}")
                    .semantics { contentDescription = resource.title },
            )
            Spacer(Modifier.size(theme.spacing.half))
            val showProgress = record != null && management.status in setOf(
                com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Downloading,
                com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Paused,
            )
            val progress = record?.takeIf { it.expectedBytes > 0 }?.let { (it.transferredBytes.toDouble() / it.expectedBytes).coerceIn(0.0, 1.0) }
            val locale = LocalConfiguration.current.locales[0]
            val status = downloadManagementStatusLabel(management.status)
            FlowRow(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.half),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
            ) {
            Text(
                listOfNotNull(
                    resource.format.takeIf(String::isNotBlank),
                    resource.sizeBytes.takeIf { it > 0 }?.let(::formatBytes),
                ).joinToString(" · ") + " ·",
                modifier = Modifier.alignByBaseline(),
                style = theme.typography.caption,
                color = theme.colors.textSecondary,
            )
            Row(modifier = Modifier.alignByBaseline(), verticalAlignment = Alignment.CenterVertically) {
                if (management.status == com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Completed) {
                    Icon(Icons.Outlined.Check, contentDescription = null, tint = theme.colors.textSecondary,
                        modifier = Modifier.size(with(LocalDensity.current) { theme.typography.caption.fontSize.toDp() }))
                    Spacer(Modifier.size(theme.spacing.half))
                }
                Text(
                    if (showProgress && progress != null) "$status · ${NumberFormat.getPercentInstance(locale).format(progress)}" else status,
                    style = theme.typography.caption, color = theme.colors.textSecondary,
                    modifier = Modifier.alignByBaseline().testTag("download-resource-status-${resource.id}"),
                )
            }
            }
            if (showProgress && progress != null) {
                LinearProgressIndicator(
                    progress = { progress.toFloat() },
                    modifier = Modifier.fillMaxWidth().padding(vertical = theme.spacing.half),
                    color = theme.colors.textSecondary,
                    trackColor = theme.colors.divider,
                )
            }
            if (management.status in setOf(
                    com.ermao.library.shared.modules.downloads.DownloadManagementStatus.FailedRetryable,
                    com.ermao.library.shared.modules.downloads.DownloadManagementStatus.FailedTerminal,
                    com.ermao.library.shared.modules.downloads.DownloadManagementStatus.InvalidLocal,
                )
            ) {
                record?.errorCode?.let { code ->
                    Text(downloadFailureMessage(code), style = theme.typography.caption, color = androidx.compose.material3.MaterialTheme.colorScheme.error)
                }
            }
        }
        if (!selectionMode) {
            Row(verticalAlignment = Alignment.CenterVertically) { actionContent() }
        }
    }
    HorizontalDivider(
        color = theme.colors.divider,
        modifier = Modifier.padding(
            start = (if (selectionMode) theme.spacing.one + theme.components.controls.minimumTouchTarget
                else theme.components.page.compactGutter) + (depth * 20).dp,
            end = theme.components.page.compactGutter,
        ),
    )
}

@Composable
private fun SelectionBatchBar(
    selected: Set<String>,
    resources: List<DownloadManagementResource>,
    selectedResources: List<ResourceContent>,
    isSubmitting: Boolean,
    onRequestRemoval: () -> Unit,
    onExecuteAction: (DownloadManagementAction) -> Unit,
) {
    val theme = WarmPageThemeValues
    val availableActions = managementBatchActions.filter {
        DownloadManagementPolicy.applicable(it, selected, resources).isNotEmpty()
    }
    val primary = availableActions.firstOrNull { it != DownloadManagementAction.Remove }
        ?: availableActions.firstOrNull() ?: DownloadManagementAction.Download
    val count = DownloadManagementPolicy.applicable(primary, selected, resources).size
    val secondary = availableActions.filter { it != primary }
    var moreExpanded by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxWidth().padding(horizontal = theme.components.page.compactGutter, vertical = theme.spacing.one),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        val sizesKnown = selected.isNotEmpty() && selectedResources.size == selected.size && selectedResources.all { it.sizeBytes > 0 }
        Text(
            if (selected.isEmpty()) stringResource(R.string.download_selection_hint)
            else listOfNotNull(
                pluralStringResource(R.plurals.multi_download_selected_count, selected.size, selected.size),
                if (sizesKnown) formatBytes(selectedResources.sumOf { it.sizeBytes }) else null,
            ).joinToString(" · "),
            style = theme.typography.caption,
            color = theme.colors.textSecondary,
        )
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
            OutlinedButton(
                colors = ButtonDefaults.outlinedButtonColors(
                    contentColor = theme.colors.textSecondary,
                    disabledContainerColor = theme.colors.navigation,
                    disabledContentColor = theme.colors.textTertiary,
                ),
                shape = RoundedCornerShape(theme.radii.control),
                border = BorderStroke(theme.components.dividerThickness,
                    if (!isSubmitting && count > 0) theme.colors.textTertiary else theme.colors.divider),
                onClick = { if (primary == DownloadManagementAction.Remove) onRequestRemoval() else onExecuteAction(primary) },
                enabled = !isSubmitting && count > 0,
                modifier = Modifier.weight(1f).heightIn(min = theme.components.controls.actionMinimumHeight)
                    .testTag("download-batch-primary"),
            ) {
                Icon(downloadManagementActionIcon(primary), contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(batchActionLabel(primary, count))
            }
            if (secondary.isNotEmpty()) {
                Box {
                    WarmPageIconAction(Icons.Outlined.MoreVert, stringResource(R.string.work_quick_more),
                        onClick = { moreExpanded = true }, enabled = !isSubmitting)
                    DropdownMenu(expanded = moreExpanded, onDismissRequest = { moreExpanded = false }) {
                        secondary.forEach { action ->
                            DropdownMenuItem(
                                text = { Text(batchActionLabel(action, DownloadManagementPolicy.applicable(action, selected, resources).size)) },
                                leadingIcon = { Icon(downloadManagementActionIcon(action), contentDescription = null) },
                                onClick = {
                                    moreExpanded = false
                                    if (action == DownloadManagementAction.Remove) onRequestRemoval() else onExecuteAction(action)
                                },
                            )
                        }
                    }
                }
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


private fun formatBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024L * 1024L -> "%.1f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
    bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
    bytes >= 1024L -> "%.1f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}
