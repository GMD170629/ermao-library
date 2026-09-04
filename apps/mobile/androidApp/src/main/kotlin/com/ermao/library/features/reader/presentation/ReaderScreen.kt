package com.ermao.library.features.reader.presentation

import android.os.Build
import android.view.ViewGroup
import android.view.WindowManager
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.drag
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.windowInsetsBottomHeight
import androidx.compose.foundation.layout.windowInsetsTopHeight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.automirrored.filled.Notes
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.fragment.app.FragmentContainerView
import androidx.core.view.WindowCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ermao.library.R
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.application.ReaderAdjacentChapters
import com.ermao.library.features.reader.application.ReaderTocNode
import com.ermao.library.features.reader.application.flattenTableOfContents
import com.ermao.library.features.reader.application.resolveAdjacentChapters
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderPanel
import com.ermao.library.shared.modules.reader.ReaderControl
import com.ermao.library.shared.modules.reader.ReaderControlAvailability
import com.ermao.library.shared.modules.reader.ReaderSettingDefinition
import com.ermao.library.shared.modules.reader.ReaderSettingState
import com.ermao.library.shared.modules.reader.ReaderSettingsCatalog
import com.ermao.library.shared.modules.reader.resetReaderPreferences
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderCommandRejected
import com.ermao.library.shared.modules.reader.ReaderNavigationCompleted
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderReadingProgression
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReaderProgressStyle
import com.ermao.library.shared.modules.reader.ReaderThemeMode
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.ui.theme.ReaderWarmPageTheme
import com.ermao.library.ui.theme.WarmPageThemeValues
import com.ermao.library.ui.components.WarmPageChoice
import com.ermao.library.ui.components.WarmPageModalBottomSheet
import com.ermao.library.ui.components.WarmPageSegmentedControl
import com.ermao.library.ui.components.WarmPageSnackbarHost
import com.ermao.library.ui.components.WarmSettingsInlineMessage
import com.ermao.library.ui.components.WarmSettingsChoice
import com.ermao.library.ui.components.WarmSettingsChoiceSheet
import com.ermao.library.ui.components.WarmSettingsDivider
import com.ermao.library.ui.components.WarmSettingsSection
import com.ermao.library.ui.components.WarmSettingsSwitchRow
import com.ermao.library.ui.components.WarmSettingsValueRow
import java.text.DateFormat
import java.util.Date
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ReaderScreen(
    title: String,
    controller: ReaderScreenController?,
    opening: Boolean,
    openError: ReaderError?,
    controlsVisible: Boolean,
    onControlsVisibleChange: (Boolean) -> Unit,
    onClose: () -> Unit,
    onRetryOpen: (() -> Unit)? = null,
    onNavigatorContainerReady: () -> Unit,
    onPanelVisibilityChange: (Boolean) -> Unit = {},
) {
    val coroutineScope = rememberCoroutineScope()
    val navigationMutex = remember(controller) { Mutex() }
    val preferences by controller?.preferences?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf(ReaderPreferences()) }
    val currentLocation by controller?.currentLocation?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<ReaderLocation?>(null) }
    val presentationProgress by controller?.presentationProgress?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<Double?>(null) }
    val contentError by controller?.contentError?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<ReaderError?>(null) }
    val displayedError = openError ?: contentError
    val resumeNotice by controller?.resumeNotice?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<com.ermao.library.features.reader.application.ReaderResumeNotice?>(null) }
    val resumeActionFailed by controller?.resumeActionFailed?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf(false) }
    val bookmarks by controller?.bookmarks?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf(emptyList()) }
    val bookmarkSyncPending by controller?.bookmarkSyncPending?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf(false) }

    val capabilities = controller?.capabilities ?: ReaderCapabilities.epub(
        supportsVolumeKeys = true,
        supportsCustomFonts = false,
    )
    var panel by remember { mutableStateOf<ReaderPanel?>(null) }
    var panelTrigger by remember { mutableStateOf<ReaderPanel?>(null) }
    val panelFocus = remember { ReaderPanel.entries.associateWith { FocusRequester() } }
    val morphology = controller?.morphology ?: ReaderMorphology.Reflowable
    var adjacentChapters by remember(controller) { mutableStateOf(ReaderAdjacentChapters()) }
    LaunchedEffect(controller, currentLocation, controlsVisible) {
        val activeController = controller
        adjacentChapters = if (controlsVisible && activeController?.morphology == ReaderMorphology.Reflowable) {
            try {
                resolveAdjacentChapters(activeController.loadTableOfContents(), currentLocation)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                ReaderAdjacentChapters()
            }
        } else {
            ReaderAdjacentChapters()
        }
    }
    val nativeUnavailable = controller?.unavailableControls(preferences).orEmpty()
    val wideViewport = readerViewportIsWide()
    var preferencesFailure by remember(controller) { mutableStateOf<ReaderCommandRejected?>(null) }
    val updatePreferences: (ReaderPreferences) -> Unit = { updated ->
        controller?.let { activeController ->
            coroutineScope.launch {
                preferencesFailure = activeController.applyPreferences(
                    if (updated == ReaderPreferences()) updated else com.ermao.library.shared.modules.reader.mergeReaderPreferenceChanges(preferences, updated, activeController.preferences.value),
                ) as? ReaderCommandRejected
            }
        }
    }
    val settingState: (ReaderSettingDefinition) -> ReaderSettingState = { setting ->
        ReaderSettingsCatalog.resolveReaderSetting(
            setting,
            morphology,
            capabilities,
            preferences,
            controller != null,
            nativeUnavailable,
            wideViewport,
        )
    }
    val negativeLetterSpacingEnabled = ReaderSettingsCatalog.resolveReaderControl(
        ReaderControl.NegativeLetterSpacing,
        morphology,
        capabilities,
        preferences,
        controller != null,
        nativeUnavailable,
    ) == ReaderControlAvailability.Available
    LaunchedEffect(panel) {
        onPanelVisibilityChange(panel != null)
        if (panel == null) panelTrigger?.let { panelFocus[it]?.requestFocus() }
    }
    BackHandler(panel != null) { panel = null }
    var pendingNavigationId by remember(controller) { mutableStateOf<String?>(null) }
    var navigationFailed by remember(controller) { mutableStateOf(false) }
    var contentsState by remember(controller) {
        val initialEntries = controller?.tableOfContents.orEmpty()
        mutableStateOf<ReaderContentsLoadState>(
            if (controller?.morphology == ReaderMorphology.Reflowable) {
                ReaderContentsLoadState.NotRequested
            } else {
                ReaderContentsLoadState.Ready(flattenTableOfContents(initialEntries))
            },
        )
    }
    val snackbarHostState = remember { SnackbarHostState() }
    val bookmarkAddedMessage = stringResource(R.string.reader_bookmark_added)
    val bookmarkRemovedMessage = stringResource(R.string.reader_bookmark_removed)
    val undoLabel = stringResource(R.string.undo_action)
    val seekFailedMessage = stringResource(R.string.reader_progress_seek_failed)
    val navigationFailedMessage = stringResource(R.string.reader_navigation_failed)
    val requestContents: () -> Unit = {
        val activeController = controller
        if (
            activeController != null &&
            contentsState !is ReaderContentsLoadState.Loading &&
            contentsState !is ReaderContentsLoadState.Ready
        ) {
            contentsState = ReaderContentsLoadState.Loading
            coroutineScope.launch {
                try {
                    val entries = activeController.loadTableOfContents()
                    val flattened = withContext(Dispatchers.Default) { flattenTableOfContents(entries) }
                    contentsState = ReaderContentsLoadState.Ready(flattened)
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {
                    contentsState = ReaderContentsLoadState.Failed
                }
            }
        }
    }

    KeepScreenAwake(preferences.interaction.keepScreenAwake)
    ReaderWarmPageTheme(preferences.appearance.theme, preferences.appearance.themeMode) {
        val colors = WarmPageThemeValues.colors
        ReaderSystemBarAppearance(colors.canvas)
        BoxWithConstraints(Modifier.fillMaxSize().background(colors.canvas)) {
            val requestedPageWidth = when (morphology) {
                ReaderMorphology.Reflowable -> preferences.epub.pageWidth
                ReaderMorphology.Comic -> preferences.comic.pageWidth
                ReaderMorphology.Pdf -> preferences.pdf.pageWidth
            }.dp
            val navigatorWidth = if (maxWidth > 640.dp) minOf(maxWidth, requestedPageWidth) else maxWidth
            AndroidView(
                modifier = Modifier
                    .align(Alignment.Center)
                    .fillMaxHeight()
                    .width(navigatorWidth)
                    .testTag(READER_NAVIGATOR_TEST_TAG),
                factory = { context ->
                    FragmentContainerView(context).apply {
                        id = READER_NAVIGATOR_CONTAINER_ID
                        layoutParams = ViewGroup.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.MATCH_PARENT,
                        )
                        // FragmentManager can only attach after AndroidView has inserted this
                        // container into the Activity hierarchy. The factory callback runs too
                        // early and races fast local MOBI opens.
                        post(onNavigatorContainerReady)
                    }
                },
            )

            Box(
                Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .windowInsetsTopHeight(WindowInsets.statusBars)
                    .background(colors.canvas),
            )
            Box(
                Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .windowInsetsBottomHeight(WindowInsets.navigationBars)
                    .background(colors.canvas),
            )

            if (controller != null) {
                Box(Modifier.size(1.dp).alpha(0f).testTag(READER_READY_TEST_TAG))
            }

            if (!controlsVisible && controller != null) {
                ReaderPassiveStatus(
                    currentLocation = currentLocation,
                    presentationProgress = presentationProgress,
                    preferences = preferences,
                    lastPageIndex = controller.tableOfContents.lastIndex,
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            }

            ReaderControlsVisibility(controlsVisible) {
                ReaderControlOverlay(
                    title = title,
                    controller = controller,
                    location = currentLocation,
                    presentationProgress = presentationProgress,
                    preferences = preferences,
                    adjacentChapters = adjacentChapters,
                    bookmarks = bookmarks,
                    onToggleBookmark = {
                        controller?.let { activeController ->
                            val change = activeController.toggleCurrentBookmark() ?: return@let
                            snackbarHostState.currentSnackbarData?.dismiss()
                            coroutineScope.launch {
                                val result = snackbarHostState.showSnackbar(
                                    message = if (change.added) bookmarkAddedMessage else bookmarkRemovedMessage,
                                    actionLabel = undoLabel,
                                    withDismissAction = true,
                                    duration = SnackbarDuration.Short,
                                )
                                if (result == SnackbarResult.ActionPerformed) {
                                    activeController.undoBookmarkChange(change)
                                }
                            }
                        }
                    },
                    onClose = { coroutineScope.launch { navigationMutex.withLock { onClose() } } },
                    panelFocus = panelFocus,
                    onPanel = {
                        panelTrigger = it
                        if (it == ReaderPanel.Contents) {
                            navigationFailed = false
                            requestContents()
                        }
                        panel = it
                    },
                    onSeek = { target ->
                        val moved = controller?.goToTotalProgression(target) == true
                        if (!moved) {
                            snackbarHostState.currentSnackbarData?.dismiss()
                            coroutineScope.launch {
                                snackbarHostState.showSnackbar(seekFailedMessage, duration = SnackbarDuration.Short)
                            }
                        }
                        moved
                    },
                    onNavigateChapter = { entry ->
                        controller?.let { activeController ->
                            coroutineScope.launch {
                                navigationMutex.withLock {
                                    if (activeController.navigateTo(entry) !is ReaderNavigationCompleted) {
                                        snackbarHostState.currentSnackbarData?.dismiss()
                                        snackbarHostState.showSnackbar(
                                            navigationFailedMessage,
                                            duration = SnackbarDuration.Short,
                                        )
                                    }
                                }
                            }
                        }
                    },
                    onHide = { onControlsVisibleChange(false) },
                )
            }

            resumeNotice?.let { notice ->
                ReaderResumeNoticeCard(
                    notice = notice,
                    actionFailed = resumeActionFailed,
                    onReturn = { controller?.returnToResumeNotice() },
                    onDismiss = { controller?.dismissResumeNotice() },
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            }

            when {
                displayedError != null -> ReaderOpenError(
                    displayedError,
                    onClose,
                    onRetryOpen,
                )
                opening -> ReaderOpeningIndicator()
            }

            if (panel == null) {
                WarmPageSnackbarHost(
                    hostState = snackbarHostState,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .navigationBarsPadding()
                        .padding(
                            start = 16.dp,
                            end = 16.dp,
                            bottom = if (controlsVisible) 112.dp else 16.dp,
                        ),
                )
            }
        }

        when (panel) {
            ReaderPanel.Contents -> ReaderContentsSheet(
                state = contentsState,
                currentLocation = currentLocation,
                pendingEntryId = pendingNavigationId,
                navigationFailed = navigationFailed,
                onDismiss = { panel = null },
                onRetry = requestContents,
                onSelect = { entry ->
                    controller?.let { activeController ->
                        coroutineScope.launch {
                            navigationMutex.withLock {
                                pendingNavigationId = entry.id
                                navigationFailed = false
                                if (activeController.navigateTo(entry) is ReaderNavigationCompleted) {
                                    panel = null
                                } else {
                                    navigationFailed = true
                                }
                                pendingNavigationId = null
                            }
                        }
                    }
                },
            )
            ReaderPanel.Bookmarks -> ReaderNotesSheet(
                capabilities = capabilities,
                bookmarks = bookmarks,
                syncPending = bookmarkSyncPending,
                navigationFailed = navigationFailed,
                onJump = { bookmarkId ->
                    navigationFailed = controller?.goToBookmark(bookmarkId) != true
                    if (!navigationFailed) panel = null
                },
                onRemove = { bookmarkId ->
                    controller?.let { activeController ->
                        activeController.removeBookmark(bookmarkId)
                        snackbarHostState.currentSnackbarData?.dismiss()
                        coroutineScope.launch {
                            val result = snackbarHostState.showSnackbar(
                                message = bookmarkRemovedMessage,
                                actionLabel = undoLabel,
                                withDismissAction = true,
                                duration = SnackbarDuration.Short,
                            )
                            if (result == SnackbarResult.ActionPerformed) {
                                activeController.undoBookmarkRemoval(bookmarkId)
                            }
                        }
                    }
                },
                snackbarHostState = snackbarHostState,
                onDismiss = { panel = null },
            )
            ReaderPanel.Appearance -> ReaderPreferenceSheet(
                ReaderPanel.Appearance,
                preferences,
                controller?.morphology ?: ReaderMorphology.Reflowable,
                settingState = settingState,
                negativeLetterSpacingEnabled = negativeLetterSpacingEnabled,
                failure = preferencesFailure,
                onUpdate = updatePreferences,
                onDismiss = { panel = null },
            )
            ReaderPanel.Settings -> ReaderPreferenceSheet(
                ReaderPanel.Settings,
                preferences,
                controller?.morphology ?: ReaderMorphology.Reflowable,
                settingState = settingState,
                negativeLetterSpacingEnabled = negativeLetterSpacingEnabled,
                failure = preferencesFailure,
                onUpdate = updatePreferences,
                onDismiss = { panel = null },
            )
            null -> Unit
        }
        if (preferencesFailure != null) {
            Surface(color = MaterialTheme.colorScheme.errorContainer) {
                Text(
                    readerPreferenceFailureMessage(preferencesFailure),
                    Modifier.fillMaxWidth().padding(12.dp),
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
        }
    }
}

@Composable
private fun ReaderResumeNoticeCard(
    notice: com.ermao.library.features.reader.application.ReaderResumeNotice,
    actionFailed: Boolean,
    onReturn: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = WarmPageThemeValues.colors
    val readAt = remember(notice.capturedAtEpochMillis) {
        DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
            .format(Date(notice.capturedAtEpochMillis))
    }
    val position = notice.pageNumber?.let { stringResource(R.string.reader_page_number, it) }
        ?: notice.chapterLabel?.takeIf(String::isNotBlank)
        ?: stringResource(R.string.reader_progress_percent, notice.percent.roundToInt())
    Surface(
        modifier = modifier
            .navigationBarsPadding()
            .padding(16.dp)
            .fillMaxWidth()
            .semantics { liveRegion = LiveRegionMode.Polite },
        color = colors.surface,
        shape = MaterialTheme.shapes.medium,
        tonalElevation = 4.dp,
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Text(
                    stringResource(R.string.reader_resume_prompt, readAt, position),
                    modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.bodyMedium,
                    color = colors.textPrimary,
                )
                IconButton(onClick = onDismiss, modifier = Modifier.size(32.dp)) {
                    Icon(Icons.Default.Close, stringResource(R.string.reader_resume_dismiss))
                }
            }
            if (actionFailed) {
                Text(
                    stringResource(R.string.reader_resume_return_failed),
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            TextButton(onClick = onReturn) {
                Text(stringResource(R.string.reader_resume_return))
            }
        }
    }
}

@Composable
private fun ReaderControlOverlay(
    title: String,
    controller: ReaderScreenController?,
    location: ReaderLocation?,
    presentationProgress: Double?,
    preferences: ReaderPreferences,
    adjacentChapters: ReaderAdjacentChapters,
    bookmarks: List<ReaderBookmark>,
    onToggleBookmark: () -> Unit,
    panelFocus: Map<ReaderPanel, FocusRequester>,
    onClose: () -> Unit,
    onPanel: (ReaderPanel) -> Unit,
    onSeek: (Double) -> Boolean,
    onNavigateChapter: (ReaderTocEntry) -> Unit,
    onHide: () -> Unit,
) {
    val colors = WarmPageThemeValues.colors
    val centerTapInteraction = remember { MutableInteractionSource() }
    Box(Modifier.fillMaxSize()) {
        Surface(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .statusBarsPadding()
                .padding(horizontal = 12.dp, vertical = 8.dp)
                .fillMaxWidth(),
            color = colors.surface.copy(alpha = 0.96f),
            contentColor = colors.textPrimary,
            shape = RoundedCornerShape(WarmPageThemeValues.radii.task),
            border = BorderStroke(1.dp, colors.divider),
            shadowElevation = 4.dp,
        ) {
            Row(
                Modifier.height(52.dp).padding(horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onClose) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.reader_close))
                }
                Text(
                    title,
                    Modifier.weight(1f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.titleSmall,
                    color = colors.textPrimary,
                )
                run {
                    val activeBookmark = currentBookmark(bookmarks, location)
                    IconButton(onClick = onToggleBookmark, enabled = location != null && controller?.capabilities?.supportsBookmarks == true) {
                        Icon(
                            if (activeBookmark) Icons.Default.Bookmark else Icons.Default.BookmarkBorder,
                            stringResource(R.string.reader_bookmark),
                        )
                    }
                }
            }
        }

        Box(
            Modifier
                .align(Alignment.Center)
                .fillMaxWidth(0.34f)
                .fillMaxHeight()
                .clickable(
                    interactionSource = centerTapInteraction,
                    indication = null,
                    onClick = onHide,
                ),
        )

        ReaderBottomConsole(
            controller,
            location,
            presentationProgress,
            preferences,
            adjacentChapters,
            onPanel,
            onSeek,
            onNavigateChapter,
            panelFocus,
            Modifier.align(Alignment.BottomCenter),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderBottomConsole(
    controller: ReaderScreenController?,
    currentLocation: ReaderLocation?,
    presentationProgress: Double?,
    preferences: ReaderPreferences,
    adjacentChapters: ReaderAdjacentChapters,
    onPanel: (ReaderPanel) -> Unit,
    onSeek: (Double) -> Boolean,
    onNavigateChapter: (ReaderTocEntry) -> Unit,
    panelFocus: Map<ReaderPanel, FocusRequester>,
    modifier: Modifier = Modifier,
) {
    val colors = WarmPageThemeValues.colors
    val totalProgression = readerTotalProgression(
        currentLocation,
        controller?.tableOfContents.orEmpty().lastIndex,
        presentationProgress,
    )
    var sliderProgress by remember { mutableFloatStateOf(totalProgression?.toFloat() ?: 0f) }
    var dragging by remember { mutableStateOf(false) }
    var pendingSeekOrigin by remember { mutableStateOf<Double?>(null) }
    LaunchedEffect(totalProgression, dragging, pendingSeekOrigin) {
        if (dragging) return@LaunchedEffect
        val origin = pendingSeekOrigin
        if (origin == null || totalProgression == null || abs(totalProgression - origin) > 0.0001) {
            sliderProgress = totalProgression?.toFloat() ?: 0f
            pendingSeekOrigin = null
        }
    }
    LaunchedEffect(pendingSeekOrigin) {
        if (pendingSeekOrigin == null) return@LaunchedEffect
        delay(PROGRESS_SEEK_FEEDBACK_TIMEOUT_MILLIS)
        sliderProgress = totalProgression?.toFloat() ?: 0f
        pendingSeekOrigin = null
    }
    val progressDescription = stringResource(R.string.reader_progress_slider)
    val seekEnabled = controller != null && currentLocation != null && totalProgression != null
    val reflowableRtl = controller?.morphology == ReaderMorphology.Reflowable &&
        controller.capabilities.supportsReadingProgression &&
        preferences.epub.readingProgression == ReaderReadingProgression.RightToLeft
    val reflowable = controller?.morphology == ReaderMorphology.Reflowable
    val leftChapter = if (reflowableRtl) adjacentChapters.next else adjacentChapters.previous
    val rightChapter = if (reflowableRtl) adjacentChapters.previous else adjacentChapters.next
    val goLeft: () -> Unit = {
        if (reflowable) leftChapter?.let(onNavigateChapter) else controller?.goPrevious()
    }
    val goRight: () -> Unit = {
        if (reflowable) rightChapter?.let(onNavigateChapter) else controller?.goNext()
    }
    val leftDescription = when {
        !reflowable -> R.string.reader_previous
        reflowableRtl -> R.string.reader_next_chapter
        else -> R.string.reader_previous_chapter
    }
    val rightDescription = when {
        !reflowable -> R.string.reader_next
        reflowableRtl -> R.string.reader_previous_chapter
        else -> R.string.reader_next_chapter
    }
    val leftEnabled = controller != null && (!reflowable || leftChapter != null)
    val rightEnabled = controller != null && (!reflowable || rightChapter != null)

    Box(
        modifier
            .navigationBarsPadding()
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Surface(
            Modifier.fillMaxWidth(),
            color = colors.surface.copy(alpha = 0.96f),
            contentColor = colors.textPrimary,
            shape = RoundedCornerShape(WarmPageThemeValues.radii.task),
            border = BorderStroke(1.dp, colors.divider),
            shadowElevation = 6.dp,
        ) {
            Column {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = goLeft, enabled = leftEnabled) {
                    Icon(Icons.Default.ChevronLeft, stringResource(leftDescription))
                }
                ReaderSlider(
                    value = sliderProgress,
                    onValueChange = { dragging = true; sliderProgress = it },
                    onValueChangeFinished = {
                        dragging = false
                        val origin = totalProgression
                        if (origin != null && onSeek(sliderProgress.toDouble())) {
                            pendingSeekOrigin = origin
                        } else {
                            sliderProgress = origin?.toFloat() ?: 0f
                            pendingSeekOrigin = null
                        }
                    },
                    enabled = seekEnabled,
                    modifier = Modifier
                        .weight(1f)
                        .semantics { contentDescription = progressDescription }
                        .testTag(READER_PROGRESS_TEST_TAG),
                )
                IconButton(onClick = goRight, enabled = rightEnabled) {
                    Icon(Icons.Default.ChevronRight, stringResource(rightDescription))
                }
            }
            HorizontalDivider(color = colors.divider)
            Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 2.dp)) {
                ReaderNavAction(Icons.AutoMirrored.Filled.MenuBook, R.string.reader_table_of_contents, READER_CONTENTS_TEST_TAG, focusRequester = panelFocus.getValue(ReaderPanel.Contents)) { onPanel(ReaderPanel.Contents) }
                ReaderNavAction(
                    Icons.AutoMirrored.Filled.Notes, R.string.reader_notes, "reader-notes",
                    focusRequester = panelFocus.getValue(ReaderPanel.Bookmarks),
                    enabled = controller?.capabilities?.supportsBookmarks == true,
                ) { onPanel(ReaderPanel.Bookmarks) }
                if (controller?.capabilities?.supportsTheme == true) {
                    ReaderNavAction(Icons.Default.Palette, R.string.reader_appearance, "reader-appearance", focusRequester = panelFocus.getValue(ReaderPanel.Appearance)) { onPanel(ReaderPanel.Appearance) }
                }
                ReaderNavAction(Icons.Default.Settings, R.string.reader_settings, READER_SETTINGS_TEST_TAG, focusRequester = panelFocus.getValue(ReaderPanel.Settings)) { onPanel(ReaderPanel.Settings) }
            }
        }
        }
    }
}

@Composable
private fun ReaderPassiveStatus(
    currentLocation: ReaderLocation?,
    presentationProgress: Double?,
    preferences: ReaderPreferences,
    lastPageIndex: Int,
    modifier: Modifier = Modifier,
) {
    val totalProgression = readerTotalProgression(currentLocation, lastPageIndex, presentationProgress)?.toFloat()
    val progress = progressLabel(preferences, currentLocation, totalProgression)
    val clock = rememberClock(preferences.display.showClock)
    if (progress.isEmpty() && clock == null) return
    Row(
        modifier
            .navigationBarsPadding()
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 10.dp)
            .testTag(READER_PASSIVE_STATUS_TEST_TAG),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            progress,
            modifier = Modifier.weight(1f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.labelSmall,
            color = WarmPageThemeValues.colors.textSecondary,
        )
        if (clock != null) {
            Text(
                clock,
                style = MaterialTheme.typography.labelSmall,
                color = WarmPageThemeValues.colors.textSecondary,
            )
        }
    }
}

@Composable
private fun ReaderSlider(
    value: Float,
    onValueChange: (Float) -> Unit,
    onValueChangeFinished: (() -> Unit)?,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    valueRange: ClosedFloatingPointRange<Float> = 0f..1f,
    steps: Int = 0,
) {
    val colors = WarmPageThemeValues.colors
    val layoutDirection = LocalLayoutDirection.current
    val currentOnValueChange by rememberUpdatedState(onValueChange)
    val currentOnValueChangeFinished by rememberUpdatedState(onValueChangeFinished)
    val rangeLength = valueRange.endInclusive - valueRange.start
    val activeFraction = if (rangeLength > 0f) {
        ((value - valueRange.start) / rangeLength).coerceIn(0f, 1f)
    } else {
        0f
    }
    val updateFromFraction: (Float) -> Unit = { fraction ->
        currentOnValueChange(sliderValueAtFraction(fraction, valueRange, steps))
    }

    BoxWithConstraints(
        modifier = modifier
            .height(48.dp)
            .semantics {
                if (!enabled) disabled()
                progressBarRangeInfo = ProgressBarRangeInfo(value, valueRange, steps)
                setProgress { requestedValue ->
                    if (!enabled) {
                        false
                    } else {
                        val updated = sliderValueAtFraction(
                            fraction = if (rangeLength > 0f) {
                                (requestedValue - valueRange.start) / rangeLength
                            } else {
                                0f
                            },
                            valueRange = valueRange,
                            steps = steps,
                        )
                        if (updated == value) {
                            false
                        } else {
                            currentOnValueChange(updated)
                            currentOnValueChangeFinished?.invoke()
                            true
                        }
                    }
                }
            }
            .pointerInput(enabled, valueRange, steps, layoutDirection) {
                if (!enabled) return@pointerInput
                val thumbRadius = 9.dp.toPx()
                val travelWidth = (size.width - (thumbRadius * 2f)).coerceAtLeast(1f)
                fun fractionAt(pointerX: Float): Float {
                    val physicalFraction = ((pointerX - thumbRadius) / travelWidth).coerceIn(0f, 1f)
                    return if (layoutDirection == LayoutDirection.Rtl) 1f - physicalFraction else physicalFraction
                }
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    updateFromFraction(fractionAt(down.position.x))
                    down.consume()
                    val completed = drag(down.id) { change ->
                        updateFromFraction(fractionAt(change.position.x))
                        change.consume()
                    }
                    if (completed) currentOnValueChangeFinished?.invoke()
                }
            },
        contentAlignment = Alignment.CenterStart,
    ) {
        val thumbSize = 18.dp
        val trackWidth = (maxWidth - thumbSize).coerceAtLeast(0.dp)
        Box(
            Modifier
                .align(Alignment.Center)
                .fillMaxWidth()
                .padding(horizontal = thumbSize / 2)
                .height(6.dp)
                .background(colors.accentSoft, CircleShape),
        ) {
            Box(
                Modifier
                    .fillMaxWidth(activeFraction)
                    .fillMaxHeight()
                    .background(if (enabled) colors.actionAccent else colors.divider, CircleShape),
            )
        }
        Surface(
            modifier = Modifier
                .align(Alignment.CenterStart)
                .offset(x = trackWidth * activeFraction)
                .size(thumbSize),
            shape = CircleShape,
            color = if (enabled) colors.actionAccent else colors.divider,
            border = BorderStroke(2.dp, colors.surface),
            shadowElevation = if (enabled) 2.dp else 0.dp,
        ) {}
    }
}

private fun sliderValueAtFraction(
    fraction: Float,
    valueRange: ClosedFloatingPointRange<Float>,
    steps: Int,
): Float {
    val clampedFraction = fraction.coerceIn(0f, 1f)
    val snappedFraction = if (steps > 0) {
        val intervals = steps + 1
        (clampedFraction * intervals).roundToInt().toFloat() / intervals
    } else {
        clampedFraction
    }
    return valueRange.start + (valueRange.endInclusive - valueRange.start) * snappedFraction
}

@Composable
private fun RowScope.ReaderNavAction(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: Int,
    tag: String,
    focusRequester: FocusRequester,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    TextButton(
        onClick,
        Modifier
            .weight(1f)
            .height(60.dp)
            .testTag(tag)
            .focusRequester(focusRequester),
        enabled = enabled,
        shape = RoundedCornerShape(WarmPageThemeValues.radii.control),
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Icon(icon, contentDescription = null)
            Text(stringResource(label), style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun progressLabel(preferences: ReaderPreferences, location: ReaderLocation?, progress: Float?): String {
    val percent = progress?.let { stringResource(R.string.reader_progress_percent, (it * 100).toInt()) }
    val position = when (location) {
        is ReflowReaderLocation -> location.position?.let { stringResource(R.string.reader_position, it) }
        is ComicReaderLocation -> stringResource(R.string.reader_comic_page, location.pageIndex + 1)
        is PdfReaderLocation -> stringResource(R.string.reader_pdf_page, location.pageIndex + 1)
        else -> null
    }
    return when (preferences.display.progressStyle) {
        ReaderProgressStyle.Hidden -> ""
        ReaderProgressStyle.Percent -> percent ?: position.orEmpty()
        ReaderProgressStyle.Position -> position ?: percent.orEmpty()
        ReaderProgressStyle.Remaining -> progress?.let {
            stringResource(
                R.string.reader_progress_remaining_percent,
                ((1f - it) * 100).roundToInt().coerceIn(0, 100),
            )
        } ?: position.orEmpty()
        ReaderProgressStyle.Auto -> percent ?: position.orEmpty()
    }
}

internal fun readerTotalProgression(
    location: ReaderLocation?,
    lastPageIndex: Int,
    presentationProgress: Double? = null,
): Double? = presentationProgress ?: when (location) {
    is ReflowReaderLocation -> location.totalProgression
    is ComicReaderLocation -> pageProgression(location.pageIndex, lastPageIndex)
    is PdfReaderLocation -> pageProgression(location.pageIndex, lastPageIndex)
    else -> null
}?.coerceIn(0.0, 1.0)

private fun pageProgression(pageIndex: Int, lastPageIndex: Int): Double =
    if (lastPageIndex <= 0) 1.0 else pageIndex.toDouble() / lastPageIndex

@Composable
private fun rememberClock(enabled: Boolean): String? {
    var now by remember { mutableStateOf(Date()) }
    LaunchedEffect(enabled) {
        while (enabled) {
            now = Date()
            delay(30_000)
        }
    }
    return if (enabled) DateFormat.getTimeInstance(DateFormat.SHORT).format(now) else null
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderPreferenceSheet(
    panel: ReaderPanel,
    preferences: ReaderPreferences,
    morphology: ReaderMorphology,
    settingState: (ReaderSettingDefinition) -> ReaderSettingState,
    negativeLetterSpacingEnabled: Boolean,
    failure: ReaderCommandRejected?,
    onUpdate: (ReaderPreferences) -> Unit,
    onDismiss: () -> Unit,
) = ReaderSheet(
    title = if (panel == ReaderPanel.Appearance) R.string.reader_appearance else R.string.reader_settings_title,
    onDismiss = onDismiss,
    usePageTitle = true,
) { scroll ->
    val chinese = androidx.compose.ui.platform.LocalConfiguration.current.locales[0].language == "zh"
    val theme = WarmPageThemeValues
    var advanced by remember { mutableStateOf(false) }
    val sections = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.sections.filter {
        it.panel == if (panel == ReaderPanel.Appearance) "appearance" else "settings"
    }
    val populatedSections = sections.mapNotNull { section ->
        val settings = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.settings.filter {
            it.section == section.id && morphology in it.formats
        }
        if (settings.isEmpty()) null else section to settings
    }
    val regularSections = populatedSections.filter { !it.first.advanced && it.first.id != "reset" }
    val advancedSections = populatedSections.filter { it.first.advanced }
    val resetSections = populatedSections.filter { it.first.id == "reset" }
    val sectionStyle = if (panel == ReaderPanel.Settings) {
        ReaderPreferenceSectionStyle.GroupedCard
    } else {
        ReaderPreferenceSectionStyle.Flat
    }
    Column(
        Modifier.verticalScroll(scroll).testTag(READER_PREFERENCES_SCROLL_TEST_TAG),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.three),
    ) {
        if (failure != null) {
            WarmSettingsInlineMessage(
                message = readerPreferenceFailureMessage(failure),
                modifier = Modifier.background(MaterialTheme.colorScheme.errorContainer),
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
        }
        regularSections.forEach { (section, settings) ->
            ReaderPreferenceSection(
                section,
                settings,
                preferences,
                settingState,
                negativeLetterSpacingEnabled,
                chinese,
                onUpdate,
                sectionStyle,
            )
        }
        if (advancedSections.isNotEmpty()) {
            val advancedStateDescription = stringResource(
                if (advanced) R.string.reader_advanced_expanded else R.string.reader_advanced_collapsed,
            )
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.three),
            ) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(theme.radii.task),
                    color = theme.colors.surfaceRaised,
                    border = BorderStroke(theme.components.dividerThickness, theme.colors.divider),
                    tonalElevation = 0.dp,
                    shadowElevation = 0.dp,
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = theme.components.settings.rowMinimumHeight)
                            .testTag("reader-advanced-settings")
                            .clickable(
                                role = Role.Button,
                                onClick = { advanced = !advanced },
                            )
                            .semantics(mergeDescendants = true) {
                                heading()
                                stateDescription = advancedStateDescription
                            }
                            .padding(
                                horizontal = theme.components.settings.horizontalInset,
                                vertical = theme.components.settings.verticalInset,
                            ),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            stringResource(R.string.reader_advanced_settings),
                            modifier = Modifier.weight(1f),
                            style = theme.typography.headline,
                            color = theme.colors.textPrimary,
                        )
                        Icon(
                            Icons.Default.ExpandMore,
                            contentDescription = null,
                            tint = theme.colors.textSecondary,
                            modifier = Modifier
                                .size(theme.components.controls.iconSize)
                                .rotate(if (advanced) 180f else 0f),
                        )
                    }
                }
                if (advanced) {
                    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.three)) {
                        advancedSections.forEach { (section, settings) ->
                            ReaderPreferenceSection(
                                section,
                                settings,
                                preferences,
                                settingState,
                                negativeLetterSpacingEnabled,
                                chinese,
                                onUpdate,
                                sectionStyle,
                            )
                        }
                    }
                }
            }
        }
        resetSections.forEach { (section, settings) ->
            ReaderPreferenceSection(
                section,
                settings,
                preferences,
                settingState,
                negativeLetterSpacingEnabled,
                chinese,
                onUpdate,
                sectionStyle,
            )
        }
    }
}

private enum class ReaderPreferenceSectionStyle {
    Flat,
    GroupedCard,
}

@Composable
private fun ReaderPreferenceSection(
    section: com.ermao.library.shared.modules.reader.ReaderSettingSection,
    settings: List<ReaderSettingDefinition>,
    preferences: ReaderPreferences,
    settingState: (ReaderSettingDefinition) -> ReaderSettingState,
    negativeLetterSpacingEnabled: Boolean,
    chinese: Boolean,
    onUpdate: (ReaderPreferences) -> Unit,
    style: ReaderPreferenceSectionStyle,
) {
    val theme = WarmPageThemeValues
    val settingsWithState = settings.map { it to settingState(it) }
    if (section.id == "reset") {
        HorizontalDivider(color = theme.colors.divider)
    }
    if (section.id == "top" || section.id == "reset") {
        Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
            settingsWithState.forEachIndexed { index, (setting, state) ->
                if (index > 0) HorizontalDivider(color = theme.colors.divider)
                ReaderCatalogSetting(
                    setting,
                    preferences,
                    state,
                    negativeLetterSpacingEnabled,
                    chinese,
                    onUpdate,
                )
            }
        }
    } else if (style == ReaderPreferenceSectionStyle.Flat) {
        WarmSettingsSection(
            title = if (chinese) section.chinese else section.english,
        ) {
            settingsWithState.forEachIndexed { index, (setting, state) ->
                if (index > 0) HorizontalDivider(color = theme.colors.divider)
                ReaderCatalogSetting(
                    setting,
                    preferences,
                    state,
                    negativeLetterSpacingEnabled,
                    chinese,
                    onUpdate,
                )
            }
        }
    } else {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .testTag("reader-setting-section-${section.id}"),
        ) {
            Text(
                text = if (chinese) section.chinese else section.english,
                style = theme.typography.headline,
                color = theme.colors.textPrimary,
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("reader-setting-section-heading-${section.id}")
                    .padding(
                        start = theme.components.settings.horizontalInset,
                        end = theme.components.settings.horizontalInset,
                        bottom = theme.components.settings.sectionHeaderBottomSpacing,
                    )
                    .semantics { heading() },
            )
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("reader-setting-section-card-${section.id}"),
                shape = RoundedCornerShape(theme.radii.task),
                color = theme.colors.surfaceRaised,
                border = BorderStroke(theme.components.dividerThickness, theme.colors.divider),
                tonalElevation = 0.dp,
                shadowElevation = 0.dp,
            ) {
                Column {
                    settingsWithState.forEachIndexed { index, (setting, state) ->
                        if (index > 0) WarmSettingsDivider()
                        ReaderCatalogSetting(
                            setting,
                            preferences,
                            state,
                            negativeLetterSpacingEnabled,
                            chinese,
                            onUpdate,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun readerPreferenceFailureMessage(failure: ReaderCommandRejected?): String = stringResource(when (failure?.reasonCode) {
    "READER_PREFERENCES_SAVE_FAILED" -> R.string.reader_preferences_save_failed
    "READER_PREFERENCES_ENGINE_FAILED" -> R.string.reader_preferences_engine_failed
    else -> R.string.reader_preferences_apply_failed
})

@Composable
private fun readerViewportIsWide(): Boolean {
    val containerWidth = LocalWindowInfo.current.containerSize.width
    return with(LocalDensity.current) {
        containerWidth.toDp() > READER_WIDE_VIEWPORT_MIN_WIDTH
    }
}

@Composable
private fun ReaderCatalogSetting(
    setting: ReaderSettingDefinition,
    preferences: ReaderPreferences,
    state: ReaderSettingState,
    negativeLetterSpacingEnabled: Boolean,
    chinese: Boolean,
    onUpdate: (ReaderPreferences) -> Unit,
) {
    val theme = WarmPageThemeValues
    val label = if (chinese) setting.chinese else setting.english
    val value = setting.value(preferences)
    var choiceSheetVisible by remember(setting.id) { mutableStateOf(false) }
    val available = state.availability == ReaderControlAvailability.Available
    val fixedSwipe = setting.id == "swipePageTurn" &&
        state.availability == ReaderControlAvailability.NotImplemented &&
        state.reasonId == "notImplemented"
    val selectedValueLabel = setting.options.firstOrNull { option ->
        option.value == value ||
            option.value.toDoubleOrNull()?.let { number -> number == value.toDoubleOrNull() } == true
    }?.let { option -> if (chinese) option.chinese else option.english } ?: value
    val unavailableReason = state.reasonId?.let(
        com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.availabilityReasons::get,
    )
    val unavailableMessage = unavailableReason?.let { if (chinese) it.chinese else it.english }
        ?: stringResource(R.string.reader_setting_unavailable_short)
    fun change(value: String) {
        var updated = setting.change(preferences, value)
        if (setting.id == "theme") updated = updated.copy(appearance = updated.appearance.copy(themeMode = ReaderThemeMode.Manual))
        onUpdate(updated)
    }
    Column(
        Modifier.fillMaxWidth().testTag("reader-setting-${setting.id}"),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
    ) {
        if (!available) {
            val status = when {
                fixedSwipe -> stringResource(R.string.reader_setting_always_on)
                state.availability == ReaderControlAvailability.NotImplemented ->
                    stringResource(R.string.reader_setting_not_adjustable)
                else -> stringResource(R.string.reader_setting_temporarily_unavailable)
            }
            val explanation = when {
                fixedSwipe -> stringResource(R.string.reader_setting_swipe_always_on_explanation)
                state.availability == ReaderControlAvailability.NotImplemented ->
                    stringResource(R.string.reader_setting_not_adjustable_explanation)
                else -> unavailableMessage
            }
            WarmSettingsValueRow(
                label = label,
                value = status,
                supporting = explanation,
                modifier = Modifier
                    .testTag("reader-setting-readonly-${setting.id}")
                    .semantics(mergeDescendants = true) {},
            )
            return@Column
        }
        when (setting.kind) {
            "action" -> TextButton(
                onClick = { onUpdate(resetReaderPreferences()) },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = theme.components.controls.minimumTouchTarget),
            ) {
                Text(
                    text = label,
                    modifier = Modifier.fillMaxWidth(),
                    style = theme.typography.button,
                    color = theme.colors.textSecondary,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Start,
                )
            }
            "toggle" -> {
                val checked = value == "true" || value == "system"
                WarmSettingsSwitchRow(
                    label = label,
                    checked = checked,
                    modifier = Modifier.testTag("reader-setting-control-${setting.id}"),
                    onCheckedChange = {
                        change(if (setting.id == "themeMode") {
                            if (it) "system" else "manual"
                        } else it.toString())
                    },
                )
            }
            "number" -> ReaderNumberSetting(setting, label, value.toDouble(), available, ::change)
            else -> {
                if (setting.id == "theme") {
                    Text(
                        text = label,
                        style = theme.typography.body,
                        color = theme.colors.textPrimary,
                        modifier = Modifier.padding(horizontal = theme.spacing.two),
                    )
                    ReaderThemeChoices(setting, value, chinese, available, ::change)
                } else if (
                    setting.options.size > 4 ||
                    setting.options.any { option ->
                        val optionLabel = if (chinese) option.chinese else option.english
                        optionLabel.length > 16
                    }
                ) {
                    WarmSettingsValueRow(
                        label = label,
                        value = selectedValueLabel,
                        modifier = Modifier.testTag("reader-setting-control-${setting.id}"),
                        onClick = { choiceSheetVisible = true },
                        enabled = available,
                    )
                    if (choiceSheetVisible) {
                        WarmSettingsChoiceSheet(
                            title = label,
                            options = setting.options.map { option ->
                                WarmSettingsChoice(
                                    id = option.value,
                                    value = option.value,
                                    label = if (chinese) option.chinese else option.english,
                                    enabled = setting.id != "letterSpacing" ||
                                        option.value.toDouble() >= 0 || negativeLetterSpacingEnabled,
                                )
                            },
                            selected = value,
                            onSelect = ::change,
                            onDismissRequest = { choiceSheetVisible = false },
                        )
                    }
                } else {
                    Text(
                        text = label,
                        style = theme.typography.body,
                        color = theme.colors.textPrimary,
                        modifier = Modifier.padding(horizontal = theme.spacing.two),
                    )
                    WarmPageSegmentedControl(
                        options = setting.options.map { option ->
                            WarmPageChoice(
                                value = option.value,
                                label = if (chinese) option.chinese else option.english,
                                enabled = setting.id != "letterSpacing" ||
                                    option.value.toDouble() >= 0 ||
                                    negativeLetterSpacingEnabled,
                            )
                        },
                        selected = value,
                        onSelect = ::change,
                        enabled = available,
                        modifier = Modifier.padding(
                            horizontal = theme.components.settings.horizontalInset,
                        ).testTag("reader-setting-control-${setting.id}"),
                    )
                }
                if (setting.options.none { it.value == value || it.value.toDoubleOrNull()?.let { number -> number == value.toDoubleOrNull() } == true }) {
                    WarmSettingsInlineMessage(
                        message = stringResource(R.string.reader_setting_saved_value, value),
                    )
                }
            }
        }
        if (setting.id == "letterSpacing" && !negativeLetterSpacingEnabled) {
            WarmSettingsInlineMessage(stringResource(R.string.reader_negative_spacing_retained))
        }
        if (setting.id == "fontFamily") {
            WarmSettingsInlineMessage(stringResource(R.string.reader_font_mapping))
        }
    }
}

@Composable
private fun ReaderThemeChoices(
    setting: com.ermao.library.shared.modules.reader.ReaderSettingDefinition,
    value: String,
    chinese: Boolean,
    available: Boolean,
    onChange: (String) -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = WarmPageThemeValues.components.settings.horizontalInset),
        horizontalArrangement = Arrangement.SpaceEvenly,
    ) {
        setting.options.forEach { option ->
            val selected = option.value == value
            val label = if (chinese) option.chinese else option.english
            Box(
                Modifier
                    .size(48.dp)
                    .selectable(
                        selected = selected,
                        enabled = available,
                        role = Role.RadioButton,
                        onClick = { onChange(option.value) },
                    )
                    .semantics { contentDescription = label },
                contentAlignment = Alignment.Center,
            ) {
                Surface(
                    Modifier.size(34.dp),
                    shape = CircleShape,
                    color = readerThemeSwatch(option.value),
                    border = BorderStroke(if (selected) 2.dp else 1.dp, if (selected) WarmPageThemeValues.colors.actionAccent else WarmPageThemeValues.colors.divider),
                ) {
                    if (selected) {
                        Box(contentAlignment = Alignment.Center) {
                            Icon(Icons.Default.Check, null, Modifier.size(18.dp), tint = readerThemeSwatchForeground(option.value))
                        }
                    }
                }
            }
        }
    }
}

private fun readerThemeSwatch(value: String): androidx.compose.ui.graphics.Color = when (value) {
    "day" -> androidx.compose.ui.graphics.Color(0xFFF7F7F4)
    "warm" -> androidx.compose.ui.graphics.Color(0xFFFDF6EA)
    "green" -> androidx.compose.ui.graphics.Color(0xFFE8F0E3)
    "night" -> androidx.compose.ui.graphics.Color(0xFF151311)
    "black" -> androidx.compose.ui.graphics.Color.Black
    else -> androidx.compose.ui.graphics.Color.Transparent
}

private fun readerThemeSwatchForeground(value: String): androidx.compose.ui.graphics.Color =
    if (value == "night" || value == "black") androidx.compose.ui.graphics.Color.White else androidx.compose.ui.graphics.Color(0xFF2B2118)

@Composable
private fun ReaderNumberSetting(
    setting: com.ermao.library.shared.modules.reader.ReaderSettingDefinition,
    label: String,
    number: Double,
    available: Boolean,
    onChange: (String) -> Unit,
) {
    val theme = WarmPageThemeValues
    if (setting.id.endsWith("PageWidth")) {
        var sliderValue by remember(number) { mutableFloatStateOf(number.toFloat()) }
        Text(
            text = label,
            style = theme.typography.body,
            color = theme.colors.textPrimary,
            modifier = Modifier.padding(horizontal = theme.spacing.two),
        )
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = theme.components.settings.rowMinimumHeight)
                .padding(horizontal = theme.spacing.two),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ReaderSlider(
                value = sliderValue,
                onValueChange = { sliderValue = it },
                onValueChangeFinished = { onChange(numberSettingValue(setting, sliderValue.toDouble())) },
                valueRange = setting.minimum.toFloat()..setting.maximum.toFloat(),
                steps = ((setting.maximum - setting.minimum) / setting.step).roundToInt().minus(1).coerceAtLeast(0),
                enabled = available,
                modifier = Modifier
                    .weight(1f)
                    .semantics { contentDescription = label },
            )
            Text(
                "${sliderValue.roundToInt()} px",
                Modifier.width(64.dp),
                style = theme.typography.label,
                color = theme.colors.textSecondary,
                textAlign = androidx.compose.ui.text.style.TextAlign.End,
            )
        }
    } else {
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 54.dp)
                .padding(horizontal = theme.spacing.two),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
        ) {
            Text(
                label,
                Modifier.weight(1f),
                style = theme.typography.body,
                color = theme.colors.textPrimary,
            )
            IconButton(
                onClick = { onChange(numberSettingValue(setting, number - setting.step)) },
                enabled = available && number > setting.minimum,
                modifier = Modifier.semantics { contentDescription = "${label} −" },
            ) { Icon(Icons.Default.Remove, null, Modifier.size(theme.components.controls.iconSize)) }
            Text(
                if (setting.id.endsWith("Zoom")) "${(number * 100).roundToInt()}%" else java.text.NumberFormat.getNumberInstance().format(number),
                Modifier.width(64.dp),
                style = theme.typography.label,
                color = theme.colors.textPrimary,
                textAlign = androidx.compose.ui.text.style.TextAlign.End,
            )
            IconButton(
                onClick = { onChange(numberSettingValue(setting, number + setting.step)) },
                enabled = available && number < setting.maximum,
                modifier = Modifier.semantics { contentDescription = "${label} +" },
            ) { Icon(Icons.Default.Add, null, Modifier.size(theme.components.controls.iconSize)) }
        }
    }
}

private fun numberSettingValue(setting: com.ermao.library.shared.modules.reader.ReaderSettingDefinition, number: Double): String {
    val bounded = number.coerceIn(setting.minimum, setting.maximum)
    return if (setting.step >= 1) bounded.roundToInt().toString() else (kotlin.math.round(bounded * 100) / 100).toString()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderNotesSheet(
    capabilities: ReaderCapabilities,
    bookmarks: List<ReaderBookmark>,
    syncPending: Boolean,
    navigationFailed: Boolean,
    onJump: (String) -> Unit,
    onRemove: (String) -> Unit,
    snackbarHostState: SnackbarHostState,
    onDismiss: () -> Unit,
) =
    ReaderSheet(R.string.reader_notes, onDismiss, snackbarHostState) { scroll ->
        Column(
            Modifier.verticalScroll(scroll),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (navigationFailed) Text(stringResource(R.string.reader_navigation_failed), color = MaterialTheme.colorScheme.error)
            WarmPageSegmentedControl(
                options = listOf(
                    WarmPageChoice("bookmarks", stringResource(R.string.reader_bookmarks)),
                    WarmPageChoice("annotations", stringResource(R.string.reader_annotations), capabilities.supportsAnnotations),
                ),
                selected = "bookmarks",
                onSelect = {},
            )
            if (syncPending) Text(stringResource(R.string.reader_bookmarks_pending), color = MaterialTheme.colorScheme.primary)
            if (bookmarks.isEmpty()) {
                Surface(
                    color = WarmPageThemeValues.colors.surfaceRaised,
                    shape = RoundedCornerShape(WarmPageThemeValues.radii.task),
                    border = BorderStroke(1.dp, WarmPageThemeValues.colors.divider),
                ) {
                    Column(
                        Modifier.fillMaxWidth().padding(vertical = 28.dp, horizontal = 20.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Icon(Icons.Default.BookmarkBorder, null, tint = WarmPageThemeValues.colors.textSecondary)
                        Text(stringResource(R.string.reader_bookmarks_empty), style = MaterialTheme.typography.titleSmall)
                        Text(
                            stringResource(R.string.reader_bookmarks_empty_hint),
                            style = MaterialTheme.typography.bodySmall,
                            color = WarmPageThemeValues.colors.textSecondary,
                        )
                    }
                }
            } else {
                bookmarks.forEach { bookmark ->
                    Surface(
                        color = WarmPageThemeValues.colors.surfaceRaised,
                        shape = RoundedCornerShape(WarmPageThemeValues.radii.control),
                        border = BorderStroke(1.dp, WarmPageThemeValues.colors.divider),
                    ) {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            TextButton({ onJump(bookmark.id) }, Modifier.weight(1f)) {
                                Column(Modifier.fillMaxWidth()) {
                                    Text(bookmark.label, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(
                                        stringResource(R.string.reader_progress_percent, bookmark.displayPercent.toInt()),
                                        style = MaterialTheme.typography.labelSmall,
                                    )
                                }
                            }
                            IconButton({ onRemove(bookmark.id) }) {
                                Icon(Icons.Default.Delete, stringResource(R.string.reader_bookmark_remove))
                            }
                        }
                    }
                }
            }
        }
    }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderContentsSheet(
    state: ReaderContentsLoadState,
    currentLocation: ReaderLocation?,
    pendingEntryId: String?,
    navigationFailed: Boolean,
    onDismiss: () -> Unit,
    onRetry: () -> Unit,
    onSelect: (ReaderTocEntry) -> Unit,
) = WarmPageModalBottomSheet(onDismissRequest = onDismiss) {
    Column(
        Modifier
            .fillMaxWidth()
            .fillMaxHeight(0.82f)
            .padding(horizontal = 16.dp)
            .testTag(READER_SHEET_TEST_TAG),
    ) {
        ReaderSheetHeader(R.string.reader_contents_title, onDismiss)
        when (state) {
            ReaderContentsLoadState.NotRequested,
            ReaderContentsLoadState.Loading -> Box(
                Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .testTag(READER_CONTENTS_LOADING_TEST_TAG),
                contentAlignment = Alignment.Center,
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
                    Text(
                        stringResource(R.string.reader_contents_loading),
                        color = WarmPageThemeValues.colors.textSecondary,
                    )
                }
            }
            ReaderContentsLoadState.Failed -> Column(
                Modifier.fillMaxWidth().weight(1f),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Text(
                    stringResource(R.string.reader_contents_load_failed),
                    color = MaterialTheme.colorScheme.error,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.retry_action)) }
            }
            is ReaderContentsLoadState.Ready -> {
                val currentLabel = readerContentsCurrentLabel(currentLocation)
                LazyColumn(
                    Modifier.fillMaxWidth().weight(1f),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                if (navigationFailed) {
                    item(key = "navigation-failed") {
                        Text(
                            stringResource(R.string.reader_navigation_failed),
                            Modifier.fillMaxWidth().padding(vertical = 8.dp),
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
                currentLabel?.let { current ->
                    item(key = "current-location") {
                        Surface(
                            color = WarmPageThemeValues.colors.accentSoft,
                            shape = RoundedCornerShape(WarmPageThemeValues.radii.control),
                        ) {
                            Text(
                                stringResource(R.string.reader_contents_current, current),
                                Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
                                style = MaterialTheme.typography.labelMedium,
                                color = WarmPageThemeValues.colors.actionAccent,
                            )
                        }
                    }
                }
                if (state.entries.isEmpty()) {
                    item(key = "empty") {
                        Text(stringResource(R.string.reader_contents_empty), Modifier.padding(vertical = 24.dp))
                    }
                }
                itemsIndexed(
                    state.entries,
                    key = { index, entry -> "${entry.entry.id}:$index" },
                ) { index, entry ->
                    val selected = readerContentsEntrySelected(currentLocation, entry.entry.location)
                    Surface(
                        color = if (selected) WarmPageThemeValues.colors.accentSoft else WarmPageThemeValues.colors.surfaceRaised,
                        shape = RoundedCornerShape(WarmPageThemeValues.radii.control),
                        border = BorderStroke(1.dp, if (selected) WarmPageThemeValues.colors.accentSoft else WarmPageThemeValues.colors.divider),
                    ) {
                        TextButton(
                            { onSelect(entry.entry) },
                            Modifier.fillMaxWidth(),
                            enabled = pendingEntryId == null,
                            shape = RoundedCornerShape(WarmPageThemeValues.radii.control),
                        ) {
                            Row(
                                Modifier.fillMaxWidth().padding(start = (entry.depth * 12).dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    (index + 1).toString(),
                                    Modifier.width(36.dp),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = WarmPageThemeValues.colors.textTertiary,
                                )
                                Text(
                                    entry.entry.title,
                                    Modifier.weight(1f),
                                    color = if (selected) WarmPageThemeValues.colors.actionAccent else WarmPageThemeValues.colors.textPrimary,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                if (pendingEntryId == entry.entry.id) {
                                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                                }
                            }
                        }
                    }
                }
                item(key = "bottom-space") { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }
}

private sealed interface ReaderContentsLoadState {
    data object NotRequested : ReaderContentsLoadState
    data object Loading : ReaderContentsLoadState
    data object Failed : ReaderContentsLoadState
    data class Ready(val entries: List<ReaderTocNode>) : ReaderContentsLoadState
}

private fun readerContentsEntrySelected(current: ReaderLocation?, entry: ReaderLocation): Boolean = when {
    current is ReflowReaderLocation && entry is ReflowReaderLocation -> current.resourceKey == entry.resourceKey
    current is ComicReaderLocation && entry is ComicReaderLocation ->
        current.resourceHref == entry.resourceHref && current.pageIndex == entry.pageIndex
    current is PdfReaderLocation && entry is PdfReaderLocation -> current.pageIndex == entry.pageIndex
    else -> false
}

@Composable
private fun readerContentsCurrentLabel(location: ReaderLocation?): String? = when (location) {
    is ComicReaderLocation -> stringResource(R.string.reader_comic_page, location.pageIndex + 1)
    is PdfReaderLocation -> stringResource(R.string.reader_pdf_page, location.pageIndex + 1)
    else -> null
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderSheet(
    title: Int,
    onDismiss: () -> Unit,
    snackbarHostState: SnackbarHostState? = null,
    usePageTitle: Boolean = false,
    content: @Composable (ScrollState) -> Unit,
) {
    val theme = WarmPageThemeValues
    WarmPageModalBottomSheet(
        onDismissRequest = onDismiss,
        skipPartiallyExpanded = true,
    ) {
        Box(Modifier.fillMaxWidth()) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = theme.spacing.two)
                    .testTag(READER_SHEET_TEST_TAG),
            ) {
                ReaderSheetHeader(title, onDismiss, usePageTitle)
                Box(
                    modifier = Modifier.weight(1f, fill = false),
                ) {
                    content(rememberScrollState())
                }
                Spacer(Modifier.height(theme.spacing.six))
            }
            snackbarHostState?.let { hostState ->
                WarmPageSnackbarHost(
                    hostState = hostState,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(horizontal = theme.spacing.two, vertical = theme.spacing.one),
                )
            }
        }
    }
}

@Composable
private fun ReaderSheetHeader(
    title: Int,
    onDismiss: () -> Unit,
    usePageTitle: Boolean = false,
) {
    val theme = WarmPageThemeValues
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.settings.rowMinimumHeight),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            stringResource(title),
            Modifier
                .weight(1f)
                .semantics { heading() },
            style = if (usePageTitle) theme.typography.title else theme.typography.sectionTitle,
            color = theme.colors.textPrimary,
        )
        IconButton(onDismiss) { Icon(Icons.Default.Close, stringResource(R.string.reader_done)) }
    }
}

private fun currentBookmark(bookmarks: List<ReaderBookmark>, location: ReaderLocation?): Boolean {
    val current = location as? ReflowReaderLocation ?: return false
    return bookmarks.any { bookmark ->
        bookmark.position.presentation.currentHref == current.resourceKey &&
            kotlin.math.abs(
                bookmark.position.presentation.totalProgression -
                    (current.totalProgression ?: current.progression ?: 0.0),
            ) < 0.0001
    }
}

@Composable
private fun ReaderSystemBarAppearance(surface: Color) {
    val activity = LocalActivity.current
    val view = LocalView.current
    DisposableEffect(activity, view, surface) {
        val window = activity?.window ?: return@DisposableEffect onDispose {}
        val controller = WindowCompat.getInsetsController(window, view)
        val previousLightStatusBars = controller.isAppearanceLightStatusBars
        val previousLightNavigationBars = controller.isAppearanceLightNavigationBars
        val previousNavigationBarContrast = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.isNavigationBarContrastEnforced
        } else {
            null
        }
        val useDarkForeground = surface.luminance() >= SYSTEM_BAR_LIGHT_SURFACE_LUMINANCE
        controller.isAppearanceLightStatusBars = useDarkForeground
        controller.isAppearanceLightNavigationBars = useDarkForeground
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.isNavigationBarContrastEnforced = false
        }
        onDispose {
            controller.isAppearanceLightStatusBars = previousLightStatusBars
            controller.isAppearanceLightNavigationBars = previousLightNavigationBars
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && previousNavigationBarContrast != null) {
                window.isNavigationBarContrastEnforced = previousNavigationBarContrast
            }
        }
    }
}

@Composable
private fun KeepScreenAwake(enabled: Boolean) {
    val activity = LocalActivity.current
    DisposableEffect(activity, enabled) {
        if (enabled) activity?.window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else activity?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { activity?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
}

@Composable private fun BoxScope.ReaderOpeningIndicator() {
    Surface(Modifier.align(Alignment.Center).padding(32.dp), shape = MaterialTheme.shapes.large) {
        Row(Modifier.padding(24.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            CircularProgressIndicator(Modifier.size(28.dp)); Text(stringResource(R.string.reader_loading))
        }
    }
}

@Composable private fun BoxScope.ReaderOpenError(
    error: ReaderError,
    onClose: () -> Unit,
    onRetryOpen: (() -> Unit)?,
) {
    val message = when (error.code) {
        ReaderErrorCode.UnsupportedFormat -> R.string.reader_error_unsupported
        ReaderErrorCode.CorruptFile -> R.string.reader_error_corrupt
        ReaderErrorCode.DrmProtected -> R.string.reader_error_drm
        ReaderErrorCode.ParseFailed -> R.string.reader_error_parse
        ReaderErrorCode.ReadFailed -> R.string.reader_error_read
        ReaderErrorCode.SecurityRejected -> R.string.reader_error_security
        ReaderErrorCode.ResourceMissing -> R.string.reader_error_missing
        ReaderErrorCode.PublicationUnavailable -> R.string.reader_error_publication_unavailable
        ReaderErrorCode.PublicationChanged -> R.string.reader_error_publication_changed
        ReaderErrorCode.Unauthorized -> R.string.reader_error_unauthorized
        ReaderErrorCode.Forbidden -> R.string.reader_error_forbidden
        ReaderErrorCode.InvalidResponse -> R.string.reader_error_invalid_response
        ReaderErrorCode.ServerUnavailable -> R.string.reader_error_server_unavailable
        ReaderErrorCode.RequestTimeout -> R.string.reader_error_timeout
        ReaderErrorCode.TlsFailure -> R.string.reader_error_tls
        ReaderErrorCode.RateLimited -> R.string.reader_error_rate_limited
        ReaderErrorCode.TxtNulCharacter -> R.string.reader_error_txt_nul
        ReaderErrorCode.TxtEncodingUnsupported -> R.string.reader_error_txt_encoding
        ReaderErrorCode.TxtEmpty -> R.string.reader_error_txt_empty
        ReaderErrorCode.OutOfMemoryRisk -> R.string.reader_error_memory
        ReaderErrorCode.PublicationTooLarge -> R.string.reader_error_publication_too_large
        ReaderErrorCode.LocationRestoreFailed -> R.string.reader_error_location
        ReaderErrorCode.NetworkUnavailable -> R.string.reader_error_network
        ReaderErrorCode.ReaderEngineError -> R.string.reader_error_generic
        ReaderErrorCode.RangeUnsupported -> R.string.reader_error_pdf_range_unsupported
        ReaderErrorCode.RangeInvalid -> R.string.reader_error_pdf_range_invalid
        ReaderErrorCode.PdfEngineLimit -> R.string.reader_error_pdf_engine_limit
        ReaderErrorCode.ResourceChanged -> R.string.reader_error_pdf_resource_changed
        ReaderErrorCode.CacheIo -> R.string.reader_error_pdf_cache
        ReaderErrorCode.Invalid -> R.string.reader_error_pdf_invalid
        ReaderErrorCode.PageLoadFailed -> R.string.reader_error_pdf_page_load
        ReaderErrorCode.RenderFailed -> R.string.reader_error_pdf_render
        ReaderErrorCode.ComicArchiveOpenFailed -> R.string.reader_error_comic_open
        ReaderErrorCode.ComicArchiveEncrypted -> R.string.reader_error_comic_encrypted
        ReaderErrorCode.ComicArchivePartMissing -> R.string.reader_error_comic_part_missing
        ReaderErrorCode.ComicArchiveFormatUnsupported -> R.string.reader_error_comic_format
        ReaderErrorCode.ComicArchiveCorrupt -> R.string.reader_error_comic_corrupt
        ReaderErrorCode.ComicPageDecodeFailed -> R.string.reader_error_comic_page_decode
        ReaderErrorCode.ComicOutOfMemoryRisk -> R.string.reader_error_comic_memory
    }
    Surface(Modifier.align(Alignment.Center).padding(24.dp), shape = MaterialTheme.shapes.large) {
        Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.reader_error_title), style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(8.dp)); Text(stringResource(message))
            val stageLabel = when (error.safeContext["stage"]) {
                "manifest" -> R.string.reader_error_stage_manifest
                "positions" -> R.string.reader_error_stage_positions
                "chapter" -> R.string.reader_error_stage_chapter
                "resource" -> R.string.reader_error_stage_resource
                else -> null
            }
            stageLabel?.let { label ->
                Text(stringResource(R.string.reader_error_stage, stringResource(label)), style = MaterialTheme.typography.bodySmall)
            }
            error.safeContext["code"]?.let { code ->
                Text(stringResource(R.string.reader_error_code, code), style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(20.dp))
            onRetryOpen?.let { retry ->
                Button(retry) { Text(stringResource(R.string.reader_retry_open)) }
            }
            Button(onClose) { Text(stringResource(R.string.reader_close)) }
        }
    }
}

internal const val READER_NAVIGATOR_CONTAINER_ID = 0x3A110001
internal const val READER_NAVIGATOR_TEST_TAG = "reader-navigator"
internal const val READER_READY_TEST_TAG = "reader-ready"
internal const val READER_PREVIOUS_TEST_TAG = "reader-previous"
internal const val READER_NEXT_TEST_TAG = "reader-next"
internal const val READER_CONTENTS_TEST_TAG = "reader-contents"
internal const val READER_CONTENTS_LOADING_TEST_TAG = "reader-contents-loading"
internal const val READER_SETTINGS_TEST_TAG = "reader-settings"
internal const val READER_PROGRESS_TEST_TAG = "reader-progress"
internal const val READER_PASSIVE_STATUS_TEST_TAG = "reader-passive-status"
internal const val READER_LINE_HEIGHT_TEST_TAG = "reader-line-height"
internal const val READER_PREFERENCES_SCROLL_TEST_TAG = "reader-preferences-scroll"
internal const val READER_SHEET_TEST_TAG = "reader-sheet"
private const val PROGRESS_SEEK_FEEDBACK_TIMEOUT_MILLIS = 4_000L
private const val SYSTEM_BAR_LIGHT_SURFACE_LUMINANCE = 0.5f
private val READER_WIDE_VIEWPORT_MIN_WIDTH = 640.dp
