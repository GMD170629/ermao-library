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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudDownload
import androidx.compose.material.icons.outlined.Equalizer
import androidx.compose.material.icons.outlined.KeyboardArrowDown
import androidx.compose.material.icons.outlined.KeyboardArrowUp
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.PauseCircle
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Source
import androidx.compose.material.icons.outlined.Splitscreen
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
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.testTag
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
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.ermao.library.R
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.VolumeContent
import com.ermao.library.features.content.model.WorkDetailContent
import com.ermao.library.features.content.ui.ContentCover
import com.ermao.library.features.content.ui.CoverProgress
import com.ermao.library.features.content.ui.CoverRole
import com.ermao.library.features.content.ui.ReadingProgressTrack
import com.ermao.library.features.content.ui.WorkCover
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
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
import com.ermao.library.ui.components.WarmPageIconAction
import com.ermao.library.ui.components.WarmPageFloatingActionMenu
import com.ermao.library.ui.components.WarmPageFloatingMenuAction
import com.ermao.library.ui.components.WarmPageTopBarRole
import com.ermao.library.ui.components.warmPageActionHorizontalPadding
import com.ermao.library.ui.theme.WarmPageThemeValues
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.isSupportedNativeReaderEntry
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
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
    data class Volume(val value: VolumeContent) : WorkControlMenuTarget
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
    AddSeries, AddShelf, MarkUnread, Download, Edit, Recognize, UploadCover,
    RegenerateCover, SendToKindle, Delete,
}

private enum class VolumeControlAction {
    MarkUnread, Download, Edit, ChangeMediaType, Split, SendToKindle, Delete,
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkDetailScreen(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
    onBack: () -> Unit,
    onSelectVersion: (String) -> Unit,
    onSelectVolume: (String) -> Unit,
    onLoadMoreVolumes: () -> Unit = {},
    onOpenShelfPicker: () -> Unit,
    onDismissShelfPicker: () -> Unit,
    onToggleShelf: (String) -> Unit,
    onSaveShelves: () -> Unit,
    onShelfSaveFeedbackShown: () -> Unit,
    onViewShelves: () -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    onRetry: () -> Unit,
    onRefresh: () -> Unit = {},
    downloadRecordsByVolume: Map<String, AndroidDownloadRecord> = emptyMap(),
    downloadFailuresByVolume: Map<String, String> = emptyMap(),
    onDownloadVolume: (String) -> Unit = {},
    onCancelDownload: (String) -> Unit = {},
    onRemoveDownload: (AndroidDownloadRecord) -> Unit = {},
    onOpenSelectedVolume: (VolumeContent) -> Unit = {},
    onSelectReadingStatus: (WorkReadingStatus) -> Unit = {},
    managementViewModel: WorkManagementViewModel? = null,
    canManageSystem: Boolean = managementViewModel != null,
) {
    var controlMenuState by remember { mutableStateOf<WorkControlMenuState?>(null) }
    var managementSheetState by remember { mutableStateOf<WorkManagementSheetState?>(null) }
    val selectedVolume = state.resolveSelectedVolume()
    var readingStatusOverride by remember(state.content?.work?.id, selectedVolume?.id) {
        mutableStateOf<WorkReadingStatus?>(null)
    }
    var pendingDownloadRemoval by remember { mutableStateOf<AndroidDownloadRecord?>(null) }
    val snackbarHostState = remember { SnackbarHostState() }
    val snackbarScope = rememberCoroutineScope()
    val shelvesUpdatedMessage = stringResource(R.string.work_shelves_updated)
    val managementUpdatedMessage = stringResource(R.string.management_updated)
    val viewShelvesLabel = stringResource(R.string.view_shelves_action)
    val shelfPickerSheetStrings = ShelfPickerSheetStrings(
        title = stringResource(R.string.work_shelf_picker_title),
        loadFailed = stringResource(R.string.work_shelf_load_failed),
        cancel = stringResource(R.string.cancel_action),
        empty = stringResource(R.string.work_shelf_empty),
        save = stringResource(R.string.work_shelf_save),
    )
    val currentReadingStatus = readingStatusOverride ?: selectedVolume?.let { volume ->
        workReadingStatus(
            completed = state.content?.completed == true || (volume.progressPercent ?: 0) >= 100,
            progressPercent = volume.progressPercent,
        )
    } ?: WorkReadingStatus.Unread
    val managementState by managementViewModel?.uiState?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf(null) }
    val managementFailureMessage = stringResource(
        R.string.management_failed,
        managementState?.errorCode.orEmpty(),
    )
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { onRefresh() }
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
    WarmPageScaffold(
        role = WarmPageTopBarRole.Detail,
        title = stringResource(R.string.work_detail_title),
        modifier = modifier.testTag("work-detail"),
        navigation = WarmPageNavigationAction(
            icon = Icons.AutoMirrored.Filled.ArrowBack,
            label = stringResource(R.string.navigate_back),
            onClick = onBack,
        ),
        actions = emptyList(),
        snackbarHost = { WarmPageSnackbarHost(snackbarHostState) },
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
                onSelectVersion = onSelectVersion,
                onSelectVolume = onSelectVolume,
                onLoadMoreVolumes = onLoadMoreVolumes,
                onOpenShelfPicker = onOpenShelfPicker,
                readingStatus = currentReadingStatus,
                onToggleReadingStatus = {
                    val next = nextWorkReadingStatus(currentReadingStatus)
                    readingStatusOverride = next
                    val managedStatus = if (next == WorkReadingStatus.Finished) {
                        ManagedReadingStatus.Finished
                    } else {
                        ManagedReadingStatus.Unread
                    }
                    if (selectedVolume != null && managementViewModel != null) {
                        managementViewModel.setReadingStatus(selectedVolume.id, managedStatus)
                    } else {
                        onSelectReadingStatus(next)
                    }
                },
                onOpenBookControl = { anchor ->
                    controlMenuState = WorkControlMenuState(WorkControlMenuTarget.Book, anchor)
                },
                onOpenFacet = onOpenFacet,
                downloadRecordsByVolume = downloadRecordsByVolume,
                downloadFailuresByVolume = downloadFailuresByVolume,
                onDownloadVolume = onDownloadVolume,
                onCancelDownload = onCancelDownload,
                onRequestRemoveDownload = { pendingDownloadRemoval = it },
                onOpenSelectedVolume = onOpenSelectedVolume,
                onOpenVolumeControl = { volume, anchor ->
                    controlMenuState = WorkControlMenuState(WorkControlMenuTarget.Volume(volume), anchor)
                },
                modifier = Modifier.padding(padding),
            )
        }
    }

    pendingDownloadRemoval?.let { download ->
        AlertDialog(
            onDismissRequest = { pendingDownloadRemoval = null },
            title = { Text(stringResource(R.string.downloads_remove_title)) },
            text = { Text(stringResource(R.string.downloads_remove_message, download.volumeTitle)) },
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
            selectedVolume = selectedVolume,
            repository = repository,
            context = context,
            canManageSystem = canManageSystem,
            selectedDownload = when (val target = activeMenu.target) {
                WorkControlMenuTarget.Book -> selectedVolume?.let { downloadRecordsByVolume[it.id] }
                is WorkControlMenuTarget.Volume -> downloadRecordsByVolume[target.value.id]
            },
            onAddShelf = {
                controlMenuState = null
                onOpenShelfPicker()
            },
            onMarkUnread = { volume ->
                controlMenuState = null
                readingStatusOverride = WorkReadingStatus.Unread
                if (managementViewModel != null) {
                    managementViewModel.setReadingStatus(volume.id, ManagedReadingStatus.Unread)
                } else {
                    onSelectReadingStatus(WorkReadingStatus.Unread)
                }
            },
            onDownload = { volume ->
                controlMenuState = null
                val download = downloadRecordsByVolume[volume.id]
                when {
                    download?.isReadable == true -> onRemoveDownload(download)
                    download?.status in setOf(
                        AndroidDownloadStatus.Queued,
                        AndroidDownloadStatus.Downloading,
                        AndroidDownloadStatus.Verifying,
                    ) -> onCancelDownload(volume.id)
                    else -> onDownloadVolume(volume.id)
                }
            },
            onBookTask = bookTask@{ action ->
                controlMenuState = null
                val task = when (action) {
                    BookControlAction.AddSeries -> WorkManagementTask.AddSeries
                    BookControlAction.Edit -> WorkManagementTask.EditWork
                    BookControlAction.Recognize -> WorkManagementTask.Recognize
                    BookControlAction.UploadCover,
                    BookControlAction.RegenerateCover,
                    -> WorkManagementTask.Cover
                    BookControlAction.SendToKindle -> WorkManagementTask.Kindle
                    BookControlAction.Delete -> WorkManagementTask.DeleteWork
                    BookControlAction.AddShelf,
                    BookControlAction.MarkUnread,
                    BookControlAction.Download,
                    -> return@bookTask
                }
                val target = if (action == BookControlAction.SendToKindle && selectedVolume != null) {
                    WorkManagementTarget.Volume(selectedVolume)
                } else {
                    WorkManagementTarget.Work
                }
                managementSheetState = WorkManagementSheetState(task, target)
            },
            onVolumeTask = volumeTask@{ action, volume ->
                controlMenuState = null
                val task = when (action) {
                    VolumeControlAction.Edit -> WorkManagementTask.EditVolume
                    VolumeControlAction.ChangeMediaType -> WorkManagementTask.MediaKind
                    VolumeControlAction.Split -> WorkManagementTask.Split
                    VolumeControlAction.SendToKindle -> WorkManagementTask.Kindle
                    VolumeControlAction.Delete -> WorkManagementTask.DeleteVolume
                    VolumeControlAction.MarkUnread,
                    VolumeControlAction.Download,
                    -> return@volumeTask
                }
                managementSheetState = WorkManagementSheetState(task, WorkManagementTarget.Volume(volume))
            },
            onDismiss = { controlMenuState = null },
        )
    }
    val activeManagementSheet = managementSheetState
    if (activeManagementSheet != null && state.content != null && managementViewModel != null) {
        WorkManagementTaskSheet(
            task = activeManagementSheet.task,
            target = activeManagementSheet.target,
            content = state.content,
            state = requireNotNull(managementState),
            viewModel = managementViewModel,
            downloadRecordsByVolume = downloadRecordsByVolume,
            workCover = {
                WorkCover(
                    work = state.content.work,
                    repository = repository,
                    context = context,
                    role = CoverRole.Compact,
                )
            },
            onDismiss = { managementSheetState = null },
        )
    }
    LaunchedEffect(managementState?.completedMutation) {
        val completion = managementState?.completedMutation ?: return@LaunchedEffect
        managementSheetState = null
        if (completion == WorkManagementCompletion.WorkDeleted) onBack() else onRefresh()
        snackbarHostState.currentSnackbarData?.dismiss()
        snackbarHostState.showSnackbar(managementUpdatedMessage)
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
}

@Composable
private fun WorkDetailBody(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onSelectVersion: (String) -> Unit,
    onSelectVolume: (String) -> Unit,
    onLoadMoreVolumes: () -> Unit,
    onOpenShelfPicker: () -> Unit,
    readingStatus: WorkReadingStatus,
    onToggleReadingStatus: () -> Unit,
    onOpenBookControl: (Offset) -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    downloadRecordsByVolume: Map<String, AndroidDownloadRecord>,
    downloadFailuresByVolume: Map<String, String>,
    onDownloadVolume: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    onRequestRemoveDownload: (AndroidDownloadRecord) -> Unit,
    onOpenSelectedVolume: (VolumeContent) -> Unit,
    onOpenVolumeControl: (VolumeContent, Offset) -> Unit,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    val content = requireNotNull(state.content)
    val selectedVersion = content.versions.firstOrNull { it.id == state.selectedVersionId }
        ?: content.versions.firstOrNull()
    val selectedVolume = state.resolveSelectedVolume()
    LazyColumn(
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
                selectedVolume = selectedVolume,
                selectedDownload = selectedVolume?.let { volume -> downloadRecordsByVolume[volume.id] },
                onOpenShelfPicker = onOpenShelfPicker,
                readingStatus = readingStatus,
                onToggleReadingStatus = onToggleReadingStatus,
                onOpenBookControl = onOpenBookControl,
                onDownloadVolume = onDownloadVolume,
                onCancelDownload = onCancelDownload,
                onRequestRemoveDownload = onRequestRemoveDownload,
                onOpenSelectedVolume = onOpenSelectedVolume,
            )
        }
        if (content.hasDescription) item { WorkAboutSection(content) }
        if (content.showsVersionPicker) {
            item {
                WorkMediaPicker(
                    options = content.versions.map { version ->
                        WarmPageChoice(version.id, versionLabel(version))
                    },
                    selected = state.selectedVersionId ?: content.versions.first().id,
                    onSelect = onSelectVersion,
                )
            }
        }
        if (selectedVersion == null || selectedVersion.volumes.isEmpty()) {
            item {
                WarmPageEmptyState(
                    title = stringResource(R.string.work_no_readable_volumes),
                    message = stringResource(R.string.work_reader_next_phase_message),
                )
            }
        } else {
            item {
                WorkVolumeRail(
                    volumes = selectedVersion.volumes,
                    selectedVolumeId = selectedVolume?.id,
                    totalVolumes = selectedVersion.volumeCount,
                    isLoadingMore = state.isLoadingMoreVolumes,
                    paginationErrorCode = state.volumePaginationErrorCode,
                    repository = repository,
                    context = context,
                    downloadRecordsByVolume = downloadRecordsByVolume,
                    downloadFailuresByVolume = downloadFailuresByVolume,
                    onSelectVolume = onSelectVolume,
                    onLoadMore = onLoadMoreVolumes,
                    onManageVolume = onOpenVolumeControl,
                    managementAvailable = true,
                )
            }
        }
        selectedVolume?.let { volume -> item { SelectedVolumeMetadata(volume) } }
    }
}

@Composable
private fun WorkDetailActionRow(
    selectedVolume: VolumeContent?,
    selectedDownload: AndroidDownloadRecord?,
    onOpenShelfPicker: () -> Unit,
    readingStatus: WorkReadingStatus,
    onToggleReadingStatus: () -> Unit,
    onOpenBookControl: (Offset) -> Unit,
    onDownloadVolume: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    onRequestRemoveDownload: (AndroidDownloadRecord) -> Unit,
    onOpenSelectedVolume: (VolumeContent) -> Unit,
) {
    val theme = WarmPageThemeValues
    val primaryAction = workDetailPrimaryActionPresentation(
        selectedVolume = selectedVolume,
        download = selectedDownload,
    )
    val primaryLabel = primaryActionLabel(primaryAction.label)
    val downloadAction = workDetailDownloadActionPresentation(selectedDownload)
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        WarmPagePrimaryAction(
            label = primaryLabel,
            trailingIcon = if (primaryAction.intent == WorkDetailPrimaryActionIntent.DownloadThenRead) {
                Icons.Outlined.CloudDownload
            } else {
                Icons.Filled.PlayArrow
            },
            onClick = {
                selectedVolume?.let { volume ->
                    when (primaryAction.intent) {
                        WorkDetailPrimaryActionIntent.OpenSelectedVolume -> onOpenSelectedVolume(volume)
                        WorkDetailPrimaryActionIntent.DownloadThenRead -> onDownloadVolume(volume.id)
                        WorkDetailPrimaryActionIntent.AwaitDownload,
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
                    -> Icons.Outlined.CloudDownload
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
                    selectedVolume?.let { volume ->
                        when (downloadAction) {
                            WorkDetailDownloadAction.Downloading -> onCancelDownload(volume.id)
                            WorkDetailDownloadAction.NotDownloaded,
                            WorkDetailDownloadAction.Paused,
                            WorkDetailDownloadAction.Failed,
                            -> onDownloadVolume(volume.id)
                            WorkDetailDownloadAction.Downloaded -> Unit
                        }
                    }
                },
                onLongClick = selectedDownload?.takeIf { it.isReadable }?.let { download ->
                    { onRequestRemoveDownload(download) }
                },
                longClickLabel = stringResource(R.string.work_quick_remove_download),
                enabled = selectedVolume != null,
                modifier = Modifier.weight(1f),
                testTag = "work-download-action",
            )
            WorkDetailQuickAction(
                icon = if (readingStatus == WorkReadingStatus.Finished) {
                    Icons.Outlined.CheckCircle
                } else {
                    Icons.Outlined.Equalizer
                },
                label = stringResource(
                    if (readingStatus == WorkReadingStatus.Finished) {
                        R.string.work_quick_reading_read
                    } else {
                        R.string.work_quick_reading_unread
                    },
                ),
                onClick = onToggleReadingStatus,
                enabled = selectedVolume != null,
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
            selectedVolume?.readerType.equals("audio", ignoreCase = true) -> R.string.work_audiobook_player_unavailable
            selectedVolume == null -> R.string.work_reader_next_phase_message
            !isSupportedNativeReaderEntry(selectedVolume.readerType, selectedVolume.format) ->
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
        )
        Text(
            text = label,
            style = theme.typography.caption,
            color = if (enabled) theme.colors.textSecondary else theme.colors.textTertiary,
        )
    }
}

@Composable
private fun IdentityHeader(
    content: WorkDetailContent,
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
        WorkCover(
            content.work,
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
    content: WorkDetailContent,
    onOpenFacet: (LibraryScope, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val presentation = workDetailIdentityPresentation(
        tags = content.tags,
        completed = content.completed,
        progressPercent = content.work.progressPercent,
    )
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
    ) {
        presentation.elements.forEach { element ->
            when (element) {
                WorkDetailIdentityElement.Title -> Text(
                    content.work.title,
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
    content: WorkDetailContent,
    onOpenFacet: (LibraryScope, String) -> Unit,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = Modifier.fillMaxWidth().testTag("work-creator-series-line"),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FacetLink(
            label = content.work.author,
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
private fun ReadingSummary(content: WorkDetailContent) {
    val theme = WarmPageThemeValues
    val progress = content.work.progressPercent ?: 0
    if (progress <= 0) return
    val currentPosition = content.readingUnits
        .firstOrNull { it.readingState == ChapterReadingState.Current }
        ?.title
    val layout = workDetailSummaryLayout(LocalDensity.current.fontScale)
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        if (layout == WorkDetailSummaryLayout.Stacked) {
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
            stateDescription = stringResource(R.string.work_volume_accessibility_progress, progress),
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
                    stringResource(R.string.work_media_versions_title),
                    style = theme.typography.sectionTitle,
                )
                Spacer(Modifier.weight(1f))
                Box(Modifier.width(workDetailMediaControlWidth(options.size))) {
                    WarmPageSegmentedControl(options = options, selected = selected, onSelect = onSelect)
                }
            }
            WorkDetailMediaPickerLayout.VerticalChoices -> Column {
                Text(stringResource(R.string.work_media_versions_title), style = theme.typography.sectionTitle)
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
    content: WorkDetailContent,
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
            WarmPageIconAction(
                icon = if (expanded) Icons.Outlined.KeyboardArrowUp else Icons.Outlined.KeyboardArrowDown,
                label = stringResource(if (expanded) R.string.work_collapse else R.string.work_expand),
                onClick = { expanded = !expanded },
                modifier = Modifier.align(Alignment.CenterHorizontally),
            )
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
private fun WorkVolumeRail(
    volumes: List<VolumeContent>,
    selectedVolumeId: String?,
    totalVolumes: Int,
    isLoadingMore: Boolean,
    paginationErrorCode: String?,
    repository: ContentRepository,
    context: ContentRequestContext,
    downloadRecordsByVolume: Map<String, AndroidDownloadRecord>,
    downloadFailuresByVolume: Map<String, String>,
    onSelectVolume: (String) -> Unit,
    onLoadMore: () -> Unit,
    onManageVolume: (VolumeContent, Offset) -> Unit,
    managementAvailable: Boolean,
) {
    val theme = WarmPageThemeValues
    val listState = rememberLazyListState()
    LaunchedEffect(listState, volumes.size, totalVolumes, isLoadingMore) {
        snapshotFlow { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1 }
            .distinctUntilChanged()
            .filter { index -> index >= volumes.lastIndex - 2 && volumes.size < totalVolumes && !isLoadingMore }
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
                itemsIndexed(volumes, key = { _, volume -> volume.id }) { position, volume ->
                    VolumeCoverItem(
                        volume = volume,
                        position = position,
                        selected = volume.id == selectedVolumeId,
                        repository = repository,
                        context = context,
                        download = downloadRecordsByVolume[volume.id],
                        downloadFailure = downloadFailuresByVolume[volume.id],
                        onSelectVolume = onSelectVolume,
                        onManageVolume = onManageVolume,
                        managementAvailable = managementAvailable,
                        modifier = Modifier.width(itemWidth),
                    )
                }
                if (isLoadingMore || paginationErrorCode != null) {
                    item(key = "volume-pagination-tail") {
                        Box(
                            modifier = Modifier
                                .width(itemWidth)
                                .heightIn(min = theme.metrics.androidMinimumTouchTarget)
                                .clickable(enabled = paginationErrorCode != null, onClick = onLoadMore),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = stringResource(
                                    if (paginationErrorCode == null) R.string.work_volume_loading_more
                                    else R.string.work_volume_load_more_failed,
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
private fun SelectedVolumeMetadata(volume: VolumeContent) {
    val locale = LocalConfiguration.current.locales[0]
    var fullPath by remember(volume.id) { mutableStateOf<String?>(null) }
    val rows = listOf(
        Triple(R.string.work_metadata_format, volume.format, false),
        Triple(R.string.work_metadata_language, volume.language, false),
        Triple(R.string.work_metadata_published, formatWorkMetadataDate(volume.publishedAt, locale), false),
        Triple(R.string.work_metadata_page_count, volume.pageCount?.let {
            pluralStringResource(R.plurals.work_metadata_page_count_value, it, it)
        }, false),
        Triple(R.string.work_metadata_source, volume.metadataSource, false),
        Triple(R.string.work_metadata_file_path, volume.files.firstOrNull()?.path, true),
    )
    val theme = WarmPageThemeValues
    Column(Modifier.fillMaxWidth().testTag("work-selected-volume-metadata")) {
        Text(stringResource(R.string.work_volume_metadata_title), style = theme.typography.sectionTitle)
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

internal enum class WorkDetailSummaryLayout {
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
    DownloadThenRead,
    AwaitDownload,
    Unavailable,
}

internal enum class WorkDetailPrimaryActionLabel {
    StartReading,
    ContinueReading,
    DownloadToRead,
    Downloading,
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
    selectedVolume: VolumeContent?,
    download: AndroidDownloadRecord?,
): WorkDetailPrimaryActionPresentation {
    val hasProgress = (selectedVolume?.progressPercent ?: 0) > 0
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
    if (selectedVolume?.readerType.equals("audio", ignoreCase = true)) {
        return WorkDetailPrimaryActionPresentation(
            intent = WorkDetailPrimaryActionIntent.Unavailable,
            label = listeningLabel,
            enabled = false,
        )
    }
    if (selectedVolume == null || !selectedVolume.readable ||
        !isSupportedNativeReaderEntry(selectedVolume.readerType, selectedVolume.format)
    ) {
        return WorkDetailPrimaryActionPresentation(
            intent = WorkDetailPrimaryActionIntent.Unavailable,
            label = readingLabel,
            enabled = false,
        )
    }
    val completedArtifactAvailable = download?.volumeId == selectedVolume.id && download.isReadable
    if (selectedVolume.readerType.equals("reflowable", ignoreCase = true) && !completedArtifactAvailable) {
        val downloadInProgress = download?.status in setOf(
            AndroidDownloadStatus.Queued,
            AndroidDownloadStatus.Downloading,
            AndroidDownloadStatus.Verifying,
        )
        return WorkDetailPrimaryActionPresentation(
            intent = if (downloadInProgress) {
                WorkDetailPrimaryActionIntent.AwaitDownload
            } else {
                WorkDetailPrimaryActionIntent.DownloadThenRead
            },
            label = if (downloadInProgress) {
                WorkDetailPrimaryActionLabel.Downloading
            } else {
                WorkDetailPrimaryActionLabel.DownloadToRead
            },
            enabled = !downloadInProgress,
        )
    }
    return WorkDetailPrimaryActionPresentation(
        intent = WorkDetailPrimaryActionIntent.OpenSelectedVolume,
        label = readingLabel,
        enabled = true,
    )
}

internal fun workDetailVolumePresentation(
    volume: VolumeContent,
    selected: Boolean,
    download: AndroidDownloadRecord?,
): WorkDetailVolumePresentation {
    val progress = volume.progressPercent?.coerceIn(0, 100) ?: 0
    val readingState = when {
        progress >= 100 -> WorkDetailVolumeReadingState.Finished
        progress > 0 -> WorkDetailVolumeReadingState.Reading
        else -> WorkDetailVolumeReadingState.Unread
    }
    val downloadState = when {
        download?.volumeId == volume.id && download.isReadable -> WorkDetailVolumeDownloadState.Downloaded
        download?.volumeId == volume.id && download.status in setOf(
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

internal fun workDetailSummaryLayout(fontScale: Float): WorkDetailSummaryLayout =
    if (fontScale >= WORK_DETAIL_STACKED_LAYOUT_FONT_SCALE) {
        WorkDetailSummaryLayout.Stacked
    } else {
        WorkDetailSummaryLayout.Inline
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
private fun VolumeCoverItem(
    volume: VolumeContent,
    position: Int,
    selected: Boolean,
    repository: ContentRepository,
    context: ContentRequestContext,
    download: AndroidDownloadRecord?,
    downloadFailure: String?,
    onSelectVolume: (String) -> Unit,
    onManageVolume: (VolumeContent, Offset) -> Unit,
    managementAvailable: Boolean,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val index = volume.displayIndex(position)
    val progress = volume.progressPercent?.coerceIn(0, 100) ?: 0
    val presentation = workDetailVolumePresentation(volume, selected, download)
    val state = when (presentation.readingState) {
        WorkDetailVolumeReadingState.Finished -> stringResource(R.string.work_volume_accessibility_finished)
        WorkDetailVolumeReadingState.Reading -> stringResource(R.string.work_volume_accessibility_progress, progress)
        WorkDetailVolumeReadingState.Unread -> stringResource(R.string.work_volume_accessibility_not_started)
    }
    val manageVolumeLabel = stringResource(R.string.management_volume)
    val volumeLabel = stringResource(R.string.work_volume_accessibility_label, index, volume.title)
    var coverPositionInWindow by remember(volume.id) { mutableStateOf(Offset.Zero) }
    var coverSize by remember(volume.id) { mutableStateOf(androidx.compose.ui.unit.IntSize.Zero) }
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
                    .pointerInput(volume.id, managementAvailable) {
                        detectTapGestures(
                            onTap = { onSelectVolume(volume.id) },
                            onLongPress = { localPress ->
                                if (managementAvailable) {
                                    onManageVolume(volume, coverPositionInWindow + localPress)
                                }
                            },
                        )
                    }
                    .semantics(mergeDescendants = true) {
                        contentDescription = volumeLabel
                        this.selected = selected
                        stateDescription = state
                        if (managementAvailable) {
                            customActions = listOf(
                                CustomAccessibilityAction(manageVolumeLabel) {
                                    onManageVolume(volume, coverCenter())
                                    true
                                },
                            )
                        }
                    }
                    .testTag("work-volume-${volume.id}"),
            ) {
                ContentCover(
                    contentId = volume.id,
                    title = volume.title,
                    coverUrl = volume.coverUrl,
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
                        contentDescription = stringResource(R.string.work_volume_selected),
                        tint = theme.colors.brandAccent,
                        modifier = Modifier.padding(theme.spacing.half),
                    )
                }
            }
        }
        Text(
            volume.title,
            style = theme.typography.callout,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            when {
                progress > 0 && progress < 100 -> stringResource(R.string.work_volume_reading_badge, progress)
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
    content: WorkDetailContent,
    selectedVolume: VolumeContent?,
    repository: ContentRepository,
    context: ContentRequestContext,
    canManageSystem: Boolean,
    selectedDownload: AndroidDownloadRecord?,
    onAddShelf: () -> Unit,
    onMarkUnread: (VolumeContent) -> Unit,
    onDownload: (VolumeContent) -> Unit,
    onBookTask: (BookControlAction) -> Unit,
    onVolumeTask: (VolumeControlAction, VolumeContent) -> Unit,
    onDismiss: () -> Unit,
) {
    val menuVolume = when (target) {
        WorkControlMenuTarget.Book -> selectedVolume
        is WorkControlMenuTarget.Volume -> target.value
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
    val kindleEligible = menuVolume?.files?.any { file ->
        file.path.endsWith(".epub", ignoreCase = true) || file.path.endsWith(".pdf", ignoreCase = true)
    } == true
    when (target) {
        WorkControlMenuTarget.Book -> {
            val actions = buildList {
                if (canManageSystem) add(
                    WarmPageFloatingMenuAction(
                        BookControlAction.AddSeries,
                        stringResource(R.string.work_control_add_series),
                        Icons.Outlined.Layers,
                    ),
                )
                add(
                    WarmPageFloatingMenuAction(
                        BookControlAction.AddShelf,
                        stringResource(R.string.work_control_add_shelf),
                        Icons.Outlined.BookmarkBorder,
                    ),
                )
                add(
                    WarmPageFloatingMenuAction(
                        BookControlAction.MarkUnread,
                        stringResource(R.string.work_control_mark_unread),
                        Icons.Outlined.BookmarkBorder,
                        enabled = menuVolume != null,
                    ),
                )
                add(
                    WarmPageFloatingMenuAction(
                        BookControlAction.Download,
                        downloadLabel,
                        if (selectedDownload?.status in setOf(
                                AndroidDownloadStatus.Queued,
                                AndroidDownloadStatus.Downloading,
                                AndroidDownloadStatus.Verifying,
                            )
                        ) Icons.Outlined.PauseCircle else Icons.Outlined.CloudDownload,
                        enabled = menuVolume != null,
                    ),
                )
                if (canManageSystem) {
                    add(WarmPageFloatingMenuAction(BookControlAction.Edit, stringResource(R.string.work_control_edit), Icons.Outlined.Edit))
                    add(WarmPageFloatingMenuAction(BookControlAction.Recognize, stringResource(R.string.work_control_recognize), Icons.Outlined.Source))
                    add(WarmPageFloatingMenuAction(BookControlAction.UploadCover, stringResource(R.string.work_control_upload_cover), Icons.Outlined.Image))
                    add(WarmPageFloatingMenuAction(BookControlAction.RegenerateCover, stringResource(R.string.work_control_regenerate_cover), Icons.Outlined.Refresh))
                    if (kindleEligible) add(
                        WarmPageFloatingMenuAction(
                            BookControlAction.SendToKindle,
                            stringResource(R.string.work_control_send_kindle),
                            Icons.AutoMirrored.Outlined.Send,
                        ),
                    )
                    add(
                        WarmPageFloatingMenuAction(
                            BookControlAction.Delete,
                            stringResource(R.string.work_control_delete),
                            Icons.Outlined.DeleteOutline,
                            destructive = true,
                        ),
                    )
                }
            }
            WarmPageFloatingActionMenu(
                actions = actions,
                anchorInWindow = anchorInWindow,
                onSelect = { action ->
                    when (action) {
                        BookControlAction.AddShelf -> onAddShelf()
                        BookControlAction.MarkUnread -> menuVolume?.let(onMarkUnread)
                        BookControlAction.Download -> menuVolume?.let(onDownload)
                        BookControlAction.AddSeries,
                        BookControlAction.Edit,
                        BookControlAction.Recognize,
                        BookControlAction.UploadCover,
                        BookControlAction.RegenerateCover,
                        BookControlAction.SendToKindle,
                        BookControlAction.Delete,
                        -> onBookTask(action)
                    }
                },
                onDismiss = onDismiss,
                modifier = Modifier.testTag("work-book-control-menu"),
                header = {
                    WorkControlMenuHeader(
                        title = content.work.title,
                        subtitle = menuVolume?.let { volume ->
                            stringResource(R.string.work_control_selected_volume_format, volume.title, volume.format)
                        }.orEmpty(),
                        cover = {
                            WorkCover(
                                work = content.work,
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
        is WorkControlMenuTarget.Volume -> {
            val volume = target.value
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
                    add(WarmPageFloatingMenuAction(VolumeControlAction.ChangeMediaType, stringResource(R.string.work_control_change_media_type), Icons.Outlined.Layers, enabled = !activeDownload))
                    add(WarmPageFloatingMenuAction(VolumeControlAction.Split, stringResource(R.string.work_control_split), Icons.Outlined.Splitscreen, enabled = !activeDownload))
                    if (kindleEligible) add(WarmPageFloatingMenuAction(VolumeControlAction.SendToKindle, stringResource(R.string.work_control_send_kindle), Icons.AutoMirrored.Outlined.Send))
                    add(WarmPageFloatingMenuAction(VolumeControlAction.Delete, stringResource(R.string.work_control_delete), Icons.Outlined.DeleteOutline, enabled = !activeDownload, destructive = true))
                }
            }
            WarmPageFloatingActionMenu(
                actions = actions,
                anchorInWindow = anchorInWindow,
                onSelect = { action ->
                    when (action) {
                        VolumeControlAction.MarkUnread -> onMarkUnread(volume)
                        VolumeControlAction.Download -> onDownload(volume)
                        VolumeControlAction.Edit,
                        VolumeControlAction.ChangeMediaType,
                        VolumeControlAction.Split,
                        VolumeControlAction.SendToKindle,
                        VolumeControlAction.Delete,
                        -> onVolumeTask(action, volume)
                    }
                },
                onDismiss = onDismiss,
                modifier = Modifier.testTag("work-volume-control-menu"),
                header = {
                    WorkControlMenuHeader(
                        title = volume.title,
                        subtitle = volume.format,
                        cover = {
                            ContentCover(
                                contentId = volume.id,
                                title = volume.title,
                                coverUrl = volume.coverUrl,
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
    content: WorkDetailContent,
    strings: WorkActionsSheetStrings,
    selectedVolume: VolumeContent?,
    selectedDownload: AndroidDownloadRecord?,
    selectedReadingStatus: WorkReadingStatus,
    onOpenShelfPicker: () -> Unit,
    onDownloadVolume: (String) -> Unit,
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
                listOf(content.work.title, content.work.author).joinToString(" · "),
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
            if (selectedVolume != null && selectedDownload?.isReadable != true) {
                WorkActionRow(
                    icon = if (isDownloading) Icons.Outlined.PauseCircle else Icons.Outlined.CloudDownload,
                    label = if (isDownloading) strings.pauseDownload else strings.download,
                    onClick = {
                        if (isDownloading) {
                            onCancelDownload(selectedVolume.id)
                        } else {
                            onDownloadVolume(selectedVolume.id)
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

private fun WorkDetailUiState.resolveSelectedVolume(): VolumeContent? {
    val content = content ?: return null
    val version = content.versions.firstOrNull { it.id == selectedVersionId }
        ?: content.versions.firstOrNull()
    return version?.volumes?.firstOrNull { it.id == selectedVolumeId }
        ?: version?.volumes?.firstOrNull { it.selected }
        ?: version?.volumes?.firstOrNull()
}

@Composable
private fun versionLabel(version: com.ermao.library.features.content.model.VersionContent): String {
    val implicitTitle = stringResource(R.string.downloads_version_implicit)
    return if (version.sourceKey == com.ermao.library.shared.modules.library.domain.IMPLICIT_WORK_VERSION_SOURCE_KEY) {
        implicitTitle
    } else {
        version.sourceName?.takeIf { it.isNotBlank() } ?: version.sourceKey
    }
}

@Composable
private fun primaryActionLabel(label: WorkDetailPrimaryActionLabel): String = stringResource(
    when (label) {
        WorkDetailPrimaryActionLabel.StartReading -> R.string.work_primary_start_read_action
        WorkDetailPrimaryActionLabel.ContinueReading -> R.string.work_primary_read_action
        WorkDetailPrimaryActionLabel.DownloadToRead -> R.string.work_primary_download_to_read
        WorkDetailPrimaryActionLabel.Downloading -> R.string.work_primary_downloading
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
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .heightIn(min = theme.components.controls.minimumTouchTarget)
                                .toggleable(
                                    value = isSelected,
                                    enabled = !state.isSavingShelves,
                                    role = Role.Checkbox,
                                    onValueChange = { onToggleShelf(shelf.id) },
                                )
                                .testTag("work-shelf-row-${shelf.id}"),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(
                                checked = isSelected,
                                onCheckedChange = null,
                                enabled = !state.isSavingShelves,
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
