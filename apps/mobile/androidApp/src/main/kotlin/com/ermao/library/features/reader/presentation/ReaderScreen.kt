package com.ermao.library.features.reader.presentation

import android.view.ViewGroup
import android.view.WindowManager
import androidx.activity.compose.LocalActivity
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
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
import com.ermao.library.shared.modules.reader.ReaderControlProfile
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderFontFamily
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderNavigationResult
import com.ermao.library.shared.modules.reader.ReaderCommandResult
import com.ermao.library.shared.modules.reader.ReaderCommandRejected
import com.ermao.library.shared.modules.reader.ReaderNavigationCompleted
import com.ermao.library.shared.modules.reader.ReaderPageMargin
import com.ermao.library.shared.modules.reader.ReaderPageTurnAnimation
import com.ermao.library.shared.modules.reader.ReaderPdfCropMargins
import com.ermao.library.shared.modules.reader.ReaderPdfFit
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReaderProgressStyle
import com.ermao.library.shared.modules.reader.ReaderReadingMode
import com.ermao.library.shared.modules.reader.ReaderComicDirection
import com.ermao.library.shared.modules.reader.ReaderComicSpreadMode
import com.ermao.library.shared.modules.reader.ReaderSpreadMode
import com.ermao.library.shared.modules.reader.ReaderTapZones
import com.ermao.library.shared.modules.reader.ReaderTextAlignment
import com.ermao.library.shared.modules.reader.ReaderTheme
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

private enum class ReaderPanel { Contents, Notes, Appearance, Settings }

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
    onReadOnline: (() -> Unit)? = null,
    onDeleteDownload: (() -> Unit)? = null,
    onNavigatorContainerReady: () -> Unit,
) {
    val coroutineScope = rememberCoroutineScope()
    val navigationMutex = remember(controller) { Mutex() }
    val preferences by controller?.preferences?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf(ReaderPreferences()) }
    val currentLocation by controller?.currentLocation?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<ReaderLocation?>(null) }
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
    var pendingNavigationId by remember(controller) { mutableStateOf<String?>(null) }
    var navigationFailed by remember(controller) { mutableStateOf(false) }
    var preferencesApplyFailed by remember(controller) { mutableStateOf(false) }
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
                    onClose = onClose,
                    onPanel = {
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
                openError != null -> ReaderOpenError(
                    openError,
                    onClose,
                    onRetryOpen,
                    onReadOnline,
                    onDeleteDownload,
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
            ReaderPanel.Notes -> ReaderNotesSheet(
                capabilities = capabilities,
                bookmarks = bookmarks,
                syncPending = bookmarkSyncPending,
                onJump = { controller?.goToBookmark(it); panel = null },
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
            ReaderPanel.Appearance -> ReaderAppearanceSheet(
                preferences,
                capabilities,
                controller?.morphology ?: ReaderMorphology.Reflowable,
                onUpdate = { updated ->
                    controller?.let { activeController ->
                        coroutineScope.launch {
                            navigationMutex.withLock {
                                preferencesApplyFailed = false
                                preferencesApplyFailed = activeController.applyPreferences(updated) is ReaderCommandRejected
                            }
                        }
                    }
                },
                onDismiss = { panel = null },
            )
            ReaderPanel.Settings -> ReaderSettingsSheet(
                preferences,
                capabilities,
                controller?.morphology ?: ReaderMorphology.Reflowable,
                onUpdate = { updated ->
                    controller?.let { activeController ->
                        coroutineScope.launch {
                            navigationMutex.withLock {
                                preferencesApplyFailed = false
                                preferencesApplyFailed = activeController.applyPreferences(updated) is ReaderCommandRejected
                            }
                        }
                    }
                },
                onDismiss = { panel = null },
            )
            null -> Unit
        }
        if (preferencesApplyFailed) {
            Surface(color = MaterialTheme.colorScheme.errorContainer) {
                Text(
                    stringResource(R.string.reader_preferences_apply_failed),
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
                if (controller?.capabilities?.supportsBookmarks == true) {
                    val activeBookmark = currentBookmark(bookmarks, location)
                    IconButton(onClick = onToggleBookmark, enabled = location != null) {
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
                ReaderNavAction(Icons.AutoMirrored.Filled.MenuBook, R.string.reader_table_of_contents, READER_CONTENTS_TEST_TAG) { onPanel(ReaderPanel.Contents) }
                if (controller?.capabilities?.supportsBookmarks == true ||
                    controller?.capabilities?.supportsAnnotations == true
                ) {
                    ReaderNavAction(Icons.AutoMirrored.Filled.Notes, R.string.reader_notes, "reader-notes") { onPanel(ReaderPanel.Notes) }
                }
                if (controller?.capabilities?.supportsTheme == true) {
                    ReaderNavAction(Icons.Default.Palette, R.string.reader_appearance, "reader-appearance") { onPanel(ReaderPanel.Appearance) }
                }
                ReaderNavAction(Icons.Default.Settings, R.string.reader_settings, READER_SETTINGS_TEST_TAG) { onPanel(ReaderPanel.Settings) }
            }
        }
    }
}

@Composable
private fun RowScope.ReaderNavAction(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: Int,
    tag: String,
    onClick: () -> Unit,
) {
    TextButton(onClick, Modifier.weight(1f).testTag(tag)) {
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
private fun ReaderAppearanceSheet(
    preferences: ReaderPreferences,
    capabilities: ReaderCapabilities,
    morphology: ReaderMorphology,
    onUpdate: (ReaderPreferences) -> Unit,
    onDismiss: () -> Unit,
) = ReaderSheet(R.string.reader_appearance, onDismiss) { scroll ->
    val epub = preferences.epub
    Column(Modifier.verticalScroll(scroll)) {
        ChoiceRow(
            R.string.reader_theme,
            ReaderTheme.entries,
            preferences.appearance.theme,
            { themeLabel(it) },
        ) { onUpdate(preferences.copy(appearance = preferences.appearance.copy(theme = it, themeMode = ReaderThemeMode.Manual))) }
        ToggleRow(
            R.string.reader_theme_system,
            preferences.appearance.themeMode == ReaderThemeMode.System,
            capabilities.supportsSystemTheme,
        ) { onUpdate(preferences.copy(appearance = preferences.appearance.copy(themeMode = if (it) ReaderThemeMode.System else ReaderThemeMode.Manual))) }
        if (morphology == ReaderMorphology.Reflowable) {
        StepperRow(R.string.reader_font_size, "${epub.fontSize}px", epub.fontSize > 14, epub.fontSize < 30, {
            onUpdate(preferences.copy(epub = epub.copy(fontSize = epub.fontSize - 1)))
        }, {
            onUpdate(preferences.copy(epub = epub.copy(fontSize = epub.fontSize + 1)))
        })
        ChoiceRow(R.string.reader_line_height, listOf(1.6, 1.9, 2.2), epub.lineHeight, { lineHeightLabel(it) }) {
            onUpdate(preferences.copy(epub = epub.copy(lineHeight = it)))
        }
        ChoiceRow(
            R.string.reader_font_family,
            ReaderFontFamily.entries,
            epub.fontFamily,
            { fontLabel(it) },
            enabled = { capabilities.supportsFontFamily },
        ) {
            onUpdate(preferences.copy(epub = epub.copy(fontFamily = it)))
        }
        ChoiceRow(R.string.reader_font_weight, listOf(400, 500, 700), epub.fontWeight, { it.toString() }) {
            onUpdate(preferences.copy(epub = epub.copy(fontWeight = it)))
        }
        ChoiceRow(
            R.string.reader_letter_spacing,
            listOf(-0.02, 0.0, 0.04, 0.08),
            epub.letterSpacing,
            { letterSpacingLabel(it) },
            enabled = { it >= 0 || capabilities.supportsNegativeLetterSpacing },
        ) { onUpdate(preferences.copy(epub = epub.copy(letterSpacing = it))) }
        ChoiceRow(R.string.reader_page_margin, ReaderPageMargin.entries, epub.pageMargin, { marginLabel(it) }) {
            onUpdate(preferences.copy(epub = epub.copy(pageMargin = it)))
        }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderSettingsSheet(
    preferences: ReaderPreferences,
    capabilities: ReaderCapabilities,
    morphology: ReaderMorphology,
    onUpdate: (ReaderPreferences) -> Unit,
    onDismiss: () -> Unit,
) = ReaderSheet(R.string.reader_settings_title, onDismiss) { scroll ->
    Column(Modifier.verticalScroll(scroll)) {
        SettingsHeader(R.string.reader_interface)
        ChoiceRow(R.string.reader_progress_display, ReaderProgressStyle.entries, preferences.display.progressStyle, { progressStyleLabel(it) }) {
            onUpdate(preferences.copy(display = preferences.display.copy(progressStyle = it)))
        }
        ToggleRow(R.string.reader_show_clock, preferences.display.showClock, capabilities.supportsClock) {
            onUpdate(preferences.copy(display = preferences.display.copy(showClock = it)))
        }
        ToggleRow(R.string.reader_keep_awake, preferences.interaction.keepScreenAwake, capabilities.supportsKeepAwake) {
            onUpdate(preferences.copy(interaction = preferences.interaction.copy(keepScreenAwake = it)))
        }
        SettingsHeader(R.string.reader_page_turn_settings)
        val pageTurnAnimation = when (morphology) {
            ReaderMorphology.Reflowable -> preferences.epub.pageTurnAnimation
            ReaderMorphology.Comic -> preferences.comic.pageTurnAnimation
            ReaderMorphology.Pdf -> ReaderPageTurnAnimation.Slide
        }
        ChoiceRow(
            R.string.reader_page_turn_animation,
            ReaderPageTurnAnimation.entries,
            pageTurnAnimation,
            { pageTurnAnimationLabel(it) },
            enabled = { capabilities.supportsPageTurnAnimation },
        ) { selected ->
            val updated = when (morphology) {
                ReaderMorphology.Reflowable -> preferences.copy(epub = preferences.epub.copy(pageTurnAnimation = selected))
                ReaderMorphology.Comic -> preferences.copy(comic = preferences.comic.copy(pageTurnAnimation = selected))
                ReaderMorphology.Pdf -> preferences
            }
            onUpdate(updated)
        }
        ChoiceRow(R.string.reader_tap_zones, ReaderTapZones.entries, preferences.interaction.tapZones, { tapZoneLabel(it) }) {
            onUpdate(preferences.copy(interaction = preferences.interaction.copy(tapZones = it)))
        }
        ToggleRow(
            R.string.reader_swipe_page_turn,
            preferences.interaction.swipePageTurn,
            capabilities.supportsSwipeToggle,
        ) {
            onUpdate(preferences.copy(interaction = preferences.interaction.copy(swipePageTurn = it)))
        }
        ReaderMorphologyControls(morphology, capabilities, preferences, onUpdate)
        ToggleRow(R.string.reader_keyboard_page_turn, preferences.interaction.keyboardPageTurn, capabilities.supportsKeyboardPageTurn) {
            onUpdate(preferences.copy(interaction = preferences.interaction.copy(keyboardPageTurn = it)))
        }
        ToggleRow(R.string.reader_volume_page_turn, preferences.interaction.volumeKeyPageTurn, capabilities.supportsVolumeKeyPageTurn) {
            onUpdate(preferences.copy(interaction = preferences.interaction.copy(volumeKeyPageTurn = it)))
        }
        Button(onClick = { onUpdate(ReaderPreferences()) }, Modifier.fillMaxWidth().padding(vertical = 16.dp)) {
            Text(stringResource(R.string.reader_reset_defaults))
        }
    }
}

@Composable
private fun ReaderMorphologyControls(
    morphology: ReaderMorphology,
    capabilities: ReaderCapabilities,
    preferences: ReaderPreferences,
    onUpdate: (ReaderPreferences) -> Unit,
) {
    val profile = ReaderControlProfile.forMorphology(morphology)
    SettingsHeader(R.string.reader_layout)
    when (morphology) {
        ReaderMorphology.Reflowable -> {
            val epub = preferences.epub
            ChoiceRow(
                R.string.reader_reading_mode,
                profile.readingModes,
                epub.flow,
                { readingModeLabel(it) },
                enabled = { capabilities.supportsReadingMode && it !in profile.disabledReadingModes },
            ) { onUpdate(preferences.copy(epub = epub.copy(flow = it))) }
            ChoiceRow(
                R.string.reader_spread_mode,
                profile.reflowableSpreadModes,
                epub.spreadMode.takeUnless { it == ReaderSpreadMode.Auto } ?: ReaderSpreadMode.Single,
                { spreadLabel(it) },
                enabled = { capabilities.supportsSpreadMode },
            ) { onUpdate(preferences.copy(epub = epub.copy(spreadMode = it))) }
            SettingsHeader(R.string.reader_advanced_settings)
            ChoiceRow(R.string.reader_paragraph_indent, listOf(0.0, 1.0, 2.0, 3.0), epub.typography.paragraphIndent, { it.toInt().toString() }) {
                onUpdate(preferences.copy(epub = epub.copy(typography = epub.typography.copy(paragraphIndent = it))))
            }
            ChoiceRow(R.string.reader_paragraph_spacing, listOf(0.0, 0.4, 0.8, 1.2), epub.typography.paragraphSpacing, { it.toString() }) {
                onUpdate(preferences.copy(epub = epub.copy(typography = epub.typography.copy(paragraphSpacing = it))))
            }
            ChoiceRow(R.string.reader_text_alignment, ReaderTextAlignment.entries, epub.typography.textAlign, { alignmentLabel(it) }) {
                onUpdate(preferences.copy(epub = epub.copy(typography = epub.typography.copy(textAlign = it))))
            }
        }
        ReaderMorphology.Comic -> {
            val comic = preferences.comic
            val paginated = comic.flow == ReaderReadingMode.Paged
            ChoiceRow(
                R.string.reader_reading_mode,
                profile.readingModes,
                comic.flow,
                { readingModeLabel(it) },
                enabled = { capabilities.supportsReadingMode && it !in profile.disabledReadingModes },
            ) {
                onUpdate(preferences.copy(comic = comic.copy(flow = it)))
            }
            ChoiceRow(R.string.reader_spread_mode, profile.comicSpreadModes, comic.spreadMode, { comicSpreadLabel(it) }, enabled = { paginated && capabilities.supportsSpreadMode }) {
                onUpdate(preferences.copy(comic = comic.copy(spreadMode = it)))
            }
            ChoiceRow(R.string.reader_comic_direction, ReaderComicDirection.entries, comic.direction, { comicDirectionLabel(it) }, enabled = { paginated && capabilities.supportsComicDirection }) {
                onUpdate(preferences.copy(comic = comic.copy(direction = it)))
            }
            ToggleRow(R.string.reader_comic_cover_single, comic.coverSingle, paginated && comic.spreadMode == ReaderComicSpreadMode.Double && capabilities.supportsComicCoverSingle) {
                onUpdate(preferences.copy(comic = comic.copy(coverSingle = it)))
            }
            ChoiceRow(R.string.reader_page_gap, listOf(0, 8, 16, 24), comic.pageGap, { stringResource(R.string.reader_pixels, it) }, enabled = { paginated && capabilities.supportsComicPageGap }) {
                onUpdate(preferences.copy(comic = comic.copy(pageGap = it)))
            }
        }
        ReaderMorphology.Pdf -> {
            val pdf = preferences.pdf
            StepperRow(R.string.reader_pdf_zoom, "${(pdf.zoom * 100).roundToInt()}%", capabilities.supportsPdfZoomPreference && pdf.zoom > 0.6, capabilities.supportsPdfZoomPreference && pdf.zoom < 2.4, {
                onUpdate(preferences.copy(pdf = pdf.copy(zoom = (pdf.zoom - 0.1).coerceAtLeast(0.6))))
            }, {
                onUpdate(preferences.copy(pdf = pdf.copy(zoom = (pdf.zoom + 0.1).coerceAtMost(2.4))))
            })
            ChoiceRow(R.string.reader_pdf_fit, ReaderPdfFit.entries, pdf.fit, { pdfFitLabel(it) }, enabled = { capabilities.supportsPdfFit }) {
                onUpdate(preferences.copy(pdf = pdf.copy(fit = it)))
            }
            ChoiceRow(R.string.reader_pdf_rotation, listOf(0, 90, 180, 270), pdf.rotation, { stringResource(R.string.reader_degrees, it) }, enabled = { capabilities.supportsPdfRotation }) {
                onUpdate(preferences.copy(pdf = pdf.copy(rotation = it)))
            }
            ChoiceRow(R.string.reader_pdf_crop_margins, ReaderPdfCropMargins.entries, pdf.cropMargins, { pdfCropLabel(it) }, enabled = { capabilities.supportsPdfCropMargins }) {
                onUpdate(preferences.copy(pdf = pdf.copy(cropMargins = it)))
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderNotesSheet(
    capabilities: ReaderCapabilities,
    bookmarks: List<ReaderBookmark>,
    syncPending: Boolean,
    onJump: (String) -> Unit,
    onRemove: (String) -> Unit,
    snackbarHostState: SnackbarHostState,
    onDismiss: () -> Unit,
) =
    ReaderSheet(R.string.reader_notes, onDismiss, snackbarHostState) { scroll ->
        Column(Modifier.verticalScroll(scroll)) {
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
private fun SettingsHeader(label: Int) {
    Text(stringResource(label), Modifier.padding(top = 18.dp, bottom = 6.dp), style = MaterialTheme.typography.titleMedium)
    HorizontalDivider()
}

@Composable
private fun ToggleRow(label: Int, checked: Boolean, enabled: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(label), Modifier.weight(1f))
        Switch(checked, onChange, enabled = enabled)
    }
}

@Composable
private fun StepperRow(label: Int, value: String, canMinus: Boolean, canPlus: Boolean, minus: () -> Unit, plus: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(label), Modifier.weight(1f))
        TextButton(minus, enabled = canMinus) { Text("−") }
        Text(value, Modifier.padding(horizontal = 8.dp))
        TextButton(plus, enabled = canPlus) { Text("+") }
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

@Composable private fun themeLabel(value: ReaderTheme) = stringResource(when (value) {
    ReaderTheme.Day -> R.string.reader_theme_day
    ReaderTheme.Warm -> R.string.reader_theme_warm
    ReaderTheme.Green -> R.string.reader_theme_green
    ReaderTheme.Night -> R.string.reader_theme_night
    ReaderTheme.Black -> R.string.reader_theme_black
})
@Composable private fun fontLabel(value: ReaderFontFamily) = stringResource(when (value) {
    ReaderFontFamily.Pingfang -> R.string.reader_font_pingfang
    ReaderFontFamily.Heiti -> R.string.reader_font_heiti
    ReaderFontFamily.Songti -> R.string.reader_font_songti
    ReaderFontFamily.Yahei -> R.string.reader_font_yahei
    ReaderFontFamily.Kaiti -> R.string.reader_font_kaiti
})
@Composable private fun marginLabel(value: ReaderPageMargin) = stringResource(when (value) {
    ReaderPageMargin.Narrow -> R.string.reader_narrow
    ReaderPageMargin.Standard -> R.string.reader_standard
    ReaderPageMargin.Wide -> R.string.reader_wide
})
@Composable private fun progressStyleLabel(value: ReaderProgressStyle) = stringResource(when (value) {
    ReaderProgressStyle.Auto -> R.string.reader_auto
    ReaderProgressStyle.Percent -> R.string.reader_percent
    ReaderProgressStyle.Position -> R.string.reader_current_position
    ReaderProgressStyle.Remaining -> R.string.reader_remaining
    ReaderProgressStyle.Hidden -> R.string.reader_hidden
})
@Composable private fun tapZoneLabel(value: ReaderTapZones) = stringResource(when (value) {
    ReaderTapZones.Standard -> R.string.reader_standard
    ReaderTapZones.Reversed -> R.string.reader_reversed
    ReaderTapZones.Disabled -> R.string.reader_disabled
})
@Composable private fun pageTurnAnimationLabel(value: ReaderPageTurnAnimation) = stringResource(
    if (value == ReaderPageTurnAnimation.Slide) R.string.reader_animation_slide else R.string.reader_animation_off,
)
@Composable private fun readingModeLabel(value: ReaderReadingMode) = stringResource(if (value == ReaderReadingMode.Paged) R.string.reader_mode_paged else R.string.reader_mode_scroll)
@Composable private fun spreadLabel(value: ReaderSpreadMode) = stringResource(when (value) {
    ReaderSpreadMode.Auto -> R.string.reader_auto
    ReaderSpreadMode.Single -> R.string.reader_single_page
    ReaderSpreadMode.Double -> R.string.reader_double_page
})
@Composable private fun comicSpreadLabel(value: ReaderComicSpreadMode) = stringResource(
    if (value == ReaderComicSpreadMode.Single) R.string.reader_single_page else R.string.reader_double_page,
)
@Composable private fun comicDirectionLabel(value: ReaderComicDirection) = stringResource(
    if (value == ReaderComicDirection.LeftToRight) R.string.reader_left_to_right else R.string.reader_right_to_left,
)
@Composable private fun pdfFitLabel(value: ReaderPdfFit) = stringResource(
    if (value == ReaderPdfFit.Width) R.string.reader_fit_width else R.string.reader_fit_page,
)
@Composable private fun pdfCropLabel(value: ReaderPdfCropMargins) = stringResource(
    if (value == ReaderPdfCropMargins.Off) R.string.reader_crop_off else R.string.reader_crop_auto,
)
@Composable private fun alignmentLabel(value: ReaderTextAlignment) = stringResource(when (value) {
    ReaderTextAlignment.PublisherDefault -> R.string.reader_publisher_default
    ReaderTextAlignment.Start -> R.string.reader_left_align
    ReaderTextAlignment.Justify -> R.string.reader_justify
})
@Composable private fun lineHeightLabel(value: Double) = when (value) { 1.6 -> stringResource(R.string.reader_small); 1.9 -> stringResource(R.string.reader_medium); else -> stringResource(R.string.reader_large) }
@Composable private fun letterSpacingLabel(value: Double) = stringResource(when (value) { -0.02 -> R.string.reader_compact; 0.0 -> R.string.reader_standard; 0.04 -> R.string.reader_relaxed; else -> R.string.reader_wide })

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
    onReadOnline: (() -> Unit)?,
    onDeleteDownload: (() -> Unit)?,
) {
    val message = when (error.code) {
        ReaderErrorCode.UnsupportedFormat -> R.string.reader_error_unsupported
        ReaderErrorCode.CorruptFile -> R.string.reader_error_corrupt
        ReaderErrorCode.DrmProtected -> R.string.reader_error_drm
        ReaderErrorCode.ParseFailed -> R.string.reader_error_parse
        ReaderErrorCode.ResourceMissing -> R.string.reader_error_missing
        ReaderErrorCode.OutOfMemoryRisk -> R.string.reader_error_memory
        ReaderErrorCode.LocationRestoreFailed -> R.string.reader_error_location
        ReaderErrorCode.NetworkUnavailable, ReaderErrorCode.ReaderEngineError -> R.string.reader_error_generic
        ReaderErrorCode.RangeUnsupported -> R.string.reader_error_pdf_range_unsupported
        ReaderErrorCode.RangeInvalid -> R.string.reader_error_pdf_range_invalid
        ReaderErrorCode.ResourceChanged -> R.string.reader_error_pdf_resource_changed
        ReaderErrorCode.CacheIo -> R.string.reader_error_pdf_cache
        ReaderErrorCode.Encrypted -> R.string.reader_error_pdf_encrypted
        ReaderErrorCode.Invalid -> R.string.reader_error_pdf_invalid
        ReaderErrorCode.PageLoadFailed -> R.string.reader_error_pdf_page_load
        ReaderErrorCode.RenderFailed -> R.string.reader_error_pdf_render
        ReaderErrorCode.ComicArchiveOpenFailed,
        ReaderErrorCode.ComicArchiveEncrypted,
        ReaderErrorCode.ComicArchivePartMissing,
        ReaderErrorCode.ComicArchiveFormatUnsupported,
        ReaderErrorCode.ComicArchiveCorrupt,
        ReaderErrorCode.ComicPageDecodeFailed,
        ReaderErrorCode.ComicOutOfMemoryRisk,
        -> R.string.reader_error_comic_open
    }
    Surface(Modifier.align(Alignment.Center).padding(24.dp), shape = MaterialTheme.shapes.large) {
        Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.reader_error_title), style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(8.dp)); Text(stringResource(message)); Spacer(Modifier.height(20.dp))
            onRetryOpen?.let { retry ->
                Button(retry) { Text(stringResource(R.string.reader_retry_open)) }
            }
            onReadOnline?.let { readOnline ->
                Button(readOnline) { Text(stringResource(R.string.reader_read_online)) }
            }
            onDeleteDownload?.let { deleteDownload ->
                Button(deleteDownload) { Text(stringResource(R.string.reader_delete_download)) }
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
