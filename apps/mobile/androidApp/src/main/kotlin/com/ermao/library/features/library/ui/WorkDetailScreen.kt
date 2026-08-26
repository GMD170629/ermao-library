package com.ermao.library.features.library.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.background
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudDownload
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.PauseCircle
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Source
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material3.Checkbox
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.foundation.text.selection.SelectionContainer
import android.text.Html
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntOffset
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.ermao.library.R
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.ui.ContentCover
import com.ermao.library.features.content.ui.CoverProgress
import com.ermao.library.features.content.ui.CoverRole
import com.ermao.library.features.content.ui.ReadingProgressTrack
import com.ermao.library.features.content.ui.BookCover
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.shared.modules.library.BookContentSort
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.BookDetailPresentation
import com.ermao.library.shared.modules.library.ResourceReadingUnitsPage
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.ui.components.WarmPageChoice
import com.ermao.library.ui.components.WarmPageEmptyState
import com.ermao.library.ui.components.WarmPageErrorState
import com.ermao.library.ui.components.WarmPageLoadingState
import com.ermao.library.ui.components.WarmPageModalBottomSheet
import com.ermao.library.ui.components.WarmPageNavigationAction
import com.ermao.library.ui.components.WarmPagePrimaryAction
import com.ermao.library.ui.components.WarmPageScaffold
import com.ermao.library.ui.components.WarmPageSecondaryAction
import com.ermao.library.ui.components.WarmPageSectionHeader
import com.ermao.library.ui.components.WarmPageSegmentedControl
import com.ermao.library.ui.components.WarmPageSnackbarHost
import com.ermao.library.ui.components.WarmPageTextAction
import com.ermao.library.ui.components.WarmPageFloatingActionMenu
import com.ermao.library.ui.components.WarmPageFloatingMenuAction
import com.ermao.library.ui.components.WarmPageTopBarRole
import com.ermao.library.ui.components.warmPageActionHorizontalPadding
import com.ermao.library.ui.theme.WarmPageThemeValues
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.isSupportedNativeReaderEntry
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.shared.modules.downloads.DownloadBatchResult
import com.ermao.library.features.workmanagement.application.WorkManagementViewModel
import com.ermao.library.features.workmanagement.application.WorkManagementCompletion
import com.ermao.library.features.workmanagement.ui.WorkManagementTarget
import com.ermao.library.features.workmanagement.ui.WorkManagementTask
import com.ermao.library.features.workmanagement.ui.WorkManagementTaskSheet
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.util.Locale
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import androidx.compose.runtime.snapshotFlow

private sealed interface WorkControlMenuTarget {
    data object Book : WorkControlMenuTarget
    data class Resource(val value: ResourceContent) : WorkControlMenuTarget
}

private data class WorkControlMenuState(
    val target: WorkControlMenuTarget,
    val anchorInWindow: Offset,
)

private data class WorkManagementSheetState(
    val task: WorkManagementTask,
    val target: WorkManagementTarget,
)

private enum class BookControlAction {
    Edit, RegenerateCover, Recognize, Rescan, Delete,
}

private enum class VolumeControlAction {
    MarkUnread, Download, Edit, SendToKindle,
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkDetailScreen(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
    onBack: () -> Unit,
    onSelectResource: (String) -> Unit,
    onShowContentBrowser: () -> Unit,
    onOpenSourceNode: (String?) -> Unit,
    onSelectContentsSort: (BookContentSort) -> Unit,
    onSelectContentsPage: (Int) -> Unit,
    onSelectReadingUnitsPage: (Int) -> Unit,
    onRetrySurface: () -> Unit,
    onOpenShelfPicker: () -> Unit,
    onDismissShelfPicker: () -> Unit,
    onToggleShelf: (String) -> Unit,
    onSaveShelves: () -> Unit,
    onShelfSaveFeedbackShown: () -> Unit,
    onViewShelves: () -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    onRetry: () -> Unit,
    onRefresh: () -> Unit = {},
    downloadRecordsByResource: Map<String, AndroidDownloadRecord> = emptyMap(),
    downloadFailuresByResource: Map<String, String> = emptyMap(),
    onDownloadResource: (String) -> Unit = {},
    onCancelDownload: (String) -> Unit = {},
    onRemoveDownload: (AndroidDownloadRecord) -> Unit = {},
    onOpenMultiDownload: () -> Unit = {},
    onDismissMultiDownload: () -> Unit = {},
    onRetryMultiDownload: () -> Unit = {},
    onToggleMultiDownloadFolder: (String) -> Unit = {},
    onEnsureMultiDownloadFolderLoaded: (String) -> Unit = {},
    onPerformDownloadBatch: (Set<String>, (DownloadBatchResult) -> Unit) -> Unit = { _, completion ->
        completion(DownloadBatchResult(emptyList()))
    },
    onOpenSelectedResource: (ResourceContent) -> Unit = {},
    onSelectReadingStatus: (WorkReadingStatus) -> Unit = {},
    managementViewModel: WorkManagementViewModel? = null,
    canManageSystem: Boolean = managementViewModel != null,
    onBookDeleted: () -> Unit = {},
) {
    var controlMenuState by remember { mutableStateOf<WorkControlMenuState?>(null) }
    var managementSheetState by remember { mutableStateOf<WorkManagementSheetState?>(null) }
    val selectedResource = state.resolveSelectedResource()
    var readingStatusOverride by remember(state.content?.book?.id, selectedResource?.id) {
        mutableStateOf<WorkReadingStatus?>(null)
    }
    var pendingDownloadRemoval by remember { mutableStateOf<AndroidDownloadRecord?>(null) }
    val snackbarHostState = remember { SnackbarHostState() }
    val snackbarScope = rememberCoroutineScope()
    val shelvesUpdatedMessage = stringResource(R.string.work_shelves_updated)
    val managementUpdatedMessage = stringResource(R.string.management_updated)
    val readingStatusUpdatedMessage = stringResource(R.string.work_reading_status_updated)
    val coverUpdatedMessage = stringResource(R.string.management_cover_updated)
    val rescanQueuedMessage = stringResource(R.string.management_rescan_queued)
    val metadataAppliedMessage = stringResource(R.string.management_metadata_applied)
    val downloadQueuedMessage = stringResource(R.string.work_download_queued)
    val downloadPausedMessage = stringResource(R.string.work_download_paused)
    val viewShelvesLabel = stringResource(R.string.view_shelves_action)
    val shelfPickerSheetStrings = ShelfPickerSheetStrings(
        title = stringResource(R.string.work_shelf_picker_title),
        loadFailed = stringResource(R.string.work_shelf_load_failed),
        cancel = stringResource(R.string.cancel_action),
        empty = stringResource(R.string.work_shelf_empty),
        save = stringResource(R.string.work_shelf_save),
    )
    val currentReadingStatus = readingStatusOverride ?: selectedResource?.let { resource ->
        workReadingStatus(
            completed = state.content?.completed == true || (resource.progressPercent ?: 0) >= 100,
            progressPercent = resource.progressPercent,
        )
    } ?: WorkReadingStatus.Unread
    val managementState by managementViewModel?.uiState?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf(null) }
    val managementFailureMessage = stringResource(
        R.string.management_failed,
        managementState?.errorCode.orEmpty(),
    )
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { onRefresh() }
    val selectedDownloadFailure = selectedResource?.let { downloadFailuresByResource[it.id] }
    val downloadFailureMessage = if (selectedDownloadFailure == "DOWNLOAD_BOOTSTRAP_INVALID") {
        stringResource(R.string.download_bootstrap_invalid)
    } else {
        stringResource(
            R.string.work_download_failed,
            selectedDownloadFailure.orEmpty(),
        )
    }
    LaunchedEffect(selectedResource?.id, selectedDownloadFailure) {
        if (selectedDownloadFailure != null) {
            snackbarHostState.currentSnackbarData?.dismiss()
            snackbarHostState.showSnackbar(downloadFailureMessage)
        }
    }
    LaunchedEffect(state.shelfSaveCompleted) {
        if (state.shelfSaveCompleted) {
            snackbarHostState.currentSnackbarData?.dismiss()
            snackbarScope.launch {
                val result = snackbarHostState.showSnackbar(
                    message = shelvesUpdatedMessage,
                    actionLabel = viewShelvesLabel,
                    withDismissAction = true,
                    duration = SnackbarDuration.Short,
                )
                if (result == SnackbarResult.ActionPerformed) onViewShelves()
            }
            onShelfSaveFeedbackShown()
        }
    }
    val theme = WarmPageThemeValues
    val detailListState = rememberLazyListState()
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(theme.colors.canvas)
            .testTag("work-detail"),
    ) {
        WarmPageScaffold(
            role = WarmPageTopBarRole.Detail,
            title = stringResource(R.string.work_detail_title),
            modifier = Modifier.fillMaxSize(),
            navigation = WarmPageNavigationAction(
                icon = Icons.AutoMirrored.Filled.ArrowBack,
                label = stringResource(R.string.navigate_back),
                onClick = onBack,
            ),
            actions = emptyList(),
            snackbarHost = { WarmPageSnackbarHost(snackbarHostState) },
            containerColor = Color.Transparent,
            topBarContainerColor = Color.Transparent,
        ) { padding ->
            when {
                state.isLoading -> WarmPageLoadingState(
                    title = stringResource(R.string.content_loading_title),
                    message = stringResource(R.string.work_detail_loading_message),
                    modifier = Modifier.padding(padding).fillMaxSize(),
                )
                state.content == null -> WarmPageErrorState(
                    title = stringResource(R.string.work_unavailable_title),
                    message = stringResource(R.string.work_unavailable_message),
                    modifier = Modifier.padding(padding).fillMaxSize(),
                    retryLabel = stringResource(R.string.retry_action),
                    onRetry = onRetry,
                )
                else -> WorkDetailBody(
                    state = state,
                    repository = repository,
                    context = context,
                    onSelectResource = onSelectResource,
                    onShowContentBrowser = onShowContentBrowser,
                    onOpenSourceNode = onOpenSourceNode,
                    onSelectContentsSort = onSelectContentsSort,
                    onSelectContentsPage = onSelectContentsPage,
                    onSelectReadingUnitsPage = onSelectReadingUnitsPage,
                    onRetrySurface = onRetrySurface,
                    onOpenShelfPicker = onOpenShelfPicker,
                    readingStatus = currentReadingStatus,
                    readingStatusBusy = managementState?.isBusy == true,
                    onToggleReadingStatus = {
                        val next = nextWorkReadingStatus(currentReadingStatus)
                        readingStatusOverride = next
                        val managedStatus = if (next == WorkReadingStatus.Finished) {
                            ManagedReadingStatus.Finished
                        } else {
                            ManagedReadingStatus.Unread
                        }
                        if (selectedResource != null && managementViewModel != null) {
                            managementViewModel.setReadingStatus(managedStatus)
                        } else {
                            onSelectReadingStatus(next)
                        }
                    },
                    onOpenBookControl = { anchor ->
                        controlMenuState = WorkControlMenuState(WorkControlMenuTarget.Book, anchor)
                    },
                    onOpenFacet = onOpenFacet,
                    downloadRecordsByResource = downloadRecordsByResource,
                    downloadFailuresByResource = downloadFailuresByResource,
                    onDownloadResource = { resourceId ->
                        if (state.content.resources.count(ResourceContent::readable) > 1) {
                            onOpenMultiDownload()
                        } else {
                            onDownloadResource(resourceId)
                            snackbarScope.launch {
                                snackbarHostState.currentSnackbarData?.dismiss()
                                snackbarHostState.showSnackbar(downloadQueuedMessage)
                            }
                        }
                    },
                    onCancelDownload = { resourceId ->
                        onCancelDownload(resourceId)
                        snackbarScope.launch {
                            snackbarHostState.currentSnackbarData?.dismiss()
                            snackbarHostState.showSnackbar(downloadPausedMessage)
                        }
                    },
                    onRequestRemoveDownload = { pendingDownloadRemoval = it },
                    onOpenSelectedResource = onOpenSelectedResource,
                    onOpenMultiDownload = onOpenMultiDownload,
                    onOpenResourceControl = { resource, anchor ->
                        controlMenuState = WorkControlMenuState(WorkControlMenuTarget.Resource(resource), anchor)
                    },
                    listState = detailListState,
                    modifier = Modifier.padding(padding),
                )
            }
        }
    }

    pendingDownloadRemoval?.let { download ->
        AlertDialog(
            onDismissRequest = { pendingDownloadRemoval = null },
            title = { Text(stringResource(R.string.downloads_remove_title)) },
            text = { Text(stringResource(R.string.downloads_remove_message, download.resourceTitle)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        pendingDownloadRemoval = null
                        onRemoveDownload(download)
                    },
                ) { Text(stringResource(R.string.downloads_remove_action)) }
            },
            dismissButton = {
                TextButton(onClick = { pendingDownloadRemoval = null }) {
                    Text(stringResource(R.string.cancel_action))
                }
            },
        )
    }
    if (controlMenuState != null && state.content != null) {
        val activeMenu = requireNotNull(controlMenuState)
        WorkDetailControlMenu(
            target = activeMenu.target,
            anchorInWindow = activeMenu.anchorInWindow,
            content = state.content,
            selectedResource = selectedResource,
            repository = repository,
            context = context,
            canManageSystem = canManageSystem && managementViewModel != null,
            selectedDownload = when (val target = activeMenu.target) {
                WorkControlMenuTarget.Book -> selectedResource?.let { downloadRecordsByResource[it.id] }
                is WorkControlMenuTarget.Resource -> downloadRecordsByResource[target.value.id]
            },
            onAddShelf = {
                controlMenuState = null
                onOpenShelfPicker()
            },
            onMarkUnread = { resource ->
                controlMenuState = null
                readingStatusOverride = WorkReadingStatus.Unread
                if (managementViewModel != null) {
                    managementViewModel.setReadingStatus(ManagedReadingStatus.Unread)
                } else {
                    onSelectReadingStatus(WorkReadingStatus.Unread)
                }
            },
            onDownload = { resource ->
                controlMenuState = null
                val download = downloadRecordsByResource[resource.id]
                when {
                    download?.isReadable == true -> onRemoveDownload(download)
                    download?.status in setOf(
                        AndroidDownloadStatus.Queued,
                        AndroidDownloadStatus.Downloading,
                        AndroidDownloadStatus.Verifying,
                    ) -> onCancelDownload(resource.id)
                    else -> onDownloadResource(resource.id)
                }
            },
            onBookTask = bookTask@{ action ->
                controlMenuState = null
                val task = when (action) {
                    BookControlAction.Edit -> WorkManagementTask.EditWork
                    BookControlAction.Recognize -> WorkManagementTask.Recognize
                    BookControlAction.RegenerateCover -> WorkManagementTask.Cover
                    BookControlAction.Rescan -> WorkManagementTask.Rescan
                    BookControlAction.Delete -> WorkManagementTask.Delete
                }
                managementSheetState = WorkManagementSheetState(task, WorkManagementTarget.Work)
            },
            onResourceTask = resourceTask@{ action, resource ->
                controlMenuState = null
                val task = when (action) {
                    VolumeControlAction.Edit -> WorkManagementTask.EditVolume
                    VolumeControlAction.SendToKindle -> WorkManagementTask.Kindle
                    VolumeControlAction.MarkUnread,
                    VolumeControlAction.Download,
                    -> return@resourceTask
                }
                managementSheetState = WorkManagementSheetState(task, WorkManagementTarget.Resource(resource))
            },
            onDismiss = { controlMenuState = null },
        )
    }
    val activeManagementSheet = managementSheetState
    val activeManagementState = managementState
    if (activeManagementSheet != null && state.content != null && activeManagementState != null && managementViewModel != null) {
        WorkManagementTaskSheet(
            task = activeManagementSheet.task,
            target = activeManagementSheet.target,
            content = state.content,
            state = activeManagementState,
            viewModel = managementViewModel,
            onDismiss = { managementSheetState = null },
        )
    }
    LaunchedEffect(managementState?.completedMutation) {
        val completion = managementState?.completedMutation ?: return@LaunchedEffect
        managementSheetState = null
        if (completion == WorkManagementCompletion.BookDeleted) onBookDeleted() else onRefresh()
        snackbarHostState.currentSnackbarData?.dismiss()
        snackbarHostState.showSnackbar(
            when (completion) {
                WorkManagementCompletion.ReadingStatusUpdated -> readingStatusUpdatedMessage
                WorkManagementCompletion.CoverUpdated -> coverUpdatedMessage
                WorkManagementCompletion.RescanQueued -> rescanQueuedMessage
                WorkManagementCompletion.MetadataApplied -> metadataAppliedMessage
                else -> managementUpdatedMessage
            },
        )
        managementViewModel?.consumeFeedback()
    }
    LaunchedEffect(managementState?.errorCode) {
        val errorCode = managementState?.errorCode ?: return@LaunchedEffect
        readingStatusOverride = null
        snackbarHostState.currentSnackbarData?.dismiss()
        snackbarHostState.showSnackbar(managementFailureMessage)
        managementViewModel?.consumeFeedback()
    }
    if (state.isShelfPickerVisible) {
        ShelfPickerSheet(
            state = state,
            strings = shelfPickerSheetStrings,
            onDismiss = onDismissShelfPicker,
            onToggleShelf = onToggleShelf,
            onSave = onSaveShelves,
        )
    }
    if (state.isMultiDownloadVisible) {
        val resources = LocalResources.current
        val multiDownloadPartial = stringResource(R.string.multi_download_partial)
        MultiDownloadSheet(
            state = state,
            recordsByResource = downloadRecordsByResource,
            onDismiss = onDismissMultiDownload,
            onRetryTree = onRetryMultiDownload,
            onToggleFolder = onToggleMultiDownloadFolder,
            onEnsureFolderLoaded = onEnsureMultiDownloadFolderLoaded,
            onPause = onCancelDownload,
            onResumeOrRetry = onDownloadResource,
            onRemove = { pendingDownloadRemoval = it },
            onPerformBatch = onPerformDownloadBatch,
            onBatchFeedback = { succeeded, failed ->
                snackbarScope.launch {
                    snackbarHostState.currentSnackbarData?.dismiss()
                    snackbarHostState.showSnackbar(
                        if (failed == 0) {
                            resources.getQuantityString(
                                R.plurals.multi_download_completed,
                                succeeded,
                                succeeded,
                            )
                        } else {
                            multiDownloadPartial.format(succeeded, failed)
                        },
                    )
                }
            },
        )
    }
}

@Composable
private fun WorkDetailBody(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onSelectResource: (String) -> Unit,
    onShowContentBrowser: () -> Unit,
    onOpenSourceNode: (String?) -> Unit,
    onSelectContentsSort: (BookContentSort) -> Unit,
    onSelectContentsPage: (Int) -> Unit,
    onSelectReadingUnitsPage: (Int) -> Unit,
    onRetrySurface: () -> Unit,
    onOpenShelfPicker: () -> Unit,
    readingStatus: WorkReadingStatus,
    readingStatusBusy: Boolean,
    onToggleReadingStatus: () -> Unit,
    onOpenBookControl: (Offset) -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    downloadRecordsByResource: Map<String, AndroidDownloadRecord>,
    downloadFailuresByResource: Map<String, String>,
    onDownloadResource: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    onRequestRemoveDownload: (AndroidDownloadRecord) -> Unit,
    onOpenSelectedResource: (ResourceContent) -> Unit,
    onOpenMultiDownload: () -> Unit,
    onOpenResourceControl: (ResourceContent, Offset) -> Unit,
    listState: LazyListState,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    val content = requireNotNull(state.content)
    val selectedResource = state.resolveSelectedResource()
    LazyColumn(
        state = listState,
        modifier = modifier
            .fillMaxSize()
            .testTag("work-detail-list"),
        contentPadding = PaddingValues(
            start = theme.components.page.compactGutter,
            top = theme.components.page.compactGutter,
            end = theme.components.page.compactGutter,
            bottom = theme.components.page.contentBottomInset,
        ),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
    ) {
        item {
            Box(Modifier.testTag("work-identity")) {
                IdentityHeader(content, repository, context, onOpenFacet)
            }
        }
        item {
            WorkDetailActionRow(
                selectedResource = selectedResource,
                selectedDownload = selectedResource?.let { resource -> downloadRecordsByResource[resource.id] },
                hasMultipleReadableResources = content.resources.count(ResourceContent::readable) > 1,
                onOpenShelfPicker = onOpenShelfPicker,
                readingStatus = readingStatus,
                readingStatusBusy = readingStatusBusy,
                onToggleReadingStatus = onToggleReadingStatus,
                onOpenBookControl = onOpenBookControl,
                onDownloadResource = onDownloadResource,
                onCancelDownload = onCancelDownload,
                onRequestRemoveDownload = onRequestRemoveDownload,
                onOpenSelectedResource = onOpenSelectedResource,
                onOpenMultiDownload = onOpenMultiDownload,
            )
        }
        if (content.hasDescription) item { WorkAboutSection(content) }
        if (content.resources.none(ResourceContent::readable)) {
            item {
                WarmPageEmptyState(
                    title = stringResource(R.string.work_no_readable_resources),
                    message = stringResource(R.string.work_no_readable_resources_message),
                )
            }
        } else if (state.presentation == BookDetailPresentation.ContentBrowser) {
            item {
                WorkContentBrowser(
                    page = state.contents,
                    resources = content.resources,
                    sort = state.contentsSort,
                    loading = state.isSurfaceLoading,
                    errorCode = state.surfaceErrorCode,
                    repository = repository,
                    context = context,
                    onSelectResource = onSelectResource,
                    onOpenSourceNode = onOpenSourceNode,
                    onSelectSort = onSelectContentsSort,
                    onSelectPage = onSelectContentsPage,
                    onRetry = onRetrySurface,
                )
            }
        } else {
            selectedResource?.let { resource ->
                item {
                    WorkResourceDetail(
                        resource = resource,
                        page = state.readingUnits,
                        loading = state.isSurfaceLoading,
                        errorCode = state.surfaceErrorCode,
                        canReturnToContents = content.resources.count(ResourceContent::readable) > 1,
                        repository = repository,
                        context = context,
                        onBack = onShowContentBrowser,
                        onOpenResource = { onOpenSelectedResource(resource) },
                        onSelectPage = onSelectReadingUnitsPage,
                        onRetry = onRetrySurface,
                    )
                }
            }
        }
    }
}

@Composable
private fun WorkDetailActionRow(
    selectedResource: ResourceContent?,
    selectedDownload: AndroidDownloadRecord?,
    hasMultipleReadableResources: Boolean,
    onOpenShelfPicker: () -> Unit,
    readingStatus: WorkReadingStatus,
    readingStatusBusy: Boolean,
    onToggleReadingStatus: () -> Unit,
    onOpenBookControl: (Offset) -> Unit,
    onDownloadResource: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    onRequestRemoveDownload: (AndroidDownloadRecord) -> Unit,
    onOpenSelectedResource: (ResourceContent) -> Unit,
    onOpenMultiDownload: () -> Unit,
) {
    val theme = WarmPageThemeValues
    val primaryAction = workDetailPrimaryActionPresentation(
        selectedResource = selectedResource,
        download = selectedDownload,
    )
    val primaryLabel = primaryActionLabel(primaryAction.label)
    val downloadAction = workDetailDownloadActionPresentation(selectedDownload)
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        WarmPagePrimaryAction(
            label = primaryLabel,
            trailingIcon = Icons.Filled.PlayArrow,
            onClick = {
                selectedResource?.let { resource ->
                    when (primaryAction.intent) {
                        WorkDetailPrimaryActionIntent.OpenSelectedVolume -> onOpenSelectedResource(resource)
                        WorkDetailPrimaryActionIntent.Unavailable,
                        -> Unit
                    }
                }
            },
            enabled = primaryAction.enabled,
            modifier = Modifier.fillMaxWidth().testTag("work-reader-action"),
        )
        Row(Modifier.fillMaxWidth()) {
            WorkDetailQuickAction(
                icon = when (downloadAction) {
                    WorkDetailDownloadAction.Downloading -> Icons.Outlined.PauseCircle
                    WorkDetailDownloadAction.Downloaded -> Icons.Outlined.CheckCircle
                    WorkDetailDownloadAction.NotDownloaded,
                    WorkDetailDownloadAction.Paused,
                    WorkDetailDownloadAction.Failed,
                    -> Icons.Outlined.Download
                },
                label = stringResource(
                    when (downloadAction) {
                        WorkDetailDownloadAction.NotDownloaded -> R.string.work_quick_download
                        WorkDetailDownloadAction.Downloading -> R.string.work_quick_downloading
                        WorkDetailDownloadAction.Paused -> R.string.work_quick_download_paused
                        WorkDetailDownloadAction.Failed -> R.string.work_quick_download_retry
                        WorkDetailDownloadAction.Downloaded -> R.string.work_quick_downloaded
                    },
                ),
                onClick = {
                    if (selectedResource == null && hasMultipleReadableResources) {
                        onOpenMultiDownload()
                    } else selectedResource?.let { resource ->
                        when (downloadAction) {
                            WorkDetailDownloadAction.Downloading -> onCancelDownload(resource.id)
                            WorkDetailDownloadAction.NotDownloaded,
                            WorkDetailDownloadAction.Paused,
                            WorkDetailDownloadAction.Failed,
                            -> onDownloadResource(resource.id)
                            WorkDetailDownloadAction.Downloaded -> selectedDownload?.let(onRequestRemoveDownload)
                        }
                    }
                },
                onLongClick = selectedDownload?.takeIf { it.isReadable }?.let { download ->
                    { onRequestRemoveDownload(download) }
                },
                longClickLabel = stringResource(R.string.work_quick_remove_download),
                enabled = (selectedResource != null || hasMultipleReadableResources) && !readingStatusBusy,
                modifier = Modifier.weight(1f),
                testTag = "work-download-action",
            )
            WorkDetailQuickAction(
                icon = Icons.Outlined.Check,
                label = stringResource(
                    if (readingStatus == WorkReadingStatus.Finished) {
                        R.string.work_quick_reading_read
                    } else {
                        R.string.work_quick_reading_unread
                    },
                ),
                onClick = onToggleReadingStatus,
                enabled = selectedResource != null && !readingStatusBusy,
                modifier = Modifier.weight(1f),
                testTag = "work-reading-status-action",
            )
            WorkDetailQuickAction(
                icon = Icons.Outlined.BookmarkBorder,
                label = stringResource(R.string.work_quick_add),
                onClick = onOpenShelfPicker,
                modifier = Modifier.weight(1f),
                testTag = "work-shelf-action",
            )
            WorkDetailQuickAction(
                icon = Icons.Outlined.MoreVert,
                label = stringResource(R.string.work_quick_more),
                onClick = {},
                onClickAt = onOpenBookControl,
                modifier = Modifier.weight(1f),
                testTag = "work-more-action",
            )
        }
        val captionResource = when {
            selectedResource?.readerType.equals("audio", ignoreCase = true) -> R.string.work_audiobook_player_unavailable
            selectedResource == null -> R.string.work_reader_next_phase_message
            !isSupportedNativeReaderEntry(selectedResource.readerType, selectedResource.format) ->
                R.string.work_reader_renderer_pending
            else -> null
        }
        captionResource?.let { resource ->
            Text(
                stringResource(resource),
                style = theme.typography.caption,
                color = theme.colors.textSecondary,
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun WorkDetailQuickAction(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    onClickAt: ((Offset) -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
    longClickLabel: String? = null,
    enabled: Boolean = true,
    testTag: String? = null,
) {
    val theme = WarmPageThemeValues
    var positionInWindow by remember { mutableStateOf(Offset.Zero) }
    var measuredSize by remember { mutableStateOf(androidx.compose.ui.unit.IntSize.Zero) }
    Column(
        modifier = modifier
            .heightIn(min = theme.metrics.androidMinimumTouchTarget)
            .onGloballyPositioned { coordinates ->
                positionInWindow = coordinates.positionInWindow()
                measuredSize = coordinates.size
            }
            .combinedClickable(
                enabled = enabled,
                onClick = {
                    val anchoredClick = onClickAt
                    if (anchoredClick == null) {
                        onClick()
                    } else {
                        anchoredClick(
                            positionInWindow + Offset(
                                measuredSize.width / 2f,
                                measuredSize.height / 2f,
                            ),
                        )
                    }
                },
                onLongClick = onLongClick,
                onLongClickLabel = longClickLabel,
            )
            .then(if (testTag == null) Modifier else Modifier.testTag(testTag)),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (enabled) theme.colors.textPrimary else theme.colors.textTertiary,
            modifier = Modifier.size(28.dp),
        )
        Spacer(Modifier.height(theme.spacing.half))
        Text(
            text = label,
            style = theme.typography.caption,
            color = if (enabled) theme.colors.textSecondary else theme.colors.textTertiary,
        )
    }
}

@Composable
private fun IdentityHeader(
    content: BookDetailContent,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenFacet: (LibraryScope, String) -> Unit,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
    ) {
        BookCover(
            content.book,
            repository,
            context,
            CoverRole.Hero,
            Modifier.width(theme.components.workDetail.heroCoverWidth),
        )
        WorkIdentityText(content, onOpenFacet, Modifier.fillMaxWidth())
        ReadingSummary(content)
    }
}

@Composable
internal fun WorkDetailHeroRow(
    cover: @Composable RowScope.() -> Unit,
    identity: @Composable RowScope.() -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
        verticalAlignment = Alignment.Top,
    ) {
        cover()
        identity()
    }
}

@Composable
private fun WorkIdentityText(
    content: BookDetailContent,
    onOpenFacet: (LibraryScope, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val presentation = workDetailIdentityPresentation(
        tags = content.tags,
        completed = content.completed,
        progressPercent = content.book.progressPercent,
    )
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
    ) {
        presentation.elements.forEach { element ->
            when (element) {
                WorkDetailIdentityElement.Title -> Text(
                    content.book.title,
                    style = theme.typography.title,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
                WorkDetailIdentityElement.AuthorAndSeries -> WorkCreatorAndSeriesLine(content, onOpenFacet)
                WorkDetailIdentityElement.Tags -> WorkIdentityTags(presentation.tags)
                WorkDetailIdentityElement.ReadingStatus -> WorkIdentityStatus(
                    status = requireNotNull(presentation.status),
                )
            }
        }
    }
}

@Composable
private fun WorkCreatorAndSeriesLine(
    content: BookDetailContent,
    onOpenFacet: (LibraryScope, String) -> Unit,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = Modifier.fillMaxWidth().testTag("work-creator-series-line"),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FacetLink(
            label = content.book.author,
            enabled = content.authorFacetId != null,
            modifier = Modifier.weight(1f, fill = false),
        ) {
            content.authorFacetId?.let { onOpenFacet(LibraryScope.Authors, it) }
        }
        content.seriesName?.let { series ->
            Text(" / ", style = theme.typography.body, color = theme.colors.textTertiary)
            FacetLink(
                label = series,
                enabled = content.seriesId != null,
                modifier = Modifier.weight(1f, fill = false),
            ) {
                content.seriesId?.let { onOpenFacet(LibraryScope.Series, it) }
            }
        }
    }
}

@Composable
private fun WorkIdentityTags(tags: List<String>) {
    val theme = WarmPageThemeValues
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .testTag("work-identity-tags"),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.one, Alignment.CenterHorizontally),
    ) {
        tags.forEach { tag ->
            Text(
                text = tag,
                style = theme.typography.callout,
                color = theme.colors.textSecondary,
                maxLines = 1,
                softWrap = false,
                modifier = Modifier
                    .background(theme.colors.surfaceRaised, RoundedCornerShape(theme.spacing.half))
                    .padding(horizontal = theme.spacing.one, vertical = theme.spacing.half),
            )
        }
    }
}

@Composable
private fun WorkIdentityStatus(status: WorkDetailIdentityStatus) {
    val theme = WarmPageThemeValues
    Text(
        text = stringResource(
            when (status) {
                WorkDetailIdentityStatus.Reading -> R.string.work_identity_status_reading
                WorkDetailIdentityStatus.Finished -> R.string.work_identity_status_finished
            },
        ),
        style = theme.typography.callout,
        color = theme.colors.actionAccent,
        modifier = Modifier.testTag("work-identity-status"),
    )
}

@Composable
private fun FacetLink(
    label: String,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier
            .clickable(enabled = enabled, onClick = onClick)
            .heightIn(min = theme.components.controls.minimumTouchTarget)
            .padding(vertical = theme.spacing.half),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = theme.typography.body,
            color = theme.colors.textSecondary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun ReadingSummary(content: BookDetailContent) {
    val theme = WarmPageThemeValues
    val progress = content.book.progressPercent ?: 0
    if (progress <= 0) return
    val currentPosition = content.readingUnits
        .firstOrNull { it.readingState == ChapterReadingState.Current }
        ?.title
    val layout = workDetailSummaryLayout(LocalDensity.current.fontScale)
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        if (layout == BookDetailSummaryLayout.Stacked) {
            ReadingProgressHeading(progress)
            currentPosition?.let { title ->
                Text(
                    stringResource(R.string.work_reading_position, title),
                    style = theme.typography.callout,
                    color = theme.colors.textSecondary,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        } else {
            Row(verticalAlignment = Alignment.CenterVertically) {
                ReadingProgressHeading(progress)
                Spacer(Modifier.weight(1f))
                currentPosition?.let { title ->
                    Text(
                        stringResource(R.string.work_reading_position, title),
                        modifier = Modifier.weight(1f),
                        style = theme.typography.callout,
                        color = theme.colors.textSecondary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        textAlign = TextAlign.End,
                    )
                }
            }
        }
        ReadingProgressTrack(
            progressPercent = progress,
            stateDescription = stringResource(R.string.work_resource_accessibility_progress, progress),
        )
    }
}

@Composable
private fun ReadingProgressHeading(progress: Int) {
    val theme = WarmPageThemeValues
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            stringResource(R.string.work_reading_progress),
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
        )
        Text(
            stringResource(R.string.reader_progress_percent, progress),
            style = theme.typography.headline,
            modifier = Modifier.padding(start = theme.spacing.one),
        )
    }
}

@Composable
private fun WorkMediaPicker(
    options: List<WarmPageChoice<String>>,
    selected: String,
    onSelect: (String) -> Unit,
) {
    val theme = WarmPageThemeValues
    val fontScale = LocalDensity.current.fontScale
    BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
        when (workDetailMediaPickerLayout(availableWidth = maxWidth, fontScale = fontScale)) {
            WorkDetailMediaPickerLayout.Segmented -> Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
            ) {
                Text(
                    stringResource(R.string.work_resources_title),
                    style = theme.typography.sectionTitle,
                )
                Spacer(Modifier.weight(1f))
                Box(Modifier.width(workDetailMediaControlWidth(options.size))) {
                    WarmPageSegmentedControl(options = options, selected = selected, onSelect = onSelect)
                }
            }
            WorkDetailMediaPickerLayout.VerticalChoices -> Column {
                Text(stringResource(R.string.work_resources_title), style = theme.typography.sectionTitle)
                WorkMediaVerticalChoices(options = options, selected = selected, onSelect = onSelect)
            }
        }
    }
}

@Composable
private fun WorkMediaVerticalChoices(
    options: List<WarmPageChoice<String>>,
    selected: String,
    onSelect: (String) -> Unit,
) {
    val theme = WarmPageThemeValues
    Column {
        HorizontalDivider(
            thickness = theme.components.dividerThickness,
            color = theme.colors.divider,
        )
        options.forEachIndexed { index, option ->
            val isSelected = selected == option.value
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .selectable(
                        selected = isSelected,
                        role = Role.RadioButton,
                        onClick = { onSelect(option.value) },
                    )
                    .heightIn(min = theme.components.controls.minimumTouchTarget)
                    .testTag("work-media-${option.value}"),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                Text(
                    option.label,
                    style = theme.typography.body,
                    modifier = Modifier.weight(1f),
                )
                RadioButton(
                    selected = isSelected,
                    onClick = null,
                )
            }
            if (index != options.lastIndex) {
                HorizontalDivider(
                    thickness = theme.components.dividerThickness,
                    color = theme.colors.divider,
                )
            }
        }
    }
}

@Composable
private fun WorkAboutSection(
    content: BookDetailContent,
) {
    val theme = WarmPageThemeValues
    val description = remember(content.description) { plainWorkDescription(content.description) }
    var expanded by remember(content.description) { mutableStateOf(false) }
    var collapsedHasOverflow by remember(content.description) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        Text(
            description,
            style = theme.typography.body,
            color = theme.colors.textSecondary,
            maxLines = if (expanded) Int.MAX_VALUE else 3,
            overflow = TextOverflow.Ellipsis,
            onTextLayout = { result ->
                if (!expanded) collapsedHasOverflow = result.hasVisualOverflow
            },
        )
        if (workDetailDescriptionActionVisible(expanded, collapsedHasOverflow)) {
            TextButton(
                onClick = { expanded = !expanded },
                modifier = Modifier.align(Alignment.End),
            ) {
                Text(
                    stringResource(if (expanded) R.string.work_collapse else R.string.work_expand),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                )
            }
        }
    }
}

internal fun plainWorkDescription(rawValue: String?): String = rawValue
    ?.let { Html.fromHtml(it, Html.FROM_HTML_MODE_COMPACT).toString() }
    ?.replace(Regex("[\\t ]+"), " ")
    ?.replace(Regex("\\n{3,}"), "\n\n")
    ?.trim()
    .orEmpty()

@Composable
private fun WorkContentBrowser(
    page: BookContentsPage?,
    resources: List<ResourceContent>,
    sort: BookContentSort,
    loading: Boolean,
    errorCode: String?,
    repository: ContentRepository,
    context: ContentRequestContext,
    onSelectResource: (String) -> Unit,
    onOpenSourceNode: (String?) -> Unit,
    onSelectSort: (BookContentSort) -> Unit,
    onSelectPage: (Int) -> Unit,
    onRetry: () -> Unit,
) {
    val theme = WarmPageThemeValues
    var sortMenuExpanded by remember { mutableStateOf(false) }
    var gridLayout by rememberSaveable(page?.bookId) { mutableStateOf(true) }
    val resourceById = resources.associateBy(ResourceContent::id)
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.work_contents_title), style = theme.typography.sectionTitle)
                page?.let {
                    Text(
                        pluralStringResource(R.plurals.work_contents_count, it.total, it.total),
                        style = theme.typography.caption,
                        color = theme.colors.textSecondary,
                    )
                }
            }
            TextButton(onClick = { gridLayout = !gridLayout }) {
                Text(stringResource(if (gridLayout) R.string.work_contents_list else R.string.work_contents_grid))
            }
            Box {
                TextButton(onClick = { sortMenuExpanded = true }) { Text(bookContentSortLabel(sort)) }
                DropdownMenu(expanded = sortMenuExpanded, onDismissRequest = { sortMenuExpanded = false }) {
                    BookContentSort.entries.forEach { option ->
                        DropdownMenuItem(
                            text = { Text(bookContentSortLabel(option)) },
                            onClick = {
                                sortMenuExpanded = false
                                onSelectSort(option)
                            },
                        )
                    }
                }
            }
        }
        page?.let { contents ->
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = { onOpenSourceNode(null) }) { Text(stringResource(R.string.work_contents_root)) }
                contents.breadcrumbs.forEach { crumb ->
                    Text("/", color = theme.colors.textSecondary)
                    TextButton(onClick = { onOpenSourceNode(crumb.sourceNodeId) }) {
                        Text(crumb.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
        when {
            loading && page == null -> WarmPageLoadingState(
                title = stringResource(R.string.content_loading_title),
                message = stringResource(R.string.work_contents_loading),
                modifier = Modifier.fillMaxWidth().heightIn(min = 160.dp),
            )
            errorCode != null -> WarmPageErrorState(
                title = stringResource(R.string.work_contents_error_title),
                message = stringResource(R.string.work_contents_error_message, errorCode),
                retryLabel = stringResource(R.string.retry_action),
                onRetry = onRetry,
                modifier = Modifier.fillMaxWidth().heightIn(min = 160.dp),
            )
            page?.entries.isNullOrEmpty() -> WarmPageEmptyState(
                title = stringResource(R.string.work_contents_empty_title),
                message = stringResource(R.string.work_contents_empty_message),
            )
            gridLayout -> page.entries.chunked(2).forEach { rowEntries ->
                Row(horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
                    rowEntries.forEach { entry ->
                        WorkContentEntryCard(
                            entry = entry,
                            resource = entry.resourceId?.let(resourceById::get),
                            repository = repository,
                            context = context,
                            grid = true,
                            onOpen = { entry.resourceId?.let(onSelectResource) ?: onOpenSourceNode(entry.sourceNodeId) },
                            modifier = Modifier.weight(1f),
                        )
                    }
                    if (rowEntries.size == 1) Spacer(Modifier.weight(1f))
                }
            }
            else -> page.entries.forEach { entry ->
                WorkContentEntryCard(
                    entry = entry,
                    resource = entry.resourceId?.let(resourceById::get),
                    repository = repository,
                    context = context,
                    grid = false,
                    onOpen = { entry.resourceId?.let(onSelectResource) ?: onOpenSourceNode(entry.sourceNodeId) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        page?.takeIf { it.totalPages > 1 }?.let { contents ->
            PaginationRow(contents.page, contents.totalPages, loading, onSelectPage)
        }
    }
}

@Composable
private fun WorkContentEntryCard(
    entry: BookContentEntry,
    resource: ResourceContent?,
    repository: ContentRepository,
    context: ContentRequestContext,
    grid: Boolean,
    onOpen: () -> Unit,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    Surface(
        onClick = onOpen,
        modifier = modifier.heightIn(min = theme.components.controls.minimumTouchTarget),
        shape = RoundedCornerShape(theme.radii.task),
        color = theme.colors.surface,
    ) {
        if (grid) {
            Column(Modifier.padding(theme.spacing.one), verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
                val coverUrl = entry.coverUrl.orEmpty()
                if (coverUrl.isNotBlank()) {
                    ContentCover(
                        contentId = entry.resourceId ?: entry.sourceNodeId,
                        title = entry.title,
                        coverUrl = coverUrl,
                        repository = repository,
                        context = context,
                        role = CoverRole.Compact,
                        modifier = Modifier.fillMaxWidth(),
                    )
                } else {
                    Box(
                        Modifier.fillMaxWidth().aspectRatio(2f / 3f).background(theme.colors.canvas),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            if (entry.isSourceFolder) Icons.Outlined.Source else Icons.Outlined.Layers,
                            contentDescription = null,
                            tint = theme.colors.textSecondary,
                        )
                    }
                }
                Text(entry.title, style = theme.typography.body, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(
                    resource?.format?.uppercase(Locale.ROOT)
                        ?: stringResource(if (entry.isSourceFolder) R.string.work_contents_folder else R.string.work_contents_file),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                )
            }
        } else {
            Row(
                Modifier.padding(horizontal = theme.spacing.oneAndHalf, vertical = theme.spacing.one),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
            ) {
                Icon(
                    if (entry.isSourceFolder) Icons.Outlined.Source else Icons.Outlined.Layers,
                    contentDescription = null,
                    tint = theme.colors.textSecondary,
                )
                Column(Modifier.weight(1f)) {
                    Text(entry.title, style = theme.typography.body, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(
                        resource?.format?.uppercase(Locale.ROOT)
                            ?: stringResource(if (entry.isSourceFolder) R.string.work_contents_folder else R.string.work_contents_file),
                        style = theme.typography.caption,
                        color = theme.colors.textSecondary,
                    )
                }
                entry.sizeBytes?.let {
                    Text(formatWorkContentSize(it), style = theme.typography.caption, color = theme.colors.textSecondary)
                }
            }
        }
    }
}

@Composable
private fun WorkResourceDetail(
    resource: ResourceContent,
    page: ResourceReadingUnitsPage?,
    loading: Boolean,
    errorCode: String?,
    canReturnToContents: Boolean,
    repository: ContentRepository,
    context: ContentRequestContext,
    onBack: () -> Unit,
    onOpenResource: () -> Unit,
    onSelectPage: (Int) -> Unit,
    onRetry: () -> Unit,
) {
    val theme = WarmPageThemeValues
    val kind = when (resource.readerType.lowercase(Locale.ROOT)) {
        "audio" -> R.string.work_resource_tracks_title
        "comic", "pdf" -> R.string.work_resource_pages_title
        else -> R.string.work_resource_chapters_title
    }
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
        if (canReturnToContents) TextButton(onClick = onBack) { Text(stringResource(R.string.work_back_to_contents)) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(stringResource(kind), style = theme.typography.sectionTitle)
                Text(
                    pluralStringResource(
                        R.plurals.work_resource_units_count,
                        page?.total ?: 0,
                        page?.total ?: 0,
                    ),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                )
            }
            WarmPageSecondaryAction(
                label = stringResource(
                    if (resource.readerType.equals("audio", true)) R.string.work_open_player else R.string.work_open_reader,
                ),
                onClick = onOpenResource,
            )
        }
        if (!resource.importStatus.equals("READY", true)) {
            Surface(shape = RoundedCornerShape(theme.radii.task), color = theme.colors.surface) {
                Text(
                    stringResource(
                        if (resource.importStatus.equals("FAILED", true)) R.string.work_resource_import_failed
                        else R.string.work_resource_importing,
                        resource.importError.orEmpty(),
                    ),
                    modifier = Modifier.padding(theme.spacing.oneAndHalf),
                    style = theme.typography.body,
                )
            }
        }
        when {
            loading && page == null -> WarmPageLoadingState(
                title = stringResource(R.string.content_loading_title),
                message = stringResource(R.string.work_resource_detail_loading),
                modifier = Modifier.fillMaxWidth().heightIn(min = 160.dp),
            )
            errorCode != null -> WarmPageErrorState(
                title = stringResource(R.string.work_resource_detail_error_title),
                message = stringResource(R.string.work_resource_detail_error_message, errorCode),
                retryLabel = stringResource(R.string.retry_action),
                onRetry = onRetry,
                modifier = Modifier.fillMaxWidth().heightIn(min = 160.dp),
            )
            page?.units.isNullOrEmpty() -> WarmPageEmptyState(
                title = stringResource(R.string.work_resource_detail_empty_title),
                message = stringResource(R.string.work_resource_detail_empty_message),
            )
            resource.readerType.equals("comic", true) || resource.readerType.equals("pdf", true) -> {
                page.units.chunked(2).forEach { rowUnits ->
                    Row(horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
                        rowUnits.forEach { unit ->
                            WorkPagePreview(unit, repository, context, Modifier.weight(1f), onOpenResource)
                        }
                        if (rowUnits.size == 1) Spacer(Modifier.weight(1f))
                    }
                }
            }
            else -> page.units.forEachIndexed { index, unit ->
                WorkReadingUnitRow(
                    unit = unit,
                    displayIndex = (page.page - 1) * page.pageSize + index + 1,
                    currentSortOrder = page.currentChapterSortOrder,
                    progress = page.progress,
                    onOpen = onOpenResource,
                )
            }
        }
        page?.takeIf { it.totalPages > 1 }?.let {
            PaginationRow(it.page, it.totalPages, loading, onSelectPage)
        }
    }
}

@Composable
private fun WorkPagePreview(
    unit: ReadingUnit,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier,
    onOpen: () -> Unit,
) {
    val theme = WarmPageThemeValues
    Surface(onClick = onOpen, modifier = modifier, color = Color.Transparent) {
        Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
            val previewUrl = unit.previewUrl.orEmpty()
            if (previewUrl.isNotBlank()) {
                ContentCover(
                    contentId = unit.id,
                    title = unit.title.orEmpty(),
                    coverUrl = previewUrl,
                    repository = repository,
                    context = context,
                    role = CoverRole.Compact,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                Box(
                    Modifier.fillMaxWidth().aspectRatio(2f / 3f).background(theme.colors.surface),
                    contentAlignment = Alignment.Center,
                ) { Icon(Icons.Outlined.Image, contentDescription = null, tint = theme.colors.textSecondary) }
            }
            Text(
                unit.title?.takeIf(String::isNotBlank)
                    ?: stringResource(R.string.work_resource_page_number, unit.metadata.pageNumber ?: unit.sortOrder + 1),
                style = theme.typography.body,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun WorkReadingUnitRow(
    unit: ReadingUnit,
    displayIndex: Int,
    currentSortOrder: Int?,
    progress: Double,
    onOpen: () -> Unit,
) {
    val theme = WarmPageThemeValues
    val readingState = when {
        currentSortOrder != null && unit.sortOrder == currentSortOrder -> R.string.work_chapter_current
        progress >= 100.0 || (currentSortOrder != null && unit.sortOrder < currentSortOrder) -> R.string.work_chapter_read
        else -> R.string.work_chapter_unread
    }
    Surface(onClick = onOpen, color = theme.colors.surface, modifier = Modifier.fillMaxWidth()) {
        Row(
            Modifier.padding(horizontal = theme.spacing.oneAndHalf, vertical = theme.spacing.one),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
        ) {
            Text(displayIndex.toString(), style = theme.typography.caption, color = theme.colors.textSecondary)
            Column(Modifier.weight(1f)) {
                Text(
                    unit.title?.takeIf(String::isNotBlank)
                        ?: stringResource(R.string.work_resource_unit_number, displayIndex),
                    style = theme.typography.body,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                if (unit.unitType.equals("track", true)) {
                    Text(formatWorkDuration(unit.durationMillis), style = theme.typography.caption, color = theme.colors.textSecondary)
                }
            }
            if (unit.unitType.equals("chapter", true)) {
                Text(stringResource(readingState), style = theme.typography.caption, color = theme.colors.textSecondary)
            }
        }
    }
}

@Composable
private fun PaginationRow(page: Int, totalPages: Int, loading: Boolean, onSelectPage: (Int) -> Unit) {
    val theme = WarmPageThemeValues
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            stringResource(R.string.work_pagination, page, totalPages),
            style = theme.typography.caption,
            color = theme.colors.textSecondary,
            modifier = Modifier.weight(1f),
        )
        TextButton(enabled = !loading && page > 1, onClick = { onSelectPage(page - 1) }) {
            Text(stringResource(R.string.reader_previous))
        }
        TextButton(enabled = !loading && page < totalPages, onClick = { onSelectPage(page + 1) }) {
            Text(stringResource(R.string.reader_next))
        }
    }
}

@Composable
private fun bookContentSortLabel(sort: BookContentSort): String = stringResource(
    when (sort) {
        BookContentSort.NameAscending -> R.string.work_sort_name_asc
        BookContentSort.NameDescending -> R.string.work_sort_name_desc
        BookContentSort.UpdatedDescending -> R.string.work_sort_updated_desc
        BookContentSort.UpdatedAscending -> R.string.work_sort_updated_asc
        BookContentSort.TypeAscending -> R.string.work_sort_type_asc
        BookContentSort.SizeDescending -> R.string.work_sort_size_desc
    },
)

private fun formatWorkContentSize(sizeBytes: Long): String = when {
    sizeBytes >= 1024L * 1024L * 1024L -> "%.1f GB".format(Locale.ROOT, sizeBytes / (1024.0 * 1024.0 * 1024.0))
    sizeBytes >= 1024L * 1024L -> "%.1f MB".format(Locale.ROOT, sizeBytes / (1024.0 * 1024.0))
    sizeBytes >= 1024L -> "%.1f KB".format(Locale.ROOT, sizeBytes / 1024.0)
    else -> "$sizeBytes B"
}

private fun formatWorkDuration(durationMillis: Long?): String {
    val totalSeconds = (durationMillis ?: 0L).coerceAtLeast(0L) / 1000L
    val hours = totalSeconds / 3600L
    val minutes = (totalSeconds % 3600L) / 60L
    val seconds = totalSeconds % 60L
    return if (hours > 0L) "%d:%02d:%02d".format(Locale.ROOT, hours, minutes, seconds)
    else "%d:%02d".format(Locale.ROOT, minutes, seconds)
}

@Composable
private fun WorkResourceRail(
    resources: List<ResourceContent>,
    selectedResourceId: String?,
    totalResources: Int,
    isLoadingMore: Boolean,
    paginationErrorCode: String?,
    repository: ContentRepository,
    context: ContentRequestContext,
    downloadRecordsByResource: Map<String, AndroidDownloadRecord>,
    downloadFailuresByResource: Map<String, String>,
    onSelectResource: (String) -> Unit,
    onLoadMore: () -> Unit,
    onManageResource: (ResourceContent, Offset) -> Unit,
    managementAvailable: Boolean,
) {
    val theme = WarmPageThemeValues
    val listState = rememberLazyListState()
    LaunchedEffect(listState, resources.size, totalResources, isLoadingMore) {
        snapshotFlow { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1 }
            .distinctUntilChanged()
            .filter { index -> index >= resources.lastIndex - 2 && resources.size < totalResources && !isLoadingMore }
            .collect { onLoadMore() }
    }
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
        BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
            val itemWidth = workDetailVolumeRailItemWidth(
                availableWidth = maxWidth,
                gap = theme.spacing.oneAndHalf,
                fontScale = LocalDensity.current.fontScale,
            )
            LazyRow(state = listState, horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
                itemsIndexed(resources, key = { _, resource -> resource.id }) { position, resource ->
                    ResourceCoverItem(
                        resource = resource,
                        position = position,
                        selected = resource.id == selectedResourceId,
                        repository = repository,
                        context = context,
                        download = downloadRecordsByResource[resource.id],
                        downloadFailure = downloadFailuresByResource[resource.id],
                        onSelectResource = onSelectResource,
                        onManageResource = onManageResource,
                        managementAvailable = managementAvailable,
                        modifier = Modifier.width(itemWidth),
                    )
                }
                if (isLoadingMore || paginationErrorCode != null) {
                    item(key = "resource-pagination-tail") {
                        Box(
                            modifier = Modifier
                                .width(itemWidth)
                                .heightIn(min = theme.metrics.androidMinimumTouchTarget)
                                .clickable(enabled = paginationErrorCode != null, onClick = onLoadMore),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = stringResource(
                                    if (paginationErrorCode == null) R.string.work_resource_loading_more
                                    else R.string.work_resource_load_more_failed,
                                ),
                                style = theme.typography.caption,
                                color = theme.colors.textSecondary,
                                textAlign = TextAlign.Center,
                            )
                        }
                    }
                }
            }
        }
    }
}

internal fun workDetailVolumeRailItemWidth(
    availableWidth: Dp,
    gap: Dp,
    fontScale: Float,
): Dp = if (fontScale >= 1.3f) {
    ((availableWidth - gap) / 2.25f).coerceAtLeast(0.dp)
} else {
    ((availableWidth - gap * 2) / 3.2f).coerceAtLeast(0.dp)
}

@Composable
private fun SelectedResourceMetadata(resource: ResourceContent) {
    val locale = LocalConfiguration.current.locales[0]
    var fullPath by remember(resource.id) { mutableStateOf<String?>(null) }
    val rows = listOf(
        Triple(R.string.work_metadata_format, resource.format, false),
        Triple(R.string.work_metadata_language, resource.language, false),
        Triple(R.string.work_metadata_published, formatWorkMetadataDate(resource.publishedAt, locale), false),
        Triple(R.string.work_metadata_page_count, resource.pageCount?.let {
            pluralStringResource(R.plurals.work_metadata_page_count_value, it, it)
        }, false),
        Triple(R.string.work_metadata_source, resource.metadataSource, false),
        Triple(R.string.work_metadata_file_path, resource.assets.firstOrNull()?.path, true),
    )
    val theme = WarmPageThemeValues
    Column(Modifier.fillMaxWidth().testTag("work-selected-volume-metadata")) {
        Text(stringResource(R.string.work_resource_metadata_title), style = theme.typography.sectionTitle)
        rows.forEach { (label, rawValue, isFilePath) ->
            val value = rawValue?.trim()?.takeIf(String::isNotEmpty)
                ?: stringResource(R.string.work_metadata_missing)
            val rowModifier = Modifier
                .fillMaxWidth()
                .heightIn(min = theme.components.controls.minimumTouchTarget)
                .then(
                    if (isFilePath && rawValue?.isNotBlank() == true) {
                        Modifier.clickable { fullPath = value }
                    } else {
                        Modifier
                    },
                )
            Row(
                modifier = rowModifier,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(label),
                    style = theme.typography.body,
                    color = theme.colors.textSecondary,
                )
                Spacer(Modifier.weight(1f))
                Text(
                    text = value,
                    style = theme.typography.body,
                    maxLines = if (isFilePath) 1 else 2,
                    overflow = TextOverflow.Ellipsis,
                    textAlign = TextAlign.End,
                    modifier = Modifier.weight(1.4f),
                )
            }
            HorizontalDivider(
                thickness = theme.components.dividerThickness,
                color = theme.colors.divider,
            )
        }
    }
    fullPath?.let { path ->
        AlertDialog(
            onDismissRequest = { fullPath = null },
            title = { Text(stringResource(R.string.work_metadata_file_path_full_title)) },
            text = {
                SelectionContainer {
                    Text(path, style = theme.typography.body)
                }
            },
            confirmButton = {
                TextButton(onClick = { fullPath = null }) {
                    Text(stringResource(R.string.close_action))
                }
            },
        )
    }
}

internal fun formatWorkMetadataDate(rawValue: String?, locale: Locale): String? {
    val value = rawValue?.trim()?.takeIf(String::isNotEmpty) ?: return null
    val date = runCatching { LocalDate.parse(value.take(10)) }.getOrNull() ?: return value
    return DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM).withLocale(locale).format(date)
}

internal enum class BookDetailSummaryLayout {
    Inline,
    Stacked,
}

internal enum class WorkDetailIdentityElement {
    Title,
    AuthorAndSeries,
    Tags,
    ReadingStatus,
}

internal enum class WorkDetailIdentityStatus {
    Reading,
    Finished,
}

internal data class WorkDetailIdentityPresentation(
    val tags: List<String>,
    val status: WorkDetailIdentityStatus?,
    val elements: List<WorkDetailIdentityElement>,
)

internal enum class WorkDetailActionLayout {
    Inline,
    Stacked,
}

internal enum class WorkDetailMediaPickerLayout {
    Segmented,
    VerticalChoices,
}

enum class WorkReadingStatus {
    Unread,
    Reading,
    Finished,
}

internal enum class WorkDetailPrimaryActionIntent {
    OpenSelectedVolume,
    Unavailable,
}

internal enum class WorkDetailPrimaryActionLabel {
    StartReading,
    ContinueReading,
    StartListening,
    ContinueListening,
}

internal data class WorkDetailPrimaryActionPresentation(
    val intent: WorkDetailPrimaryActionIntent,
    val label: WorkDetailPrimaryActionLabel,
    val enabled: Boolean,
)

internal enum class WorkDetailVolumeReadingState {
    Unread,
    Reading,
    Finished,
}

internal enum class WorkDetailVolumeDownloadState {
    NotDownloaded,
    Downloading,
    Downloaded,
}

internal enum class WorkDetailDownloadAction {
    NotDownloaded,
    Downloading,
    Paused,
    Failed,
    Downloaded,
}

internal fun workDetailDownloadActionPresentation(
    download: AndroidDownloadRecord?,
): WorkDetailDownloadAction = when {
    download?.isReadable == true -> WorkDetailDownloadAction.Downloaded
    download == null -> WorkDetailDownloadAction.NotDownloaded
    download.status in setOf(
        AndroidDownloadStatus.Queued,
        AndroidDownloadStatus.Downloading,
        AndroidDownloadStatus.Verifying,
    ) -> WorkDetailDownloadAction.Downloading
    download.status == AndroidDownloadStatus.Paused -> WorkDetailDownloadAction.Paused
    else -> WorkDetailDownloadAction.Failed
}

internal data class WorkDetailVolumePresentation(
    val selected: Boolean,
    val readingState: WorkDetailVolumeReadingState,
    val downloadState: WorkDetailVolumeDownloadState,
)

internal fun workDetailIdentityPresentation(
    tags: List<String>,
    completed: Boolean,
    progressPercent: Int?,
): WorkDetailIdentityPresentation {
    val visibleTags = tags
        .filter(String::isNotBlank)
        .distinctBy { tag -> tag.lowercase(Locale.ROOT) }
    val elements = buildList {
        add(WorkDetailIdentityElement.Title)
        add(WorkDetailIdentityElement.AuthorAndSeries)
        if (visibleTags.isNotEmpty()) add(WorkDetailIdentityElement.Tags)
    }
    return WorkDetailIdentityPresentation(
        tags = visibleTags,
        status = null,
        elements = elements,
    )
}

internal fun workDetailDescriptionActionVisible(
    expanded: Boolean,
    collapsedHasOverflow: Boolean,
): Boolean = expanded || collapsedHasOverflow

internal fun workReadingStatus(
    completed: Boolean,
    progressPercent: Int?,
): WorkReadingStatus = when {
    completed -> WorkReadingStatus.Finished
    (progressPercent ?: 0) > 0 -> WorkReadingStatus.Reading
    else -> WorkReadingStatus.Unread
}

internal fun nextWorkReadingStatus(current: WorkReadingStatus): WorkReadingStatus =
    if (current == WorkReadingStatus.Finished) WorkReadingStatus.Unread else WorkReadingStatus.Finished

internal fun workReadingStatusChoices(): List<WorkReadingStatus> = listOf(
    WorkReadingStatus.Unread,
    WorkReadingStatus.Finished,
)

internal fun workDetailPrimaryActionPresentation(
    selectedResource: ResourceContent?,
    download: AndroidDownloadRecord?,
): WorkDetailPrimaryActionPresentation {
    val hasProgress = (selectedResource?.progressPercent ?: 0) > 0
    val readingLabel = if (hasProgress) {
        WorkDetailPrimaryActionLabel.ContinueReading
    } else {
        WorkDetailPrimaryActionLabel.StartReading
    }
    val listeningLabel = if (hasProgress) {
        WorkDetailPrimaryActionLabel.ContinueListening
    } else {
        WorkDetailPrimaryActionLabel.StartListening
    }
    if (selectedResource?.readerType.equals("audio", ignoreCase = true)) return WorkDetailPrimaryActionPresentation(
        intent = WorkDetailPrimaryActionIntent.OpenSelectedVolume,
        label = listeningLabel,
        enabled = selectedResource?.readable == true,
    )
    if (selectedResource == null || !selectedResource.readable ||
        !isSupportedNativeReaderEntry(selectedResource.readerType, selectedResource.format)
    ) {
        return WorkDetailPrimaryActionPresentation(
            intent = WorkDetailPrimaryActionIntent.Unavailable,
            label = readingLabel,
            enabled = false,
        )
    }
    return WorkDetailPrimaryActionPresentation(
        intent = WorkDetailPrimaryActionIntent.OpenSelectedVolume,
        label = readingLabel,
        enabled = true,
    )
}

internal fun workDetailVolumePresentation(
    resource: ResourceContent,
    selected: Boolean,
    download: AndroidDownloadRecord?,
): WorkDetailVolumePresentation {
    val progress = resource.progressPercent?.coerceIn(0, 100) ?: 0
    val readingState = when {
        progress >= 100 -> WorkDetailVolumeReadingState.Finished
        progress > 0 -> WorkDetailVolumeReadingState.Reading
        else -> WorkDetailVolumeReadingState.Unread
    }
    val downloadState = when {
        download?.resourceId == resource.id && download.isReadable -> WorkDetailVolumeDownloadState.Downloaded
        download?.resourceId == resource.id && download.status in setOf(
            AndroidDownloadStatus.Queued,
            AndroidDownloadStatus.Downloading,
            AndroidDownloadStatus.Verifying,
        ) -> WorkDetailVolumeDownloadState.Downloading
        else -> WorkDetailVolumeDownloadState.NotDownloaded
    }
    return WorkDetailVolumePresentation(
        selected = selected,
        readingState = readingState,
        downloadState = downloadState,
    )
}

internal fun workDetailSummaryLayout(fontScale: Float): BookDetailSummaryLayout =
    if (fontScale >= WORK_DETAIL_STACKED_LAYOUT_FONT_SCALE) {
        BookDetailSummaryLayout.Stacked
    } else {
        BookDetailSummaryLayout.Inline
    }

internal fun workDetailActionLayout(
    availableWidth: Dp,
    fontScale: Float,
    requiredInlineWidth: Dp,
): WorkDetailActionLayout =
    if (
        fontScale >= WORK_DETAIL_STACKED_LAYOUT_FONT_SCALE ||
        availableWidth < maxOf(WORK_DETAIL_MIN_INLINE_WIDTH, requiredInlineWidth)
    ) {
        WorkDetailActionLayout.Stacked
    } else {
        WorkDetailActionLayout.Inline
    }

@Composable
internal fun workDetailActionLayoutForLabels(
    availableWidth: Dp,
    fontScale: Float,
    secondaryLabel: String,
    primaryLabel: String,
): WorkDetailActionLayout {
    val theme = WarmPageThemeValues
    val density = LocalDensity.current
    val textMeasurer = rememberTextMeasurer()
    val secondaryLabelWidth = with(density) {
        textMeasurer.measure(
            text = AnnotatedString(secondaryLabel),
            style = theme.typography.button,
            softWrap = false,
            maxLines = 1,
        ).size.width.toDp()
    }
    val primaryLabelWidth = with(density) {
        textMeasurer.measure(
            text = AnnotatedString(primaryLabel),
            style = theme.typography.button,
            softWrap = false,
            maxLines = 1,
        ).size.width.toDp()
    }
    val requiredInlineWidth = minimumWorkDetailInlineActionWidth(
        secondaryLabelWidth = secondaryLabelWidth,
        primaryLabelWidth = primaryLabelWidth,
        iconSize = theme.components.controls.iconSize,
        iconLabelGap = theme.spacing.one,
        horizontalContentPadding = warmPageActionHorizontalPadding(
            hasIcon = true,
            regularPadding = theme.spacing.three,
            compactPadding = theme.spacing.one,
        ),
        actionGap = theme.spacing.oneAndHalf,
    )
    return workDetailActionLayout(
        availableWidth = availableWidth,
        fontScale = fontScale,
        requiredInlineWidth = requiredInlineWidth,
    )
}

internal fun minimumWorkDetailInlineActionWidth(
    secondaryLabelWidth: Dp,
    primaryLabelWidth: Dp,
    iconSize: Dp,
    iconLabelGap: Dp,
    horizontalContentPadding: Dp,
    actionGap: Dp,
): Dp =
    (
        maxOf(secondaryLabelWidth, primaryLabelWidth) +
            iconSize +
            iconLabelGap +
            (horizontalContentPadding * 2)
    ) * 2 + actionGap

internal fun workDetailMediaPickerLayout(
    availableWidth: Dp,
    fontScale: Float,
): WorkDetailMediaPickerLayout =
    if (fontScale >= WORK_DETAIL_STACKED_LAYOUT_FONT_SCALE || availableWidth < WORK_DETAIL_MIN_INLINE_WIDTH) {
        WorkDetailMediaPickerLayout.VerticalChoices
    } else {
        WorkDetailMediaPickerLayout.Segmented
    }

internal fun workDetailMediaControlWidth(optionCount: Int): Dp =
    WORK_DETAIL_MEDIA_OPTION_WIDTH * optionCount.coerceIn(1, 3)

private const val WORK_DETAIL_STACKED_LAYOUT_FONT_SCALE = 1.5f
private val WORK_DETAIL_MIN_INLINE_WIDTH = 328.dp
private val WORK_DETAIL_MEDIA_OPTION_WIDTH = 80.dp
internal val WORK_DETAIL_SELECTED_VOLUME_BORDER_WIDTH = 3.dp

internal fun workDetailVolumeColumnCount(
    availableWidth: Dp,
    horizontalPadding: Dp,
    gap: Dp,
    fontScale: Float,
): Int {
    val minimumColumns = if (fontScale >= 1.3f || availableWidth < 320.dp) 2 else 3
    val minimumItemWidth = if (minimumColumns == 2) 132.dp else 88.dp
    val contentWidth = (availableWidth - horizontalPadding * 2).coerceAtLeast(0.dp)
    val estimatedColumns = ((contentWidth + gap) / (minimumItemWidth + gap)).toInt().coerceAtLeast(1)
    return estimatedColumns.coerceAtLeast(minimumColumns)
}

internal fun workDetailVolumeItemWidth(
    availableWidth: Dp,
    horizontalPadding: Dp,
    gap: Dp,
    columns: Int,
): Dp {
    require(columns > 0)
    return ((availableWidth - horizontalPadding * 2 - gap * (columns - 1)) / columns)
        .coerceAtLeast(0.dp)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ResourceCoverItem(
    resource: ResourceContent,
    position: Int,
    selected: Boolean,
    repository: ContentRepository,
    context: ContentRequestContext,
    download: AndroidDownloadRecord?,
    downloadFailure: String?,
    onSelectResource: (String) -> Unit,
    onManageResource: (ResourceContent, Offset) -> Unit,
    managementAvailable: Boolean,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val index = resource.displayIndex(position)
    val progress = resource.progressPercent?.coerceIn(0, 100) ?: 0
    val presentation = workDetailVolumePresentation(resource, selected, download)
    val state = when (presentation.readingState) {
        WorkDetailVolumeReadingState.Finished -> stringResource(R.string.work_resource_accessibility_finished)
        WorkDetailVolumeReadingState.Reading -> stringResource(R.string.work_resource_accessibility_progress, progress)
        WorkDetailVolumeReadingState.Unread -> stringResource(R.string.work_resource_accessibility_not_started)
    }
    val manageResourceLabel = stringResource(R.string.management_resource)
    val resourceLabel = stringResource(R.string.work_resource_accessibility_label, index, resource.title)
    var coverPositionInWindow by remember(resource.id) { mutableStateOf(Offset.Zero) }
    var coverSize by remember(resource.id) { mutableStateOf(androidx.compose.ui.unit.IntSize.Zero) }
    val coverCenter = {
        coverPositionInWindow + Offset(coverSize.width / 2f, coverSize.height / 2f)
    }
    Column(
        modifier = modifier
            .background(
                color = if (selected) theme.colors.accentSoft else androidx.compose.ui.graphics.Color.Transparent,
                shape = RoundedCornerShape(theme.radii.coverCompact),
            )
            .padding(theme.spacing.half),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
    ) {
        Box {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { coordinates ->
                        coverPositionInWindow = coordinates.positionInWindow()
                        coverSize = coordinates.size
                    }
                    .pointerInput(resource.id, managementAvailable) {
                        detectTapGestures(
                            onTap = { onSelectResource(resource.id) },
                            onLongPress = { localPress ->
                                if (managementAvailable) {
                                    onManageResource(resource, coverPositionInWindow + localPress)
                                }
                            },
                        )
                    }
                    .semantics(mergeDescendants = true) {
                        contentDescription = resourceLabel
                        this.selected = selected
                        stateDescription = state
                        if (managementAvailable) {
                            customActions = listOf(
                                CustomAccessibilityAction(manageResourceLabel) {
                                    onManageResource(resource, coverCenter())
                                    true
                                },
                            )
                        }
                    }
                    .testTag("work-resource-${resource.id}"),
            ) {
                ContentCover(
                    contentId = resource.id,
                    title = resource.title,
                    coverUrl = resource.coverUrl,
                    repository = repository,
                    context = context,
                    role = CoverRole.Compact,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (progress > 0) {
                    CoverProgress(
                        progressPercent = progress,
                        stateDescription = state,
                        modifier = Modifier.align(Alignment.BottomCenter),
                    )
                }
                if (presentation.selected) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .border(
                                width = WORK_DETAIL_SELECTED_VOLUME_BORDER_WIDTH,
                                color = theme.colors.brandAccent,
                                shape = RoundedCornerShape(theme.radii.coverCompact),
                            ),
                    )
                }
            }
            Surface(
                shape = RoundedCornerShape(theme.radii.coverCompact),
                color = theme.colors.surfaceRaised,
                modifier = Modifier.align(Alignment.TopStart).padding(theme.spacing.half),
            ) {
                Text(
                    index,
                    style = theme.typography.caption,
                    maxLines = 1,
                    softWrap = false,
                    color = theme.colors.textSecondary,
                    modifier = Modifier
                        .heightIn(min = theme.components.workDetail.statusBadgeMinimumHeight)
                        .padding(horizontal = theme.spacing.half, vertical = theme.spacing.half),
                )
            }
            if (selected) Box(
                modifier = Modifier.align(Alignment.TopEnd).padding(theme.spacing.half),
                contentAlignment = Alignment.Center,
            ) {
                Surface(
                    shape = CircleShape,
                    color = theme.colors.accentSoft,
                    modifier = Modifier.size(theme.components.workDetail.statusBadgeMinimumHeight),
                ) {
                    Icon(
                        imageVector = Icons.Outlined.CheckCircle,
                        contentDescription = stringResource(R.string.work_resource_selected),
                        tint = theme.colors.brandAccent,
                        modifier = Modifier.padding(theme.spacing.half),
                    )
                }
            }
        }
        Text(
            resource.title,
            style = theme.typography.callout,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            when {
                progress > 0 && progress < 100 -> stringResource(R.string.work_resource_reading_badge, progress)
                progress >= 100 -> stringResource(R.string.work_chapter_read)
                else -> stringResource(R.string.work_chapter_unread)
            },
            style = theme.typography.caption,
            color = if (presentation.selected) theme.colors.actionAccent else theme.colors.textSecondary,
        )
        if (downloadFailure != null) {
            Text(
                stringResource(R.string.work_download_failed_inline),
                style = theme.typography.caption,
                color = androidx.compose.material3.MaterialTheme.colorScheme.error,
                maxLines = 2,
            )
        }
    }
}

@Composable
private fun WorkDetailControlMenu(
    target: WorkControlMenuTarget,
    anchorInWindow: Offset,
    content: BookDetailContent,
    selectedResource: ResourceContent?,
    repository: ContentRepository,
    context: ContentRequestContext,
    canManageSystem: Boolean,
    selectedDownload: AndroidDownloadRecord?,
    onAddShelf: () -> Unit,
    onMarkUnread: (ResourceContent) -> Unit,
    onDownload: (ResourceContent) -> Unit,
    onBookTask: (BookControlAction) -> Unit,
    onResourceTask: (VolumeControlAction, ResourceContent) -> Unit,
    onDismiss: () -> Unit,
) {
    val menuResource = when (target) {
        WorkControlMenuTarget.Book -> selectedResource
        is WorkControlMenuTarget.Resource -> target.value
    }
    val downloadLabel = when {
        selectedDownload?.isReadable == true -> stringResource(R.string.downloads_remove_action)
        selectedDownload?.status in setOf(
            AndroidDownloadStatus.Queued,
            AndroidDownloadStatus.Downloading,
            AndroidDownloadStatus.Verifying,
        ) -> stringResource(R.string.work_download_pause)
        else -> stringResource(R.string.work_control_download)
    }
    val kindleEligible = menuResource?.assets?.any { asset ->
        asset.path.endsWith(".epub", ignoreCase = true) || asset.path.endsWith(".pdf", ignoreCase = true)
    } == true
    when (target) {
        WorkControlMenuTarget.Book -> {
            if (!canManageSystem) { LaunchedEffect(Unit) { onDismiss() } }
            Box(
                Modifier.offset { IntOffset(anchorInWindow.x.toInt(), anchorInWindow.y.toInt()) }
                    .testTag("work-book-control-menu"),
            ) {
                DropdownMenu(expanded = canManageSystem, onDismissRequest = onDismiss) {
                    fun select(action: BookControlAction) { onDismiss(); onBookTask(action) }
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.work_control_edit)) },
                        leadingIcon = { Icon(Icons.Outlined.Edit, contentDescription = null) },
                        onClick = { select(BookControlAction.Edit) },
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.work_control_regenerate_cover)) },
                        leadingIcon = { Icon(Icons.Outlined.Refresh, contentDescription = null) },
                        onClick = { select(BookControlAction.RegenerateCover) },
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.work_control_recognize)) },
                        leadingIcon = { Icon(Icons.Outlined.Source, contentDescription = null) },
                        onClick = { select(BookControlAction.Recognize) },
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.management_rescan)) },
                        leadingIcon = { Icon(Icons.Outlined.Refresh, contentDescription = null) },
                        onClick = { select(BookControlAction.Rescan) },
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.management_delete), color = Color.Red) },
                        leadingIcon = { Icon(Icons.Outlined.Delete, contentDescription = null, tint = Color.Red) },
                        onClick = { select(BookControlAction.Delete) },
                    )
                }
            }
        }
        is WorkControlMenuTarget.Resource -> {
            val resource = target.value
            val activeDownload = selectedDownload?.status in setOf(
                AndroidDownloadStatus.Queued,
                AndroidDownloadStatus.Downloading,
                AndroidDownloadStatus.Verifying,
            )
            val actions = buildList {
                add(WarmPageFloatingMenuAction(VolumeControlAction.MarkUnread, stringResource(R.string.work_control_mark_unread), Icons.Outlined.BookmarkBorder))
                add(WarmPageFloatingMenuAction(VolumeControlAction.Download, downloadLabel, if (activeDownload) Icons.Outlined.PauseCircle else Icons.Outlined.CloudDownload))
                if (canManageSystem) {
                    add(WarmPageFloatingMenuAction(VolumeControlAction.Edit, stringResource(R.string.work_control_edit), Icons.Outlined.Edit))
                    if (kindleEligible) add(WarmPageFloatingMenuAction(VolumeControlAction.SendToKindle, stringResource(R.string.work_control_send_kindle), Icons.AutoMirrored.Outlined.Send))
                }
            }
            WarmPageFloatingActionMenu(
                actions = actions,
                anchorInWindow = anchorInWindow,
                onSelect = { action ->
                    when (action) {
                        VolumeControlAction.MarkUnread -> onMarkUnread(resource)
                        VolumeControlAction.Download -> onDownload(resource)
                        VolumeControlAction.Edit,
                        VolumeControlAction.SendToKindle,
                        -> onResourceTask(action, resource)
                    }
                },
                onDismiss = onDismiss,
                modifier = Modifier.testTag("work-resource-control-menu"),
                header = {
                    WorkControlMenuHeader(
                        title = resource.title,
                        subtitle = resource.format,
                        cover = {
                            ContentCover(
                                contentId = resource.id,
                                title = resource.title,
                                coverUrl = resource.coverUrl,
                                repository = repository,
                                context = context,
                                role = CoverRole.Compact,
                                modifier = Modifier.width(38.dp),
                            )
                        },
                    )
                },
            )
        }
    }
}

@Composable
private fun WorkControlMenuHeader(
    title: String,
    subtitle: String,
    cover: @Composable () -> Unit,
) {
    val theme = WarmPageThemeValues
    Row(
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        cover()
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
        ) {
            Text(
                text = title,
                style = theme.typography.body,
                fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
                color = theme.colors.textPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (subtitle.isNotBlank()) {
                Text(
                    text = subtitle,
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WorkActionsSheet(
    content: BookDetailContent,
    strings: WorkActionsSheetStrings,
    selectedResource: ResourceContent?,
    selectedDownload: AndroidDownloadRecord?,
    selectedReadingStatus: WorkReadingStatus,
    onOpenShelfPicker: () -> Unit,
    onDownloadResource: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    onSelectReadingStatus: (WorkReadingStatus) -> Unit,
    onDismiss: () -> Unit,
) {
    val theme = WarmPageThemeValues
    val isDownloading = selectedDownload?.status == AndroidDownloadStatus.Downloading ||
        selectedDownload?.status == AndroidDownloadStatus.Queued
    WarmPageModalBottomSheet(
        onDismissRequest = onDismiss,
        modifier = Modifier.testTag("work-actions-sheet"),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    horizontal = theme.components.page.compactGutter,
                    vertical = theme.spacing.two,
                ),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
        ) {
            WarmPageSectionHeader(
                title = strings.title,
                modifier = Modifier.testTag("work-actions-title"),
            )
            Text(
                listOf(content.book.title, content.book.author).joinToString(" · "),
                style = theme.typography.callout,
                color = theme.colors.textSecondary,
            )
            HorizontalDivider(
                thickness = theme.components.dividerThickness,
                color = theme.colors.divider,
            )
            WorkActionRow(
                icon = Icons.Outlined.BookmarkBorder,
                label = strings.addToShelf,
                onClick = onOpenShelfPicker,
            )
            if (selectedResource != null && selectedDownload?.isReadable != true) {
                WorkActionRow(
                    icon = if (isDownloading) Icons.Outlined.PauseCircle else Icons.Outlined.CloudDownload,
                    label = if (isDownloading) strings.pauseDownload else strings.download,
                    onClick = {
                        if (isDownloading) {
                            onCancelDownload(selectedResource.id)
                        } else {
                            onDownloadResource(selectedResource.id)
                        }
                    },
                )
            }
            Text(
                text = strings.readingStatus,
                style = theme.typography.sectionTitle,
                modifier = Modifier.padding(top = theme.spacing.one),
            )
            WorkReadingStatusChoices(
                selected = selectedReadingStatus,
                strings = strings,
                onSelect = onSelectReadingStatus,
            )
            WarmPageTextAction(
                label = strings.cancel,
                onClick = onDismiss,
                modifier = Modifier.align(Alignment.End),
            )
        }
    }
}

internal data class WorkActionsSheetStrings(
    val title: String,
    val addToShelf: String,
    val download: String,
    val pauseDownload: String,
    val readingStatus: String,
    val unread: String,
    val reading: String,
    val finished: String,
    val cancel: String,
)

@Composable
internal fun WorkReadingStatusChoices(
    selected: WorkReadingStatus,
    strings: WorkActionsSheetStrings,
    onSelect: (WorkReadingStatus) -> Unit,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .selectableGroup()
            .testTag("work-reading-status-choices"),
    ) {
        workReadingStatusChoices().forEach { status ->
            val isSelected = status == selected
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = theme.components.controls.minimumTouchTarget)
                    .selectable(
                        selected = isSelected,
                        role = Role.RadioButton,
                        onClick = { onSelect(status) },
                    )
                    .testTag("work-reading-status-${status.name.lowercase(Locale.ROOT)}"),
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(
                    selected = isSelected,
                    onClick = null,
                )
                Text(
                    text = strings.label(status),
                    style = theme.typography.body,
                    color = theme.colors.textPrimary,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

private fun WorkActionsSheetStrings.label(status: WorkReadingStatus): String = when (status) {
    WorkReadingStatus.Unread -> unread
    WorkReadingStatus.Reading -> reading
    WorkReadingStatus.Finished -> finished
}

@Composable
private fun WorkActionRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    onClick: () -> Unit,
) {
    val theme = WarmPageThemeValues
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = theme.components.controls.minimumTouchTarget)
                .clickable(onClick = onClick)
                .padding(vertical = theme.spacing.one),
            horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = theme.colors.textSecondary,
                modifier = Modifier.size(theme.components.controls.iconSize),
            )
            Text(
                text = label,
                style = theme.typography.body,
                color = theme.colors.textPrimary,
                modifier = Modifier.weight(1f),
            )
        }
        HorizontalDivider(
            thickness = theme.components.dividerThickness,
            color = theme.colors.divider,
        )
    }
}

private fun WorkDetailUiState.resolveSelectedResource(): ResourceContent? {
    val resources = content?.resources.orEmpty()
    return selectedResourceId?.let { id -> resources.firstOrNull { it.id == id } }
        ?: resources.firstOrNull { it.selected }
        ?: resources.firstOrNull()
}

@Composable
private fun primaryActionLabel(label: WorkDetailPrimaryActionLabel): String = stringResource(
    when (label) {
        WorkDetailPrimaryActionLabel.StartReading -> R.string.work_primary_start_read_action
        WorkDetailPrimaryActionLabel.ContinueReading -> R.string.work_primary_read_action
        WorkDetailPrimaryActionLabel.StartListening -> R.string.work_primary_start_listen_action
        WorkDetailPrimaryActionLabel.ContinueListening -> R.string.work_primary_listen_action
    },
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ShelfPickerSheet(
    state: WorkDetailUiState,
    strings: ShelfPickerSheetStrings,
    onDismiss: () -> Unit,
    onToggleShelf: (String) -> Unit,
    onSave: () -> Unit,
) {
    val theme = WarmPageThemeValues
    WarmPageModalBottomSheet(
        onDismissRequest = onDismiss,
        modifier = Modifier.testTag("work-shelf-picker-sheet"),
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(
                    horizontal = theme.components.page.compactGutter,
                    vertical = theme.spacing.two,
                ),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
        ) {
            WarmPageSectionHeader(
                title = strings.title,
                modifier = Modifier.testTag("work-shelf-picker-title"),
            )
            when {
                state.isLoadingShelves -> WarmPageLoadingState(
                    modifier = Modifier.fillMaxWidth(),
                )
                state.shelfErrorCode != null -> WarmPageErrorState(
                    title = strings.title,
                    message = strings.loadFailed,
                    retryLabel = strings.cancel,
                    onRetry = onDismiss,
                )
                state.shelves.isEmpty() -> WarmPageEmptyState(
                    title = strings.title,
                    message = strings.empty,
                )
                else -> {
                    state.shelves.forEach { shelf ->
                        val isSelected = shelf.id in state.selectedShelfIds
                        val editable = shelf.kind == com.ermao.library.shared.modules.shelf.domain.ShelfKind.Static
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .heightIn(min = theme.components.controls.minimumTouchTarget)
                                .toggleable(
                                    value = isSelected,
                                    enabled = editable && !state.isSavingShelves,
                                    role = Role.Checkbox,
                                    onValueChange = { onToggleShelf(shelf.id) },
                                )
                                .testTag("work-shelf-row-${shelf.id}"),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(
                                checked = isSelected,
                                onCheckedChange = null,
                                enabled = editable && !state.isSavingShelves,
                            )
                            Text(shelf.name, style = theme.typography.body, modifier = Modifier.weight(1f))
                        }
                    }
                    WarmPagePrimaryAction(
                        label = strings.save,
                        onClick = onSave,
                        enabled = !state.isSavingShelves,
                        loading = state.isSavingShelves,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
    }
}

private data class ShelfPickerSheetStrings(
    val title: String,
    val loadFailed: String,
    val cancel: String,
    val empty: String,
    val save: String,
)
