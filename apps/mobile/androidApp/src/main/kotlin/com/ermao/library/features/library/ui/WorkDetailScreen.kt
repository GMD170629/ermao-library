package com.ermao.library.features.library.ui

import com.ermao.library.shared.modules.reader.ReaderFormatSupport

import com.ermao.library.features.workmanagement.ManagementAnchor
import com.ermao.library.shared.modules.workmanagement.ManagementMenuContext
import com.ermao.library.features.workmanagement.ManagementIdentityScope
import com.ermao.library.shared.modules.workmanagement.ManagementObject
import com.ermao.library.shared.modules.workmanagement.ManagementTarget
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
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudDownload
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Headphones
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
import androidx.compose.runtime.mutableIntStateOf
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
import androidx.compose.ui.platform.LocalContext
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
import com.ermao.library.shared.modules.library.resolveBookDetailActionScope
import com.ermao.library.shared.modules.library.BookDetailActionScope
import com.ermao.library.shared.modules.library.BookDetailObjectKind
import com.ermao.library.shared.modules.library.BookDetailDownloadState
import com.ermao.library.shared.modules.library.BookDetailDownloadSummary
import com.ermao.library.shared.modules.library.summarizeBookDetailDownloads
import com.ermao.library.features.content.ui.ContentCover
import com.ermao.library.features.content.ui.CoverProgress
import com.ermao.library.features.content.ui.CoverRole
import com.ermao.library.features.content.ui.ReadingProgressTrack
import com.ermao.library.features.content.ui.BookCover
import com.ermao.library.features.content.ui.compactCoverGridColumnCount
import com.ermao.library.features.content.ui.compactCoverGridItemWidth
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
import com.ermao.library.ui.components.WarmPageIconAction
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
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.shared.modules.downloads.DownloadBatchResult
import com.ermao.library.features.workmanagement.application.WorkManagementViewModel
import com.ermao.library.features.workmanagement.application.WorkManagementCompletion
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.platform.persistence.AndroidCoverCache
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.util.Locale
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import androidx.compose.runtime.snapshotFlow

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkDetailScreen(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
    onBack: () -> Unit,
    onSelectResource: (String) -> Unit,
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
    onOpenReadingUnit: (ResourceContent, com.ermao.library.shared.modules.library.domain.ReadingUnit) -> Unit = { _, _ -> },
    onOpenDownloadedResource: (AndroidDownloadRecord) -> Unit = {},
    onSelectReadingStatus: (BookDetailActionScope, WorkReadingStatus) -> Unit = { _, _ -> },
    onReadingStatusChanged: (BookDetailActionScope) -> Unit = {},
    managementViewModel: WorkManagementViewModel? = null,
    canManageSystem: Boolean = managementViewModel != null,
    onBookDeleted: () -> Unit = {},
) {
    var audioUnavailable by remember { mutableStateOf(false) }
    val openResource: (ResourceContent) -> Unit = { resource ->
        if (resource.readerType.equals("audio", true)) audioUnavailable = true else onOpenSelectedResource(resource)
    }
    val selectedResource = state.resolveReadingResource()
    val pageActionScope = state.detailActionScope()
    var pendingReadingStatusScope by remember(state.content?.book?.id) {
        mutableStateOf<BookDetailActionScope?>(null)
    }
    var pendingDownloadRemoval by remember { mutableStateOf<AndroidDownloadRecord?>(null) }
    var coverRefreshToken by remember { mutableIntStateOf(0) }
    val appContext = LocalContext.current.applicationContext
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
    val currentReadingStatus = if (state.isBookRoot) when {
        state.content?.completed == true -> WorkReadingStatus.Finished
        state.content?.resources?.any { (it.progressPercent ?: 0) > 0 } == true -> WorkReadingStatus.Reading
        else -> WorkReadingStatus.Unread
    } else selectedResource?.let { resource ->
        workReadingStatus(
            completed = (resource.progressPercent ?: 0) >= 100,
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
            title = workDetailPageContent(state)?.book?.title ?: stringResource(R.string.work_detail_title),
            modifier = Modifier.fillMaxSize(),
            navigation = WarmPageNavigationAction(
                icon = Icons.AutoMirrored.Filled.ArrowBack,
                label = stringResource(R.string.navigate_back),
                onClick = onBack,
            ),
            actionContent = {
                if (!state.isBookRoot && !state.isLoading && state.content != null &&
                    state.presentation == BookDetailPresentation.ContentBrowser && state.contents != null
                ) {
                    val currentNode = state.contents.currentNode
                    DirectoryControlMenu(
                        onDownload = onOpenMultiDownload,
                        target = ManagementTarget(ManagementObject.Directory, state.content.book.id, currentNode.sourceNodeId, currentNode.title),
                        menuContext = ManagementMenuContext(hasRepresentativeResource = currentNode.representativeResourceId != null),
                    )
                }
            },
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
                    onOpenSourceNode = onOpenSourceNode,
                    onSelectContentsSort = onSelectContentsSort,
                    onSelectContentsPage = onSelectContentsPage,
                    onSelectReadingUnitsPage = onSelectReadingUnitsPage,
                    onRetrySurface = onRetrySurface,
                    onOpenShelfPicker = onOpenShelfPicker,
                    onOpenMultiDownload = onOpenMultiDownload,
                    readingStatus = currentReadingStatus,
                    readingStatusBusy = managementState?.isBusy == true,
                    onToggleReadingStatus = {
                        val next = nextWorkReadingStatus(currentReadingStatus)
                        val managedStatus = if (next == WorkReadingStatus.Finished) {
                            ManagedReadingStatus.Finished
                        } else {
                            ManagedReadingStatus.Unread
                        }
                        if (pageActionScope != null) {
                            pendingReadingStatusScope = pageActionScope
                            if (managementViewModel != null) {
                                if (pageActionScope.objectKind == BookDetailObjectKind.Book) managementViewModel.setReadingStatus(managedStatus)
                                else managementViewModel.setResourceReadingStatus(pageActionScope.objectId, managedStatus)
                            } else {
                                onSelectReadingStatus(pageActionScope, next)
                            }
                        }
                    },
                    onOpenFacet = onOpenFacet,
                    downloadRecordsByResource = downloadRecordsByResource,
                    downloadFailuresByResource = downloadFailuresByResource,
                    onDownloadResource = { resourceId ->
                        run {
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
                    onOpenSelectedResource = openResource,
                    onOpenReadingUnit = { resource, unit ->
                        if (resource.readerType.equals("audio", true)) audioUnavailable = true else onOpenReadingUnit(resource, unit)
                    },
                    onOpenDownloadedResource = onOpenDownloadedResource,
                    coverRefreshToken = coverRefreshToken,
                    listState = detailListState,
                    modifier = Modifier.padding(padding),
                )
            }
        }
    }

    if (audioUnavailable) AlertDialog(
        onDismissRequest = { audioUnavailable = false },
        title = { Text(stringResource(R.string.work_open_player)) },
        text = { Text(stringResource(R.string.work_audiobook_player_unavailable)) },
        confirmButton = { TextButton(onClick = { audioUnavailable = false }) { Text(stringResource(R.string.cancel_action)) } },
    )
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
    LaunchedEffect(managementState?.completedMutation) {
        val completion = managementState?.completedMutation ?: return@LaunchedEffect
        if (completion == WorkManagementCompletion.CoverUpdated) {
            val coverPaths = buildSet {
                state.content?.book?.coverUrl?.takeIf(String::isNotBlank)?.let(::add)
                selectedResource?.coverUrl?.takeIf(String::isNotBlank)?.let(::add)
                managementState?.coverMutation?.coverUrl?.takeIf(String::isNotBlank)?.let(::add)
            }
            coverPaths.forEach { path ->
                runCatching { AndroidCoverCache.invalidate(appContext, context, path) }
            }
            coverRefreshToken += 1
        }
        if (completion == WorkManagementCompletion.BookDeleted) onBookDeleted()
        else if (completion == WorkManagementCompletion.ReadingStatusUpdated && pendingReadingStatusScope != null) {
            onReadingStatusChanged(requireNotNull(pendingReadingStatusScope))
            pendingReadingStatusScope = null
        } else onRefresh()
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
        pendingReadingStatusScope = null
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
            onOpenDownloaded = onOpenDownloadedResource,
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
    onOpenSourceNode: (String?) -> Unit,
    onSelectContentsSort: (BookContentSort) -> Unit,
    onSelectContentsPage: (Int) -> Unit,
    onSelectReadingUnitsPage: (Int) -> Unit,
    onRetrySurface: () -> Unit,
    onOpenShelfPicker: () -> Unit,
    onOpenMultiDownload: () -> Unit,
    readingStatus: WorkReadingStatus,
    readingStatusBusy: Boolean,
    onToggleReadingStatus: () -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    downloadRecordsByResource: Map<String, AndroidDownloadRecord>,
    downloadFailuresByResource: Map<String, String>,
    onDownloadResource: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    onRequestRemoveDownload: (AndroidDownloadRecord) -> Unit,
    onOpenSelectedResource: (ResourceContent) -> Unit,
    onOpenDownloadedResource: (AndroidDownloadRecord) -> Unit,
    onOpenReadingUnit: (ResourceContent, com.ermao.library.shared.modules.library.domain.ReadingUnit) -> Unit,
    coverRefreshToken: Int,
    listState: LazyListState,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    val content = requireNotNull(workDetailPageContent(state))
    val selectedResource = state.resolveSelectedResource()
    val actionScope = state.detailActionScope()
    val readingResource = state.resolveReadingResource()
    val managementTarget = if (state.isBookRoot || state.selectedResourceId != null) ManagementTarget(
        if (state.isBookRoot) ManagementObject.Book else ManagementObject.Resource,
        content.book.id, if (state.isBookRoot) content.book.id else state.selectedResourceId.orEmpty(), content.book.title,
    ) else null
    val managementMenuContext = ManagementMenuContext(completed = state.content?.completed,
        kindleSendAvailable = selectedResource?.kindleSendAvailable == true)
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
        if (state.isBookRoot || state.presentation == BookDetailPresentation.ResourceDetail) item {
            Box(Modifier.testTag("work-identity")) {
                ManagementIdentityScope(managementTarget, managementMenuContext) { IdentityHeader(content, repository, context, onOpenFacet, coverRefreshToken) }
            }
        }
        if (state.isBookRoot && state.presentation == BookDetailPresentation.ContentBrowser && (readingResource?.progressPercent ?: 0) > 0) item {
            BookReadingProgress(readingResource)
        }
        if (actionScope != null) item {
            WorkDetailActionRow(
                managementTarget = managementTarget,
                managementMenuContext = managementMenuContext,
                selectedResource = readingResource,
                showBookActions = actionScope.includesBookActions,
                selectedDownload = readingResource?.let { downloadRecordsByResource[it.id] },
                bookDownloads = if (state.isBookRoot) workBookDownloadSummary(content.book.id, downloadRecordsByResource.values) else null,
                onOpenBookDownloads = onOpenMultiDownload,
                onOpenShelfPicker = onOpenShelfPicker,
                readingStatus = readingStatus,
                readingStatusBusy = readingStatusBusy,
                onToggleReadingStatus = onToggleReadingStatus,
                onDownloadResource = onDownloadResource,
                onCancelDownload = onCancelDownload,
                onRequestRemoveDownload = onRequestRemoveDownload,
                onOpenSelectedResource = onOpenSelectedResource,
                onOpenDownloadedResource = onOpenDownloadedResource,
            )
        }
        if ((state.isBookRoot || state.presentation == BookDetailPresentation.ResourceDetail) && content.hasDescription) {
            item { WorkAboutSection(content) }
        }
        if (selectedResource != null) item { SelectedResourceMetadata(selectedResource) }
        if (selectedResource != null && state.contents?.currentNode?.hasChildren == true) item {
            TextButton(onClick = { onOpenSourceNode(state.contents.currentNode.sourceNodeId) }) {
                Text(stringResource(R.string.work_contents_open_children))
            }
        }
        if (state.presentation == BookDetailPresentation.ResourceDetail && selectedResource == null) {
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
                    bookId = content.book.id,
                    bookTitle = state.content?.book?.title.orEmpty(),
                    bookCoverUrl = content.book.coverUrl,
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
                        repository = repository,
                        context = context,
                        onOpenUnit = { onOpenReadingUnit(resource, it) },
                        onSelectPage = onSelectReadingUnitsPage,
                        onRetry = onRetrySurface,
                    )
                }
            }
        }
    }
}

@Composable
private fun BookReadingProgress(resource: ResourceContent?) {
    val theme = WarmPageThemeValues
    val isAudio = resource?.readerType.equals("audio", ignoreCase = true)
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        if (resource != null && (resource.progressPercent ?: 0) > 0) {
            Text(
                stringResource(if (isAudio) R.string.work_book_listening else R.string.work_book_reading, resource.title),
                style = theme.typography.callout,
                color = theme.colors.textSecondary,
                modifier = Modifier.testTag("work-book-reading-resource"),
            )
            ReadingProgressTrack(
                progressPercent = requireNotNull(resource.progressPercent),
                stateDescription = stringResource(R.string.work_resource_accessibility_progress, resource.progressPercent),
            )
        }
    }
}

@Composable
private fun WorkDetailActionRow(
    managementTarget: ManagementTarget?,
    managementMenuContext: ManagementMenuContext,
    selectedResource: ResourceContent?,
    showBookActions: Boolean,
    selectedDownload: AndroidDownloadRecord?,
    bookDownloads: BookDetailDownloadSummary?,
    onOpenBookDownloads: () -> Unit,
    onOpenShelfPicker: () -> Unit,
    readingStatus: WorkReadingStatus,
    readingStatusBusy: Boolean,
    onToggleReadingStatus: () -> Unit,
    onDownloadResource: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    onRequestRemoveDownload: (AndroidDownloadRecord) -> Unit,
    onOpenSelectedResource: (ResourceContent) -> Unit,
    onOpenDownloadedResource: (AndroidDownloadRecord) -> Unit,
) {
    val theme = WarmPageThemeValues
    val primaryAction = workDetailPrimaryActionPresentation(
        selectedResource = selectedResource,
        download = selectedDownload,
    )
    val primaryLabel = primaryActionLabel(primaryAction.label)
    val downloadAction = bookDownloads?.state?.let { download ->
        when (download) {
            BookDetailDownloadState.NotDownloaded -> WorkDetailDownloadAction.NotDownloaded
            BookDetailDownloadState.Downloading -> WorkDetailDownloadAction.Downloading
            BookDetailDownloadState.Paused -> WorkDetailDownloadAction.Paused
            BookDetailDownloadState.Failed -> WorkDetailDownloadAction.Failed
            BookDetailDownloadState.Downloaded -> WorkDetailDownloadAction.Downloaded
        }
    } ?: workDetailDownloadActionPresentation(selectedDownload)
    var downloadMenuExpanded by remember(selectedResource?.id, selectedDownload?.assetId) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        WarmPagePrimaryAction(
            label = primaryLabel,
            trailingIcon = if (selectedResource?.readerType.equals("audio", true)) Icons.Outlined.Headphones else Icons.Filled.PlayArrow,
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
        Row(Modifier.fillMaxWidth().testTag("work-detail-actions")) {
            Box(Modifier.weight(1f)) {
                WorkDetailQuickAction(
                    icon = when (downloadAction) {
                        WorkDetailDownloadAction.Downloading -> Icons.Outlined.PauseCircle
                        WorkDetailDownloadAction.Downloaded -> Icons.Outlined.CheckCircle
                        WorkDetailDownloadAction.NotDownloaded,
                        WorkDetailDownloadAction.Paused,
                        WorkDetailDownloadAction.Failed,
                        -> Icons.Outlined.Download
                    },
                    label = if (bookDownloads?.state == BookDetailDownloadState.Downloaded) stringResource(R.string.work_book_download_count, bookDownloads.downloadedResources) else stringResource(
                        when (downloadAction) {
                            WorkDetailDownloadAction.NotDownloaded -> R.string.work_quick_download
                            WorkDetailDownloadAction.Downloading -> R.string.work_quick_downloading
                            WorkDetailDownloadAction.Paused -> R.string.work_quick_download_paused
                            WorkDetailDownloadAction.Failed -> R.string.work_quick_download_retry
                            WorkDetailDownloadAction.Downloaded -> R.string.work_quick_downloaded
                        },
                    ),
                    onClick = downloadClick@{
                        if (showBookActions) { onOpenBookDownloads(); return@downloadClick }
                        selectedResource?.let { resource ->
                            when (downloadAction) {
                                WorkDetailDownloadAction.Downloading -> onCancelDownload(resource.id)
                                WorkDetailDownloadAction.NotDownloaded,
                                WorkDetailDownloadAction.Paused,
                                WorkDetailDownloadAction.Failed,
                                -> onDownloadResource(resource.id)
                                WorkDetailDownloadAction.Downloaded -> downloadMenuExpanded = true
                            }
                        }
                    },
                    onLongClick = selectedDownload?.takeIf { it.isReadable && !showBookActions }?.let {
                        { downloadMenuExpanded = true }
                    },
                    longClickLabel = stringResource(R.string.work_quick_manage_download),
                    enabled = showBookActions || (selectedResource != null && (selectedResource.readable || selectedDownload != null)),
                    modifier = Modifier.fillMaxWidth(),
                    testTag = "work-download-action",
                )
                DropdownMenu(
                    expanded = downloadMenuExpanded,
                    onDismissRequest = { downloadMenuExpanded = false },
                ) {
                    selectedDownload?.takeIf(AndroidDownloadRecord::isReadable)?.let { download ->
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.work_download_open_offline)) },
                            onClick = {
                                downloadMenuExpanded = false
                                onOpenDownloadedResource(download)
                            },
                        )
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.downloads_remove_action)) },
                            onClick = {
                                downloadMenuExpanded = false
                                onRequestRemoveDownload(download)
                            },
                        )
                    }
                }
            }
            WorkDetailQuickAction(
                icon = Icons.Outlined.Check,
                label = stringResource(
                    when (readingStatus) {
                        WorkReadingStatus.Finished -> R.string.work_quick_reading_read
                        WorkReadingStatus.Reading -> R.string.work_quick_reading_in_progress
                        WorkReadingStatus.Unread -> R.string.work_quick_reading_unread
                    },
                ),
                onClick = onToggleReadingStatus,
                enabled = (showBookActions || selectedResource != null) && !readingStatusBusy,
                modifier = Modifier.weight(1f),
                testTag = "work-reading-status-action",
            )
            if (showBookActions) WorkDetailQuickAction(
                icon = Icons.Outlined.BookmarkBorder,
                label = stringResource(R.string.work_quick_add),
                onClick = onOpenShelfPicker,
                modifier = Modifier.weight(1f),
                testTag = "work-shelf-action",
            )
            if (managementTarget != null) ManagementAnchor(managementTarget, Modifier.weight(1f), menuContext = managementMenuContext) { open ->
            WorkDetailQuickAction(
                icon = Icons.Outlined.MoreVert,
                label = stringResource(R.string.work_quick_more),
                onClick = open,

                modifier = Modifier.fillMaxWidth(),
                testTag = "work-more-action",
            )
            }
        }
        val captionResource = when {
            selectedResource?.readerType.equals("audio", ignoreCase = true) -> R.string.work_audiobook_player_unavailable
            selectedResource == null || !selectedResource.readable -> R.string.work_no_readable_resources
            !ReaderFormatSupport.canOpenOnline(selectedResource.readerType, selectedResource.format) ->
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
    coverRefreshToken: Int,
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
            cacheRevision = coverRefreshToken,
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
    var expanded by rememberSaveable(content.description) { mutableStateOf(false) }
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

internal enum class WorkContentItemKind { SourceDirectory, ReadableResource }

internal data class WorkContentItemPresentation(
    val entry: BookContentEntry,
    val kind: WorkContentItemKind,
    val resource: ResourceContent?,
    val coverUrl: String,
    val title: String,
    val position: Int,
    val indexLabel: String,
)

internal data class WorkContentBreadcrumbPresentation(
    val title: String,
    val sourceNodeId: String?,
)

internal fun workContentItemPresentations(
    page: BookContentsPage,
    resources: List<ResourceContent>,
    bookCoverUrl: String,
): List<WorkContentItemPresentation> {
    val entries = buildList {
        addAll(page.entries.filter { it.isSourceFolder || it.isDirectResource })
        if (page.currentNode.isDirectResource && none { it.sourceNodeId == page.currentNode.sourceNodeId }) {
            add(0, page.currentNode)
        }
    }
    val resourcesById = resources.associateBy(ResourceContent::id)
    val directories = entries.filter(BookContentEntry::isSourceFolder)
    val directResources = entries.filter(BookContentEntry::isDirectResource)

    return directories.mapIndexed { position, entry ->
        val representative = entry.representativeResourceId?.let(resourcesById::get)
        WorkContentItemPresentation(
            entry = entry,
            kind = WorkContentItemKind.SourceDirectory,
            resource = representative,
            coverUrl = listOfNotNull(entry.coverUrl, representative?.coverUrl, bookCoverUrl)
                .firstOrNull(String::isNotBlank)
                .orEmpty(),
            title = entry.title,
            position = position,
            indexLabel = (position + 1).toString().padStart(2, '0'),
        )
    } + directResources.mapIndexed { position, entry ->
        val resource = entry.resourceId?.let(resourcesById::get)
        WorkContentItemPresentation(
            entry = entry,
            kind = WorkContentItemKind.ReadableResource,
            resource = resource,
            coverUrl = listOfNotNull(resource?.coverUrl, entry.coverUrl)
                .firstOrNull(String::isNotBlank)
                .orEmpty(),
            title = resource?.title ?: entry.title,
            position = position,
            indexLabel = resource?.displayIndex(position) ?: (position + 1).toString().padStart(2, '0'),
        )
    }
}

internal fun workContentBreadcrumbs(
    bookTitle: String,
    page: BookContentsPage,
): List<WorkContentBreadcrumbPresentation> = listOf(
    WorkContentBreadcrumbPresentation(title = bookTitle, sourceNodeId = null),
) + page.breadcrumbs.map { breadcrumb ->
    WorkContentBreadcrumbPresentation(title = breadcrumb.title, sourceNodeId = breadcrumb.sourceNodeId)
}

@Composable
private fun WorkContentBrowser(
    bookId: String,
    page: BookContentsPage?,
    bookTitle: String,
    bookCoverUrl: String,
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
    val items = page?.let { workContentItemPresentations(it, resources, bookCoverUrl) }.orEmpty()
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
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
                workContentBreadcrumbs(bookTitle, contents).forEachIndexed { index, breadcrumb ->
                    if (index > 0) Text("/", color = theme.colors.textSecondary)
                    TextButton(
                        onClick = { onOpenSourceNode(breadcrumb.sourceNodeId) },
                        modifier = Modifier.testTag(
                            if (breadcrumb.sourceNodeId == null) {
                                "work-contents-breadcrumb-root"
                            } else {
                                "work-contents-breadcrumb-${breadcrumb.sourceNodeId}"
                            },
                        ),
                    ) {
                        Text(breadcrumb.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
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
            items.isEmpty() -> WarmPageEmptyState(
                title = stringResource(R.string.work_contents_empty_title),
                message = stringResource(R.string.work_contents_empty_message),
            )
            gridLayout -> BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
                val columns = compactCoverGridColumnCount(
                    compactColumns = theme.components.grid.compactColumns,
                    largeTextColumns = theme.components.grid.largeTextColumns,
                    fontScale = LocalDensity.current.fontScale,
                )
                val horizontalGap = theme.components.grid.horizontalGap
                val itemWidth = compactCoverGridItemWidth(
                    availableWidth = maxWidth,
                    horizontalGap = horizontalGap,
                    columns = columns,
                )
                Column(verticalArrangement = Arrangement.spacedBy(theme.components.grid.verticalGap)) {
                    items.chunked(columns).forEach { rowItems ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(horizontalGap),
                        ) {
                            rowItems.forEach { item ->
                                WorkContentEntryCard(
                    bookId = bookId,
                                    item = item,
                                    repository = repository,
                                    context = context,
                                    grid = true,
                                    onBrowseChildren = { onOpenSourceNode(item.entry.sourceNodeId) },
                                    onOpen = {
                                        if (item.kind == WorkContentItemKind.SourceDirectory) {
                                            onOpenSourceNode(item.entry.sourceNodeId)
                                        } else {
                                            (item.resource?.id ?: item.entry.resourceId)?.let(onSelectResource)
                                        }
                                    },
                                    modifier = Modifier.width(itemWidth),
                                )
                            }
                            repeat(columns - rowItems.size) {
                                Spacer(Modifier.width(itemWidth))
                            }
                        }
                    }
                }
            }
            else -> items.forEach { item ->
                WorkContentEntryCard(
                    bookId = bookId,
                    item = item,
                    repository = repository,
                    context = context,
                    grid = false,
                    onBrowseChildren = { onOpenSourceNode(item.entry.sourceNodeId) },
                    onOpen = {
                        if (item.kind == WorkContentItemKind.SourceDirectory) {
                            onOpenSourceNode(item.entry.sourceNodeId)
                        } else {
                            (item.resource?.id ?: item.entry.resourceId)?.let(onSelectResource)
                        }
                    },
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
    bookId: String,
    item: WorkContentItemPresentation,
    repository: ContentRepository,
    context: ContentRequestContext,
    grid: Boolean,
    onBrowseChildren: () -> Unit,
    onOpen: () -> Unit,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    val target = ManagementTarget(if (item.kind == WorkContentItemKind.SourceDirectory) ManagementObject.Directory else ManagementObject.Resource,
        bookId, if (item.kind == WorkContentItemKind.SourceDirectory) item.entry.sourceNodeId else requireNotNull(item.resource?.id ?: item.entry.resourceId), item.title)
    ManagementAnchor(target, modifier, menuContext = ManagementMenuContext(
        kindleSendAvailable = item.resource?.kindleSendAvailable == true,
        hasRepresentativeResource = item.entry.representativeResourceId != null)) {
    Surface(
        onClick = onOpen,
        modifier = Modifier
            .heightIn(min = theme.components.controls.minimumTouchTarget)
            .testTag(
                if (item.kind == WorkContentItemKind.SourceDirectory) {
                    "work-contents-folder-${item.entry.sourceNodeId}"
                } else {
                    "work-resource-${item.resource?.id ?: item.entry.resourceId ?: item.entry.sourceNodeId}"
                },
            ),
        shape = RoundedCornerShape(theme.radii.task),
        color = Color.Transparent,
    ) {
        if (grid) {
            Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
                Box {
                    ContentCover(
                        contentId = if (item.kind == WorkContentItemKind.SourceDirectory) {
                            item.entry.sourceNodeId
                        } else {
                            item.resource?.id ?: item.entry.sourceNodeId
                        },
                        title = item.title,
                        coverUrl = item.coverUrl,
                        repository = repository,
                        context = context,
                        role = CoverRole.Compact,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (item.kind == WorkContentItemKind.ReadableResource) {
                        item.resource?.progressPercent?.takeIf { it > 0 }?.let { progress ->
                            CoverProgress(
                                progressPercent = progress,
                                modifier = Modifier.align(Alignment.BottomCenter),
                            )
                        }
                    }
                    Box(
                        modifier = Modifier
                            .align(Alignment.TopStart)
                            .padding(theme.spacing.one)
                            .size(theme.spacing.four)
                            .background(theme.colors.textPrimary.copy(alpha = 0.62f), CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = item.indexLabel,
                            color = theme.colors.canvas,
                            style = theme.typography.caption,
                            textAlign = TextAlign.Center,
                        )
                    }
                }
                Row(verticalAlignment = Alignment.Top) {
                    Text(
                        item.title,
                        modifier = Modifier.weight(1f),
                        style = theme.typography.body,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (item.kind == WorkContentItemKind.SourceDirectory) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowForward,
                            contentDescription = null,
                            tint = theme.colors.textSecondary,
                            modifier = Modifier.size(theme.spacing.two),
                        )
                    }
                }
                if (item.kind == WorkContentItemKind.ReadableResource && item.entry.hasChildren) {
                    TextButton(onClick = onBrowseChildren) { Text(stringResource(R.string.work_contents_open_children)) }
                }
                if (item.kind == WorkContentItemKind.ReadableResource) {
                    Text(
                        item.resource?.format?.uppercase(Locale.ROOT)
                            ?: stringResource(R.string.work_contents_file),
                        style = theme.typography.caption,
                        color = theme.colors.textSecondary,
                    )
                }
            }
        } else {
            Row(
                Modifier.padding(horizontal = theme.spacing.oneAndHalf, vertical = theme.spacing.one),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
            ) {
                ContentCover(
                    contentId = if (item.kind == WorkContentItemKind.SourceDirectory) {
                        item.entry.sourceNodeId
                    } else {
                        item.resource?.id ?: item.entry.sourceNodeId
                    },
                    title = item.title,
                    coverUrl = item.coverUrl,
                    repository = repository,
                    context = context,
                    role = CoverRole.Compact,
                    modifier = Modifier.width(theme.spacing.five),
                )
                Column(Modifier.weight(1f)) {
                    Text(item.title, style = theme.typography.body, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(
                        if (item.kind == WorkContentItemKind.SourceDirectory) {
                            stringResource(R.string.work_contents_source_directory, item.position + 1)
                        } else {
                            item.resource?.format?.uppercase(Locale.ROOT)
                                ?: stringResource(R.string.work_contents_file)
                        },
                        style = theme.typography.caption,
                        color = theme.colors.textSecondary,
                    )
                }
                if (item.kind == WorkContentItemKind.ReadableResource) {
                    item.resource?.progressPercent?.takeIf { it > 0 }?.let {
                        Text("$it%", style = theme.typography.caption, color = theme.colors.textSecondary)
                    }
                }
                if (item.kind == WorkContentItemKind.ReadableResource && item.entry.hasChildren) {
                    TextButton(onClick = onBrowseChildren) { Text(stringResource(R.string.work_contents_open_children)) }
                }
                item.entry.sizeBytes?.let {
                    Text(formatWorkContentSize(it), style = theme.typography.caption, color = theme.colors.textSecondary)
                }
                if (item.kind == WorkContentItemKind.SourceDirectory) {
                    Icon(
                        Icons.AutoMirrored.Filled.ArrowForward,
                        contentDescription = null,
                        tint = theme.colors.textSecondary,
                    )
                }
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
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenUnit: (com.ermao.library.shared.modules.library.domain.ReadingUnit) -> Unit,
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
                BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
                    val columns = compactCoverGridColumnCount(
                        compactColumns = theme.components.grid.compactColumns,
                        largeTextColumns = theme.components.grid.largeTextColumns,
                        fontScale = LocalDensity.current.fontScale,
                    )
                    val horizontalGap = theme.components.grid.horizontalGap
                    val itemWidth = compactCoverGridItemWidth(
                        availableWidth = maxWidth,
                        horizontalGap = horizontalGap,
                        columns = columns,
                    )
                    Column(verticalArrangement = Arrangement.spacedBy(theme.components.grid.verticalGap)) {
                        page.units.chunked(columns).forEach { rowUnits ->
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(horizontalGap),
                            ) {
                                rowUnits.forEach { unit ->
                                    WorkPagePreview(
                                        unit,
                                        repository,
                                        context,
                                        Modifier.width(itemWidth),
                                        { onOpenUnit(unit) },
                                    )
                                }
                                repeat(columns - rowUnits.size) {
                                    Spacer(Modifier.width(itemWidth))
                                }
                            }
                        }
                    }
                }
            }
            else -> page.units.forEachIndexed { index, unit ->
                WorkReadingUnitRow(
                    unit = unit,
                    displayIndex = (page.page - 1) * page.pageSize + index + 1,
                    currentSortOrder = page.currentChapterSortOrder,
                    progress = page.progress,
                    onOpen = { onOpenUnit(unit) },
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
        !ReaderFormatSupport.canOpenOnline(selectedResource.readerType, selectedResource.format)
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





@Composable
internal fun DirectoryControlMenu(
    onDownload: () -> Unit,
    target: ManagementTarget? = null,
    menuContext: ManagementMenuContext = ManagementMenuContext(),
) {
    if (target != null) {
        ManagementAnchor(target, menuContext = menuContext, menuExtras = { close ->
            DropdownMenuItem(text = { Text(stringResource(R.string.work_quick_download)) },
                onClick = { close(); onDownload() }, modifier = Modifier.testTag("work-directory-download"))
        }) { open ->
            WarmPageIconAction(icon = Icons.Outlined.MoreVert, label = stringResource(R.string.work_quick_more),
                onClick = open, modifier = Modifier.testTag("work-directory-more"))
        }
        return
    }
    var expanded by remember { mutableStateOf(false) }
    Box {
        WarmPageIconAction(
            icon = Icons.Outlined.MoreVert,
            label = stringResource(R.string.work_quick_more),
            onClick = { expanded = true },
            modifier = Modifier.testTag("work-directory-more"),
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.work_quick_download)) },
                leadingIcon = { Icon(Icons.Outlined.Download, contentDescription = null) },
                onClick = { expanded = false; onDownload() },
                modifier = Modifier.testTag("work-directory-download"),
            )
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
}

internal fun WorkDetailUiState.detailActionScope(): BookDetailActionScope? = content?.let {
    resolveBookDetailActionScope(isBookRoot, it.book.id, selectedResourceId, it.continueResourceId)
}

internal fun WorkDetailUiState.resolveReadingResource(): ResourceContent? {
    val scope = detailActionScope()
    return content?.resources?.firstOrNull { it.id == scope?.readingResourceId }
}

internal fun workBookDownloadSummary(bookId: String, records: Collection<AndroidDownloadRecord>): BookDetailDownloadSummary =
    summarizeBookDetailDownloads(records.filter { it.bookId == bookId }.distinctBy { it.resourceId }.map {
        when (workDetailDownloadActionPresentation(it)) {
            WorkDetailDownloadAction.Downloading -> BookDetailDownloadState.Downloading
            WorkDetailDownloadAction.Downloaded -> BookDetailDownloadState.Downloaded
            WorkDetailDownloadAction.Paused -> BookDetailDownloadState.Paused
            WorkDetailDownloadAction.Failed -> BookDetailDownloadState.Failed
            WorkDetailDownloadAction.NotDownloaded -> BookDetailDownloadState.NotDownloaded
        }
    })

internal fun workDetailPageContent(state: WorkDetailUiState): BookDetailContent? {
    val content = state.content ?: return null
    if (state.isBookRoot && state.presentation == BookDetailPresentation.ContentBrowser) {
        return content.copy(book = content.book.copy(progressPercent = null), completed = false)
    }
    val resource = state.resolveSelectedResource()
    val node = state.contents?.currentNode
    val representative = node?.representativeResourceId?.let { id -> content.resources.firstOrNull { it.id == id } }
    return content.copy(
        book = content.book.copy(
            title = resource?.title ?: node?.title ?: content.book.title,
            coverUrl = resource?.coverUrl ?: node?.coverUrl ?: representative?.coverUrl ?: content.book.coverUrl,
            progressPercent = resource?.progressPercent,
        ),
        description = if (resource != null) resource.description else node?.description ?: content.description.takeIf { state.isBookRoot },
        completed = (resource?.progressPercent ?: 0) >= 100,
        tags = content.tags.takeIf { state.isBookRoot }.orEmpty(),
    )
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
