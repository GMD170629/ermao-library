package com.ermao.library.features.reader.presentation

import android.view.ViewGroup
import android.view.WindowManager
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.automirrored.filled.Notes
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.fragment.app.FragmentContainerView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ermao.library.R
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderPanel
import com.ermao.library.shared.modules.reader.ReaderControl
import com.ermao.library.shared.modules.reader.ReaderControlAvailability
import com.ermao.library.shared.modules.reader.resolveReaderControl
import com.ermao.library.shared.modules.reader.resetReaderPreferences
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderCommandRejected
import com.ermao.library.shared.modules.reader.ReaderNavigationCompleted
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReaderProgressStyle
import com.ermao.library.shared.modules.reader.ReaderThemeMode
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.ui.theme.ReaderWarmPageTheme
import com.ermao.library.ui.theme.WarmPageThemeValues
import com.ermao.library.ui.components.WarmPageSnackbarHost
import java.text.DateFormat
import java.util.Date
import kotlin.math.roundToInt
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

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
    val contentError by controller?.contentError?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<ReaderError?>(null) }
    val displayedError = openError ?: contentError
    val restoreWarning by controller?.restoreWarning?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<ReaderError?>(null) }
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
    val nativeUnavailable = controller?.unavailableControls(preferences).orEmpty()
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
    val controlEnabled: (ReaderControl) -> Boolean = { control ->
        resolveReaderControl(control, morphology, capabilities, preferences, controller != null, nativeUnavailable) ==
            ReaderControlAvailability.Available
    }
    LaunchedEffect(panel) {
        onPanelVisibilityChange(panel != null)
        if (panel == null) panelTrigger?.let { panelFocus[it]?.requestFocus() }
    }
    BackHandler(panel != null) { panel = null }
    var pendingNavigationId by remember(controller) { mutableStateOf<String?>(null) }
    var navigationFailed by remember(controller) { mutableStateOf(false) }
    val snackbarHostState = remember { SnackbarHostState() }
    val bookmarkAddedMessage = stringResource(R.string.reader_bookmark_added)
    val bookmarkRemovedMessage = stringResource(R.string.reader_bookmark_removed)
    val undoLabel = stringResource(R.string.undo_action)

    KeepScreenAwake(preferences.interaction.keepScreenAwake)
    ReaderWarmPageTheme(preferences.appearance.theme, preferences.appearance.themeMode) {
        val colors = WarmPageThemeValues.colors
        Box(Modifier.fillMaxSize().background(colors.canvas)) {
            AndroidView(
                modifier = Modifier.fillMaxSize().testTag(READER_NAVIGATOR_TEST_TAG),
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

            if (controller != null) {
                Box(Modifier.size(1.dp).alpha(0f).testTag(READER_READY_TEST_TAG))
            }

            ReaderControlsVisibility(controlsVisible) {
                ReaderControlOverlay(
                    title = title,
                    controller = controller,
                    location = currentLocation,
                    preferences = preferences,
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
                        if (it == ReaderPanel.Contents) navigationFailed = false
                        panel = it
                    },
                    onHide = { onControlsVisibleChange(false) },
                )
            }

            if (restoreWarning?.code == ReaderErrorCode.LocationRestoreFailed) {
                Surface(
                    modifier = Modifier.align(Alignment.TopCenter).statusBarsPadding().padding(16.dp),
                    color = colors.accentSoft,
                    shape = MaterialTheme.shapes.medium,
                ) {
                    Text(stringResource(R.string.reader_restore_warning), Modifier.padding(12.dp))
                }
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
                entries = controller?.tableOfContents.orEmpty(),
                currentLocation = currentLocation,
                pendingEntryId = pendingNavigationId,
                navigationFailed = navigationFailed,
                onDismiss = { panel = null },
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
                enabled = controlEnabled,
                failure = preferencesFailure,
                onUpdate = updatePreferences,
                onDismiss = { panel = null },
            )
            ReaderPanel.Settings -> ReaderPreferenceSheet(
                ReaderPanel.Settings,
                preferences,
                controller?.morphology ?: ReaderMorphology.Reflowable,
                enabled = controlEnabled,
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
    preferences: ReaderPreferences,
    bookmarks: List<ReaderBookmark>,
    onToggleBookmark: () -> Unit,
    panelFocus: Map<ReaderPanel, FocusRequester>,
    onClose: () -> Unit,
    onPanel: (ReaderPanel) -> Unit,
    onHide: () -> Unit,
) {
    val colors = WarmPageThemeValues.colors
    Box(Modifier.fillMaxSize()) {
        Surface(
            modifier = Modifier.align(Alignment.TopCenter).fillMaxWidth(),
            color = colors.surface,
        ) {
            Row(
                Modifier.statusBarsPadding().height(56.dp).padding(horizontal = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onClose) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.reader_close))
                }
                Text(title, Modifier.weight(1f), maxLines = 1, style = MaterialTheme.typography.titleMedium)
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
            Modifier.align(Alignment.Center).fillMaxWidth(0.34f).fillMaxHeight().clickable(onClick = onHide),
        )

        ReaderBottomConsole(
            controller,
            location,
            preferences,
            onPanel,
            panelFocus,
            Modifier.align(Alignment.BottomCenter),
        )
    }
}

@Composable
private fun ReaderBottomConsole(
    controller: ReaderScreenController?,
    currentLocation: ReaderLocation?,
    preferences: ReaderPreferences,
    onPanel: (ReaderPanel) -> Unit,
    panelFocus: Map<ReaderPanel, FocusRequester>,
    modifier: Modifier = Modifier,
) {
    val colors = WarmPageThemeValues.colors
    val totalProgression = readerTotalProgression(
        currentLocation,
        controller?.tableOfContents.orEmpty().lastIndex,
    )
    var sliderProgress by remember { mutableFloatStateOf(totalProgression.toFloat()) }
    var dragging by remember { mutableStateOf(false) }
    LaunchedEffect(totalProgression, dragging) { if (!dragging) sliderProgress = totalProgression.toFloat() }
    val clock = rememberClock(preferences.display.showClock)
    val progressDescription = stringResource(R.string.reader_progress_slider)

    Surface(modifier.fillMaxWidth(), color = colors.surface) {
        Column(Modifier.navigationBarsPadding()) {
            HorizontalDivider(color = colors.divider)
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = { controller?.goPrevious() }, enabled = controller != null) {
                    Icon(Icons.Default.ChevronLeft, stringResource(R.string.reader_previous))
                }
                Column(Modifier.weight(1f)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(progressLabel(preferences, currentLocation, sliderProgress), style = MaterialTheme.typography.labelSmall)
                        if (clock != null) Text(clock, style = MaterialTheme.typography.labelSmall)
                    }
                    Slider(
                        value = sliderProgress,
                        onValueChange = { dragging = true; sliderProgress = it },
                        onValueChangeFinished = {
                            controller?.goToTotalProgression(sliderProgress.toDouble())
                            dragging = false
                        },
                        enabled = controller != null && currentLocation != null,
                        modifier = Modifier.semantics { contentDescription = progressDescription }
                            .testTag(READER_PROGRESS_TEST_TAG),
                    )
                }
                IconButton(onClick = { controller?.goNext() }, enabled = controller != null) {
                    Icon(Icons.Default.ChevronRight, stringResource(R.string.reader_next))
                }
            }
            HorizontalDivider(color = colors.divider)
            Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp)) {
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

@Composable
private fun RowScope.ReaderNavAction(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: Int,
    tag: String,
    focusRequester: FocusRequester,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    TextButton(onClick, Modifier.weight(1f).testTag(tag).focusRequester(focusRequester), enabled = enabled) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, contentDescription = null)
            Text(stringResource(label), style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun progressLabel(preferences: ReaderPreferences, location: ReaderLocation?, progress: Float): String {
    val percent = stringResource(R.string.reader_progress_percent, (progress * 100).toInt())
    val position = when (location) {
        is ReflowReaderLocation -> location.position?.let { stringResource(R.string.reader_position, it) }
        is ComicReaderLocation -> stringResource(R.string.reader_comic_page, location.pageIndex + 1)
        is PdfReaderLocation -> stringResource(R.string.reader_pdf_page, location.pageIndex + 1)
        else -> null
    } ?: percent
    return when (preferences.display.progressStyle) {
        ReaderProgressStyle.Hidden -> ""
        ReaderProgressStyle.Percent -> percent
        ReaderProgressStyle.Position -> position
        ReaderProgressStyle.Remaining -> stringResource(
            R.string.reader_progress_remaining_percent,
            ((1f - progress) * 100).roundToInt().coerceIn(0, 100),
        )
        ReaderProgressStyle.Auto -> percent
    }
}

internal fun readerTotalProgression(location: ReaderLocation?, lastPageIndex: Int): Double = when (location) {
    is ReflowReaderLocation -> location.totalProgression ?: location.progression ?: 0.0
    is ComicReaderLocation -> pageProgression(location.pageIndex, lastPageIndex)
    is PdfReaderLocation -> pageProgression(location.pageIndex, lastPageIndex)
    else -> 0.0
}.coerceIn(0.0, 1.0)

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
    enabled: (ReaderControl) -> Boolean,
    failure: ReaderCommandRejected?,
    onUpdate: (ReaderPreferences) -> Unit,
    onDismiss: () -> Unit,
) = ReaderSheet(if (panel == ReaderPanel.Appearance) R.string.reader_appearance else R.string.reader_settings_title, onDismiss) { scroll ->
    val chinese = androidx.compose.ui.platform.LocalConfiguration.current.locales[0].language == "zh"
    var advanced by remember { mutableStateOf(false) }
    val sections = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.sections.filter {
        it.panel == if (panel == ReaderPanel.Appearance) "appearance" else "settings"
    }
    Column(Modifier.verticalScroll(scroll)) {
        if (failure != null) Text(readerPreferenceFailureMessage(failure), color = MaterialTheme.colorScheme.error)
        sections.forEach { section ->
            val settings = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.settings.filter {
                it.section == section.id && morphology in it.formats
            }
            if (settings.isNotEmpty()) {
                if (section.id == "paragraph" && morphology == ReaderMorphology.Reflowable ||
                    section.id == "comicImage" && morphology == ReaderMorphology.Comic ||
                    section.id == "operations" && morphology == ReaderMorphology.Pdf) {
                    TextButton({ advanced = !advanced }) { Text(stringResource(R.string.reader_advanced_settings)) }
                }
                if (!section.advanced || advanced) {
                    if (section.chinese.isNotEmpty()) {
                        Text(if (chinese) section.chinese else section.english, Modifier.padding(top = 18.dp, bottom = 6.dp), style = MaterialTheme.typography.titleMedium)
                        HorizontalDivider()
                    }
                    settings.forEach { setting -> ReaderCatalogSetting(setting, preferences, enabled, chinese, onUpdate) }
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
private fun ReaderCatalogSetting(
    setting: com.ermao.library.shared.modules.reader.ReaderSettingDefinition,
    preferences: ReaderPreferences,
    enabled: (ReaderControl) -> Boolean,
    chinese: Boolean,
    onUpdate: (ReaderPreferences) -> Unit,
) {
    val label = if (chinese) setting.chinese else setting.english
    val value = setting.value(preferences)
    val available = setting.control?.let(enabled) ?: true
    val fixedSwipe = setting.id == "swipePageTurn" && !available
    fun change(value: String) {
        var updated = setting.change(preferences, value)
        if (setting.id == "theme") updated = updated.copy(appearance = updated.appearance.copy(themeMode = ReaderThemeMode.Manual))
        onUpdate(updated)
    }
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        when (setting.kind) {
            "action" -> Button({ onUpdate(resetReaderPreferences()) }, Modifier.fillMaxWidth()) { Text(label) }
            "toggle" -> Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(label, Modifier.weight(1f))
                val checked = value == "true" || value == "system"
                Switch(checked = fixedSwipe || available && checked, onCheckedChange = {
                    change(if (setting.id == "themeMode") { if (it) "system" else "manual" } else it.toString())
                }, enabled = available)
            }
            "number" -> {
                Text(label, style = MaterialTheme.typography.labelLarge)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val number = value.toDouble()
                    TextButton({ change(numberSettingValue(setting, number - setting.step)) }, enabled = available && number > setting.minimum) { Text("−") }
                    Text(java.text.NumberFormat.getNumberInstance().format(number))
                    TextButton({ change(numberSettingValue(setting, number + setting.step)) }, enabled = available && number < setting.maximum) { Text("+") }
                }
            }
            else -> {
                Text(label, style = MaterialTheme.typography.labelLarge)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    setting.options.forEach { option ->
                        val same = option.value == value || option.value.toDoubleOrNull()?.let { it == value.toDoubleOrNull() } == true
                        val optionEnabled = available && (setting.id != "letterSpacing" || option.value.toDouble() >= 0 || enabled(ReaderControl.NegativeLetterSpacing))
                        FilterChip(selected = same && optionEnabled, onClick = { change(option.value) }, label = { Text(if (chinese) option.chinese else option.english) }, enabled = optionEnabled)
                    }
                }
                if (setting.options.none { it.value == value || it.value.toDoubleOrNull()?.let { number -> number == value.toDoubleOrNull() } == true }) {
                    Text(stringResource(R.string.reader_setting_saved_value, value), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        if (fixedSwipe) Text(stringResource(R.string.reader_swipe_fixed), style = MaterialTheme.typography.bodySmall)
        if (!available && !fixedSwipe) {
            Text(stringResource(R.string.reader_setting_unavailable, label, value), style = MaterialTheme.typography.bodySmall)
        }
        if (setting.id == "letterSpacing" && !enabled(ReaderControl.NegativeLetterSpacing)) Text(stringResource(R.string.reader_negative_spacing_retained), style = MaterialTheme.typography.bodySmall)
        if (setting.id == "fontFamily") Text(stringResource(R.string.reader_font_mapping), style = MaterialTheme.typography.bodySmall)
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
        Column(Modifier.verticalScroll(scroll)) {
            if (navigationFailed) Text(stringResource(R.string.reader_navigation_failed), color = MaterialTheme.colorScheme.error)
            ChoiceRow(R.string.reader_notes, listOf("bookmarks", "annotations"), "bookmarks", {
                stringResource(if (it == "bookmarks") R.string.reader_bookmarks else R.string.reader_annotations)
            }, enabled = { it == "bookmarks" || capabilities.supportsAnnotations }) {}
            if (syncPending) Text(stringResource(R.string.reader_bookmarks_pending), color = MaterialTheme.colorScheme.primary)
            if (bookmarks.isEmpty()) {
                Text(stringResource(R.string.reader_bookmarks_empty), Modifier.padding(vertical = 24.dp))
            } else {
                bookmarks.forEach { bookmark ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        TextButton({ onJump(bookmark.id) }, Modifier.weight(1f)) {
                            Column(Modifier.fillMaxWidth()) {
                                Text(bookmark.label, maxLines = 1)
                                Text(
                                    stringResource(R.string.reader_progress_percent, bookmark.percent.toInt()),
                                    style = MaterialTheme.typography.labelSmall,
                                )
                            }
                        }
                        IconButton({ onRemove(bookmark.id) }) {
                            Icon(Icons.Default.Delete, stringResource(R.string.reader_bookmark_remove))
                        }
                    }
                    HorizontalDivider()
                }
            }
        }
    }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderContentsSheet(
    entries: List<ReaderTocEntry>,
    currentLocation: ReaderLocation?,
    pendingEntryId: String?,
    navigationFailed: Boolean,
    onDismiss: () -> Unit,
    onSelect: (ReaderTocEntry) -> Unit,
) = ReaderSheet(R.string.reader_contents_title, onDismiss) { scroll ->
    val flattened = remember(entries) { flattenContents(entries) }
    Column(Modifier.verticalScroll(scroll)) {
        if (navigationFailed) {
            Text(
                stringResource(R.string.reader_navigation_failed),
                Modifier.fillMaxWidth().padding(vertical = 8.dp),
                color = MaterialTheme.colorScheme.error,
            )
        }
        if (flattened.isEmpty()) Text(stringResource(R.string.reader_contents_empty), Modifier.padding(vertical = 24.dp))
        flattened.forEach { entry ->
            val entryLocation = entry.entry.location
            val selected = when {
                currentLocation is ReflowReaderLocation && entryLocation is ReflowReaderLocation ->
                    currentLocation.resourceKey == entryLocation.resourceKey
                currentLocation is ComicReaderLocation && entryLocation is ComicReaderLocation ->
                    currentLocation.resourceHref == entryLocation.resourceHref &&
                        currentLocation.pageIndex == entryLocation.pageIndex
                currentLocation is PdfReaderLocation && entryLocation is PdfReaderLocation ->
                    currentLocation.pageIndex == entryLocation.pageIndex
                else -> false
            }
            TextButton(
                { onSelect(entry.entry) },
                Modifier.fillMaxWidth().padding(start = (entry.depth * 16).dp),
                enabled = pendingEntryId == null,
            ) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(entry.entry.title, Modifier.weight(1f), color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                    if (pendingEntryId == entry.entry.id) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                }
            }
            HorizontalDivider()
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderSheet(
    title: Int,
    onDismiss: () -> Unit,
    snackbarHostState: SnackbarHostState? = null,
    content: @Composable (ScrollState) -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Box(Modifier.fillMaxWidth()) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(stringResource(title), Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
                    TextButton(onDismiss) { Text(stringResource(R.string.reader_done)) }
                }
                content(rememberScrollState())
                Spacer(Modifier.height(24.dp))
            }
            snackbarHostState?.let { hostState ->
                WarmPageSnackbarHost(
                    hostState = hostState,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                )
            }
        }
    }
}

@Composable
private fun <T> ChoiceRow(
    label: Int,
    values: List<T>,
    selected: T,
    optionLabel: @Composable (T) -> String,
    enabled: (T) -> Boolean = { true },
    onSelect: (T) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text(stringResource(label), style = MaterialTheme.typography.labelLarge)
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            values.forEach { value ->
                FilterChip(selected == value, { onSelect(value) }, { Text(optionLabel(value)) }, enabled = enabled(value))
            }
        }
    }
}

private data class FlatTocEntry(val entry: ReaderTocEntry, val depth: Int)
private fun flattenContents(entries: List<ReaderTocEntry>, depth: Int = 0): List<FlatTocEntry> = buildList {
    entries.forEach { add(FlatTocEntry(it, depth)); addAll(flattenContents(it.children, depth + 1)) }
}

private fun currentBookmark(bookmarks: List<ReaderBookmark>, location: ReaderLocation?): Boolean {
    val current = location as? ReflowReaderLocation ?: return false
    return bookmarks.any { bookmark ->
        bookmark.location.resourceKey == current.resourceKey &&
            kotlin.math.abs((bookmark.location.progression ?: 0.0) - (current.progression ?: 0.0)) < 0.0001
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
        ReaderErrorCode.OnlineLimit -> R.string.reader_download_reason
        ReaderErrorCode.LocationRestoreFailed -> R.string.reader_error_location
        ReaderErrorCode.NetworkUnavailable -> R.string.reader_error_network
        ReaderErrorCode.ReaderEngineError -> R.string.reader_error_generic
        ReaderErrorCode.RangeUnsupported -> R.string.reader_error_pdf_range_unsupported
        ReaderErrorCode.RangeInvalid -> R.string.reader_error_pdf_range_invalid
        ReaderErrorCode.PdfEngineLimit -> R.string.reader_error_pdf_engine_limit
        ReaderErrorCode.ResourceChanged -> R.string.reader_error_pdf_resource_changed
        ReaderErrorCode.CacheIo -> R.string.reader_error_pdf_cache
        ReaderErrorCode.Encrypted -> R.string.reader_error_pdf_encrypted
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
internal const val READER_SETTINGS_TEST_TAG = "reader-settings"
internal const val READER_PROGRESS_TEST_TAG = "reader-progress"
internal const val READER_LINE_HEIGHT_TEST_TAG = "reader-line-height"
