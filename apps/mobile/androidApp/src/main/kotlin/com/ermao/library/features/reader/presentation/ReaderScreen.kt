package com.ermao.library.features.reader.presentation

import android.view.ViewGroup
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.FormatSize
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderReadingMode
import com.ermao.library.shared.modules.reader.ReaderTheme
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.ui.theme.ReaderWarmPageTheme
import com.ermao.library.ui.theme.WarmPageThemeValues

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ReaderScreen(
    title: String,
    controller: ReaderScreenController?,
    opening: Boolean,
    openError: ReaderError?,
    onClose: () -> Unit,
    onNavigatorContainerReady: () -> Unit,
) {
    val preferences by controller?.preferences?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf(ReaderPreferences()) }
    val currentLocation by controller?.currentLocation?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<ReaderLocation?>(null) }
    val restoreWarning by controller?.restoreWarning?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<ReaderError?>(null) }
    var showContents by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }

    ReaderWarmPageTheme(preferences.theme) {
        val colors = WarmPageThemeValues.colors
        Scaffold(
            modifier = Modifier.fillMaxSize(),
            containerColor = colors.canvas,
            topBar = {
                CenterAlignedTopAppBar(
                    title = {
                        Text(
                            text = title,
                            maxLines = 1,
                            style = MaterialTheme.typography.titleMedium,
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = onClose) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = stringResource(R.string.reader_close),
                            )
                        }
                    },
                )
            },
            bottomBar = {
                ReaderBottomControls(
                    controller = controller,
                    currentLocation = currentLocation,
                    onShowContents = { showContents = true },
                    onShowSettings = { showSettings = true },
                )
            },
        ) { padding ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .background(colors.canvas),
            ) {
                AndroidView(
                    modifier = Modifier
                        .fillMaxSize()
                        .testTag(READER_NAVIGATOR_TEST_TAG),
                    factory = { context ->
                        FragmentContainerView(context).apply {
                            id = READER_NAVIGATOR_CONTAINER_ID
                            layoutParams = ViewGroup.LayoutParams(
                                ViewGroup.LayoutParams.MATCH_PARENT,
                                ViewGroup.LayoutParams.MATCH_PARENT,
                            )
                            onNavigatorContainerReady()
                        }
                    },
                )

                if (controller != null) {
                    Box(
                        modifier = Modifier
                            .size(1.dp)
                            .alpha(0f)
                            .testTag(READER_READY_TEST_TAG),
                    )
                }

                if (restoreWarning?.code == ReaderErrorCode.LocationRestoreFailed) {
                    Surface(
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .fillMaxWidth()
                            .padding(16.dp),
                        color = colors.accentSoft,
                        shape = MaterialTheme.shapes.medium,
                    ) {
                        Text(
                            text = stringResource(R.string.reader_restore_warning),
                            modifier = Modifier.padding(12.dp),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }

                when {
                    openError != null -> ReaderOpenError(openError, onClose)
                    opening -> ReaderOpeningIndicator()
                }
            }
        }

        if (showContents) {
            ReaderContentsSheet(
                entries = controller?.tableOfContents.orEmpty(),
                onDismiss = { showContents = false },
                onSelect = { location ->
                    controller?.goTo(location)
                    showContents = false
                },
            )
        }

        if (showSettings) {
            ReaderSettingsSheet(
                preferences = preferences,
                onUpdate = { controller?.updatePreferences(it) },
                onDismiss = { showSettings = false },
            )
        }
    }
}

@Composable
private fun ReaderBottomControls(
    controller: ReaderScreenController?,
    currentLocation: ReaderLocation?,
    onShowContents: () -> Unit,
    onShowSettings: () -> Unit,
) {
    val colors = WarmPageThemeValues.colors
    val totalProgression = (currentLocation as? ReflowReaderLocation)?.totalProgression ?: 0.0
    val progressDescription = stringResource(R.string.reader_progress_slider)
    var sliderProgress by remember { mutableFloatStateOf(totalProgression.toFloat()) }
    var draggingSlider by remember { mutableStateOf(false) }
    LaunchedEffect(totalProgression, draggingSlider) {
        if (!draggingSlider) sliderProgress = totalProgression.toFloat()
    }

    Surface(color = colors.surface, tonalElevation = 2.dp) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Slider(
                    value = sliderProgress,
                    onValueChange = {
                        draggingSlider = true
                        sliderProgress = it
                    },
                    onValueChangeFinished = {
                        controller?.goToTotalProgression(sliderProgress.toDouble())
                        draggingSlider = false
                    },
                    modifier = Modifier
                        .weight(1f)
                        .semantics { contentDescription = progressDescription }
                        .testTag(READER_PROGRESS_TEST_TAG),
                    enabled = controller != null && currentLocation != null,
                )
                Text(
                    text = stringResource(R.string.reader_progress_percent, (sliderProgress * 100).toInt()),
                    modifier = Modifier.padding(start = 12.dp),
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                ReaderAction(
                    icon = Icons.Default.ChevronLeft,
                    label = stringResource(R.string.reader_previous),
                    enabled = controller != null,
                    testTag = READER_PREVIOUS_TEST_TAG,
                    onClick = { controller?.goPrevious() },
                )
                ReaderAction(
                    icon = Icons.AutoMirrored.Filled.MenuBook,
                    label = stringResource(R.string.reader_table_of_contents),
                    enabled = controller != null,
                    testTag = READER_CONTENTS_TEST_TAG,
                    onClick = onShowContents,
                )
                ReaderAction(
                    icon = Icons.Default.Settings,
                    label = stringResource(R.string.reader_settings),
                    enabled = controller != null,
                    testTag = READER_SETTINGS_TEST_TAG,
                    onClick = onShowSettings,
                )
                ReaderAction(
                    icon = Icons.Default.ChevronRight,
                    label = stringResource(R.string.reader_next),
                    enabled = controller != null,
                    testTag = READER_NEXT_TEST_TAG,
                    onClick = { controller?.goNext() },
                )
            }
        }
    }
}

@Composable
private fun ReaderAction(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    enabled: Boolean,
    testTag: String,
    onClick: () -> Unit,
) {
    TextButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.testTag(testTag),
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(imageVector = icon, contentDescription = null)
            Text(text = label, style = MaterialTheme.typography.labelSmall)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderSettingsSheet(
    preferences: ReaderPreferences,
    onUpdate: (ReaderPreferences) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 8.dp),
        ) {
            Text(stringResource(R.string.reader_settings_title), style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(20.dp))
            Text(stringResource(R.string.reader_font_size), style = MaterialTheme.typography.titleMedium)
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(
                    onClick = { onUpdate(preferences.copy(fontSize = (preferences.fontSize - 0.1).coerceAtLeast(0.5))) },
                ) {
                    Icon(Icons.Default.Remove, stringResource(R.string.reader_decrease_font_size))
                }
                Icon(Icons.Default.FormatSize, contentDescription = null)
                Text(
                    text = stringResource(
                        R.string.reader_progress_percent,
                        (preferences.fontSize * 100).toInt(),
                    ),
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
                IconButton(
                    onClick = { onUpdate(preferences.copy(fontSize = (preferences.fontSize + 0.1).coerceAtMost(3.0))) },
                ) {
                    Icon(Icons.Default.Add, stringResource(R.string.reader_increase_font_size))
                }
            }
            Spacer(Modifier.height(12.dp))
            Text(stringResource(R.string.reader_line_height), style = MaterialTheme.typography.titleMedium)
            Slider(
                value = preferences.lineHeight.toFloat(),
                onValueChange = { onUpdate(preferences.copy(lineHeight = it.toDouble())) },
                valueRange = 0.8f..3.0f,
                modifier = Modifier.testTag(READER_LINE_HEIGHT_TEST_TAG),
            )
            Spacer(Modifier.height(12.dp))
            Text(stringResource(R.string.reader_theme), style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ThemeChip(ReaderTheme.Paper, preferences, onUpdate, R.string.reader_theme_paper)
                ThemeChip(ReaderTheme.Night, preferences, onUpdate, R.string.reader_theme_night)
                ThemeChip(ReaderTheme.System, preferences, onUpdate, R.string.reader_theme_system)
            }
            Spacer(Modifier.height(12.dp))
            Text(stringResource(R.string.reader_reading_mode), style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ReadingModeChip(
                    mode = ReaderReadingMode.Paged,
                    preferences = preferences,
                    onUpdate = onUpdate,
                    label = R.string.reader_mode_paged,
                )
                ReadingModeChip(
                    mode = ReaderReadingMode.ContinuousScroll,
                    preferences = preferences,
                    onUpdate = onUpdate,
                    label = R.string.reader_mode_scroll,
                )
            }
            Spacer(Modifier.height(12.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(stringResource(R.string.reader_publisher_styles), style = MaterialTheme.typography.bodyLarge)
                Switch(
                    checked = preferences.publisherStyles,
                    onCheckedChange = { onUpdate(preferences.copy(publisherStyles = it)) },
                )
            }
            Spacer(Modifier.height(20.dp))
            Button(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.reader_done))
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun ThemeChip(
    theme: ReaderTheme,
    preferences: ReaderPreferences,
    onUpdate: (ReaderPreferences) -> Unit,
    label: Int,
) {
    FilterChip(
        selected = preferences.theme == theme,
        onClick = { onUpdate(preferences.copy(theme = theme)) },
        label = { Text(stringResource(label)) },
    )
}

@Composable
private fun ReadingModeChip(
    mode: ReaderReadingMode,
    preferences: ReaderPreferences,
    onUpdate: (ReaderPreferences) -> Unit,
    label: Int,
) {
    FilterChip(
        selected = preferences.readingMode == mode,
        onClick = { onUpdate(preferences.copy(readingMode = mode)) },
        label = { Text(stringResource(label)) },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderContentsSheet(
    entries: List<ReaderTocEntry>,
    onDismiss: () -> Unit,
    onSelect: (ReaderLocation) -> Unit,
) {
    val flattened = remember(entries) { flattenContents(entries) }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 8.dp),
        ) {
            Text(stringResource(R.string.reader_contents_title), style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(16.dp))
            if (flattened.isEmpty()) {
                Text(stringResource(R.string.reader_contents_empty), style = MaterialTheme.typography.bodyLarge)
            } else {
                flattened.forEach { entry ->
                    TextButton(
                        onClick = { onSelect(entry.entry.location) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(start = (entry.depth * 16).dp),
                    ) {
                        Text(
                            text = entry.entry.title,
                            modifier = Modifier.fillMaxWidth(),
                            style = MaterialTheme.typography.bodyLarge,
                        )
                    }
                    HorizontalDivider()
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

private data class FlatTocEntry(val entry: ReaderTocEntry, val depth: Int)

private fun flattenContents(entries: List<ReaderTocEntry>, depth: Int = 0): List<FlatTocEntry> = buildList {
    entries.forEach { entry ->
        add(FlatTocEntry(entry, depth))
        addAll(flattenContents(entry.children, depth + 1))
    }
}

@Composable
private fun BoxScope.ReaderOpeningIndicator() {
    Surface(
        modifier = Modifier
            .align(Alignment.Center)
            .padding(32.dp),
        shape = MaterialTheme.shapes.large,
        tonalElevation = 3.dp,
    ) {
        Row(
            modifier = Modifier.padding(24.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            CircularProgressIndicator(modifier = Modifier.size(28.dp))
            Text(stringResource(R.string.reader_loading))
        }
    }
}

@Composable
private fun BoxScope.ReaderOpenError(error: ReaderError, onClose: () -> Unit) {
    val message = when (error.code) {
        ReaderErrorCode.UnsupportedFormat -> R.string.reader_error_unsupported
        ReaderErrorCode.CorruptFile -> R.string.reader_error_corrupt
        ReaderErrorCode.DrmProtected -> R.string.reader_error_drm
        ReaderErrorCode.ParseFailed -> R.string.reader_error_parse
        ReaderErrorCode.ResourceMissing -> R.string.reader_error_missing
        ReaderErrorCode.OutOfMemoryRisk -> R.string.reader_error_memory
        ReaderErrorCode.LocationRestoreFailed -> R.string.reader_error_location
        ReaderErrorCode.NetworkUnavailable,
        ReaderErrorCode.ReaderEngineError,
        -> R.string.reader_error_generic
    }
    Surface(
        modifier = Modifier
            .align(Alignment.Center)
            .padding(24.dp),
        shape = MaterialTheme.shapes.large,
        tonalElevation = 3.dp,
    ) {
        Column(
            modifier = Modifier.padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(stringResource(R.string.reader_error_title), style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(8.dp))
            Text(stringResource(message), style = MaterialTheme.typography.bodyLarge)
            Spacer(Modifier.height(20.dp))
            Button(onClick = onClose) { Text(stringResource(R.string.reader_close)) }
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
