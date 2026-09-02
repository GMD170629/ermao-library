package com.ermao.library.features.audio.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Forward30
import androidx.compose.material.icons.filled.FormatListBulleted
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.audio.application.AndroidAudioPlaybackRuntime
import com.ermao.library.features.audio.model.AndroidAudioPhase
import com.ermao.library.features.audio.model.AndroidAudioPlaybackSnapshot
import com.ermao.library.features.audio.model.AndroidAudioTrack
import com.ermao.library.features.audio.model.SUPPORTED_PLAYBACK_RATES
import com.ermao.library.ui.theme.WarmPageThemeValues
import java.text.NumberFormat
import java.util.Locale
import kotlin.math.roundToLong
import kotlinx.coroutines.flow.distinctUntilChanged

/**
 * App-owned mini player content. Navigation and modal presentation remain platform-owned by the
 * caller; this composable only describes the semantic media task and its state.
 */
@Composable
fun AudioMiniPlayer(
    snapshot: AndroidAudioPlaybackSnapshot,
    onOpen: () -> Unit,
    onPlayPause: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (!snapshot.hasSession || snapshot.phase == AndroidAudioPhase.Idle) return
    val theme = WarmPageThemeValues
    val title = snapshot.title ?: stringResource(R.string.audio_unknown_title)
    val chapter = snapshot.chapterTitle ?: stringResource(R.string.audio_no_chapter)
    val status = audioStatusLabel(snapshot.phase)
    val progressLabel = stringResource(R.string.audio_progress)
    val playPauseLabel = if (snapshot.phase == AndroidAudioPhase.Playing) {
        stringResource(R.string.audio_pause)
    } else {
        stringResource(R.string.audio_play)
    }
    val playPauseEnabled = snapshot.phase !in setOf(
        AndroidAudioPhase.Loading,
        AndroidAudioPhase.Error,
    )
    Surface(
        color = theme.colors.surface,
        modifier = modifier
            .fillMaxWidth()
            .semantics { stateDescription = status },
    ) {
        Column {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 72.dp)
                    .clickable(role = Role.Button, onClick = onOpen)
                    .padding(horizontal = theme.spacing.two),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                AudioArtwork(
                    title = title,
                    modifier = Modifier.size(48.dp),
                    iconSize = 24.dp,
                )
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
                ) {
                    Text(
                        text = title,
                        style = theme.typography.headline,
                        color = theme.colors.textPrimary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = chapter,
                        style = theme.typography.caption,
                        color = theme.colors.textSecondary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                IconButton(
                    onClick = onPlayPause,
                    enabled = playPauseEnabled,
                    modifier = Modifier
                        .size(theme.components.controls.minimumTouchTarget)
                        .semantics { contentDescription = "$playPauseLabel · $title" },
                ) {
                    Icon(
                        imageVector = if (snapshot.phase == AndroidAudioPhase.Playing) {
                            Icons.Filled.Pause
                        } else {
                            Icons.Filled.PlayArrow
                        },
                        contentDescription = null,
                        tint = if (playPauseEnabled) {
                            theme.colors.textPrimary
                        } else {
                            theme.colors.textTertiary
                        },
                    )
                }
            }
            LinearProgressIndicator(
                progress = { snapshot.progress },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(2.dp)
                    .semantics {
                        progressBarRangeInfo = ProgressBarRangeInfo(snapshot.progress, 0f..1f)
                        contentDescription = progressLabel
                    },
                color = theme.colors.brandAccent,
                trackColor = theme.colors.divider,
            )
        }
    }
}

/** Full-screen Now Playing content; the Dialog shell is deliberately kept in [AudioNowPlayingDialog]. */
@OptIn(ExperimentalMaterial3Api::class)
// The pinned Compose icons artifact predates AutoMirrored; these two directional-looking
// content icons are not mirrored by the player, so keep the available stable vectors locally.
@Suppress("DEPRECATION")
@Composable
fun AudioNowPlayingScreen(
    snapshot: AndroidAudioPlaybackSnapshot,
    runtime: AndroidAudioPlaybackRuntime,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    var speedMenuVisible by remember { mutableStateOf(false) }
    var queueVisible by remember { mutableStateOf(false) }
    val title = snapshot.title ?: stringResource(R.string.audio_unknown_title)
    val chapter = snapshot.chapterTitle ?: stringResource(R.string.audio_no_chapter)
    val author = snapshot.author?.takeIf(String::isNotBlank)
    val duration = snapshot.durationMillis
    val current = snapshot.positionMillis.coerceAtMost(duration.takeIf { it > 0 } ?: Long.MAX_VALUE)
    val status = audioStatusLabel(snapshot.phase)
    val retryLabel = stringResource(R.string.audio_retry)
    val scrubberLabel = stringResource(R.string.audio_scrubber)
    val playPauseLabel = if (snapshot.phase == AndroidAudioPhase.Playing) {
        stringResource(R.string.audio_pause)
    } else {
        stringResource(R.string.audio_play)
    }
    val controlsEnabled = snapshot.hasSession && snapshot.phase !in setOf(
        AndroidAudioPhase.Idle,
        AndroidAudioPhase.Loading,
        AndroidAudioPhase.Buffering,
        AndroidAudioPhase.Error,
    )
    val chaptersEnabled = controlsEnabled && runtime.currentTracks().isNotEmpty()
    val speedEnabled = controlsEnabled

    Scaffold(
        modifier = modifier.semantics { stateDescription = status },
        containerColor = theme.colors.surfaceRaised,
        contentColor = theme.colors.textPrimary,
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Text(
                        text = stringResource(R.string.audio_now_playing),
                        style = theme.typography.headline,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(
                        onClick = onClose,
                        modifier = Modifier.size(theme.components.controls.minimumTouchTarget),
                    ) {
                        Icon(
                            imageVector = Icons.Filled.ExpandMore,
                            contentDescription = stringResource(R.string.audio_collapse),
                            tint = theme.colors.textPrimary,
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = theme.colors.surfaceRaised,
                    scrolledContainerColor = theme.colors.surfaceRaised,
                    titleContentColor = theme.colors.textPrimary,
                    navigationIconContentColor = theme.colors.textPrimary,
                    actionIconContentColor = theme.colors.textPrimary,
                ),
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            contentPadding = PaddingValues(
                horizontal = theme.spacing.two,
                vertical = theme.spacing.one,
            ),
            verticalArrangement = Arrangement.SpaceBetween,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            item(key = "audio-header") {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    // Keep this slot square regardless of the source ratio. An authenticated
                    // artwork bitmap can be passed to AudioArtwork in a future media adapter and
                    // is always Fit.
                    AudioArtwork(
                        title = title,
                        modifier = Modifier
                            .widthIn(min = 180.dp, max = 260.dp)
                            .fillMaxWidth()
                            .aspectRatio(1f),
                        iconSize = 48.dp,
                    )
                    Spacer(Modifier.height(theme.spacing.three))
                    Text(
                        text = title,
                        style = theme.typography.title,
                        color = theme.colors.textPrimary,
                        modifier = Modifier.fillMaxWidth(),
                        textAlign = TextAlign.Center,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (author != null) {
                        Text(
                            text = author,
                            style = theme.typography.body,
                            color = theme.colors.textSecondary,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = theme.spacing.half),
                            textAlign = TextAlign.Center,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Text(
                        text = chapter,
                        style = theme.typography.callout,
                        color = theme.colors.textSecondary,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = theme.spacing.one),
                        textAlign = TextAlign.Center,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            item(key = "audio-controls") {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    val sliderFraction = if (duration > 0) {
                        (current.toFloat() / duration.toFloat()).coerceIn(0f, 1f)
                    } else {
                        0f
                    }
                    val sliderPosition = if (duration > 0) {
                        (sliderFraction * duration).roundToLong()
                    } else {
                        current
                    }
                    if (duration > 0) {
                        Slider(
                            value = sliderFraction,
                            onValueChange = { fraction ->
                                if (controlsEnabled) {
                                    runtime.beginScrubbing()
                                    runtime.updateScrubbing((fraction * duration).roundToLong())
                                }
                            },
                            onValueChangeFinished = {
                                runtime.finishScrubbing()
                            },
                            enabled = controlsEnabled,
                            modifier = Modifier
                                .fillMaxWidth()
                                .heightIn(min = theme.components.controls.minimumTouchTarget)
                                .semantics {
                                    contentDescription = scrubberLabel
                                    stateDescription = formatPlaybackTime(sliderPosition, duration)
                                },
                            colors = SliderDefaults.colors(
                                thumbColor = theme.colors.brandAccent,
                                activeTrackColor = theme.colors.brandAccent,
                                inactiveTrackColor = theme.colors.divider,
                                disabledThumbColor = theme.colors.textTertiary.copy(alpha = 0.38f),
                                disabledActiveTrackColor = theme.colors.divider,
                                disabledInactiveTrackColor = theme.colors.divider.copy(alpha = 0.58f),
                            ),
                        )
                    } else {
                        LinearProgressIndicator(
                            progress = { 0f },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(4.dp)
                                .semantics { contentDescription = scrubberLabel },
                            color = theme.colors.brandAccent.copy(alpha = if (controlsEnabled) 1f else 0.38f),
                            trackColor = theme.colors.divider,
                        )
                    }
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = theme.spacing.half),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            text = formatMillis(sliderPosition),
                            style = theme.typography.caption,
                            color = theme.colors.textSecondary,
                        )
                        Text(
                            text = formatMillis(duration),
                            style = theme.typography.caption,
                            color = theme.colors.textSecondary,
                        )
                    }
                    AudioPlaybackFeedback(
                        phase = snapshot.phase,
                        retryLabel = retryLabel,
                        onRetry = runtime::retry,
                    )
                    Spacer(Modifier.height(theme.spacing.one))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceEvenly,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        AudioIconButton(
                            icon = Icons.Filled.SkipPrevious,
                            label = stringResource(R.string.audio_previous),
                            onClick = runtime::previous,
                            enabled = controlsEnabled,
                        )
                        AudioSkipButton(
                            icon = Icons.Filled.Replay,
                            seconds = "15",
                            label = stringResource(R.string.audio_back_15),
                            onClick = runtime::skipBack,
                            enabled = controlsEnabled,
                        )
                        val isLoading = snapshot.phase == AndroidAudioPhase.Loading ||
                            snapshot.phase == AndroidAudioPhase.Buffering
                        AudioPlaybackButton(
                            label = if (isLoading) status else playPauseLabel,
                            enabled = controlsEnabled,
                            isPlaying = snapshot.phase == AndroidAudioPhase.Playing,
                            isLoading = isLoading,
                            onClick = {
                                if (snapshot.phase == AndroidAudioPhase.Playing) runtime.pause() else runtime.play()
                            },
                        )
                        AudioIconButton(
                            icon = Icons.Filled.Forward30,
                            label = stringResource(R.string.audio_forward_30),
                            onClick = runtime::skipForward,
                            enabled = controlsEnabled,
                        )
                        AudioIconButton(
                            icon = Icons.Filled.SkipNext,
                            label = stringResource(R.string.audio_next),
                            onClick = runtime::next,
                            enabled = controlsEnabled,
                        )
                    }
                    Spacer(Modifier.height(theme.spacing.two))
                    HorizontalDivider(color = theme.colors.divider)
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = theme.spacing.one),
                        horizontalArrangement = Arrangement.spacedBy(theme.spacing.half),
                    ) {
                        Box(modifier = Modifier.weight(1f)) {
                            AudioToolButton(
                                label = stringResource(R.string.audio_speed),
                                contentDescription = stringResource(R.string.audio_speed),
                                enabled = speedEnabled,
                                onClick = { speedMenuVisible = true },
                                modifier = Modifier.fillMaxWidth(),
                                content = { tint ->
                                    Text(
                                        text = stringResource(
                                            R.string.audio_speed_value,
                                            formatPlaybackRate(snapshot.playbackRate),
                                        ),
                                        style = theme.typography.headline.copy(fontWeight = FontWeight.Medium),
                                        color = tint,
                                    )
                                },
                            )
                            DropdownMenu(
                                expanded = speedMenuVisible,
                                onDismissRequest = { speedMenuVisible = false },
                            ) {
                                SUPPORTED_PLAYBACK_RATES.forEach { rate ->
                                    DropdownMenuItem(
                                        text = {
                                            Text(
                                                text = stringResource(
                                                    R.string.audio_speed_value,
                                                    formatPlaybackRate(rate),
                                                ),
                                                color = theme.colors.textPrimary,
                                            )
                                        },
                                        onClick = {
                                            speedMenuVisible = false
                                            if (speedEnabled) runtime.setPlaybackRate(rate)
                                        },
                                    )
                                }
                            }
                        }
                        AudioToolButton(
                            label = stringResource(R.string.audio_chapters),
                            contentDescription = stringResource(R.string.audio_chapters),
                            enabled = chaptersEnabled,
                            onClick = { queueVisible = true },
                            modifier = Modifier.weight(1f),
                            content = { tint ->
                                Icon(
                                    imageVector = Icons.Filled.FormatListBulleted,
                                    contentDescription = null,
                                    tint = tint,
                                    modifier = Modifier.size(28.dp),
                                )
                            },
                        )
                        AudioToolButton(
                            label = stringResource(R.string.audio_sleep_timer),
                            contentDescription = stringResource(R.string.audio_sleep_unavailable),
                            enabled = false,
                            onClick = {},
                            modifier = Modifier.weight(1f),
                            content = { tint ->
                                Icon(
                                    imageVector = Icons.Filled.Timer,
                                    contentDescription = null,
                                    tint = tint,
                                    modifier = Modifier.size(28.dp),
                                )
                            },
                        )
                        AudioToolButton(
                            label = stringResource(R.string.audio_work),
                            contentDescription = stringResource(R.string.audio_work),
                            enabled = controlsEnabled,
                            onClick = onClose,
                            modifier = Modifier.weight(1f),
                            content = { tint ->
                                Icon(
                                    imageVector = Icons.Filled.MenuBook,
                                    contentDescription = null,
                                    tint = tint,
                                    modifier = Modifier.size(28.dp),
                                )
                            },
                        )
                    }
                }
            }
        }
    }
    if (queueVisible) {
        AudioQueueSheet(
            snapshot = snapshot,
            intentTracks = runtime.currentTracks(),
            onSelectAsset = { assetId ->
                queueVisible = false
                runtime.selectAsset(assetId)
            },
            onSelectChapter = { assetId, chapterId ->
                queueVisible = false
                runtime.selectChapter(assetId, chapterId)
            },
            onDismiss = { queueVisible = false },
        )
    }
}

@Composable
private fun AudioPlaybackFeedback(
    phase: AndroidAudioPhase,
    retryLabel: String,
    onRetry: () -> Unit,
) {
    if (phase != AndroidAudioPhase.Error) return
    val theme = WarmPageThemeValues
    val statusLabel = audioStatusLabel(phase)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 40.dp)
            .semantics { stateDescription = statusLabel },
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = statusLabel,
            style = theme.typography.caption,
            color = theme.colors.textSecondary,
        )
        Spacer(Modifier.size(theme.spacing.one))
        TextButton(
            onClick = onRetry,
            modifier = Modifier.semantics { contentDescription = retryLabel },
            colors = ButtonDefaults.textButtonColors(contentColor = theme.colors.textPrimary),
        ) {
            Text(retryLabel)
        }
    }
}

@Composable
private fun AudioPlaybackButton(
    label: String,
    enabled: Boolean,
    isPlaying: Boolean,
    isLoading: Boolean,
    onClick: () -> Unit,
) {
    val theme = WarmPageThemeValues
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier
            .size(64.dp)
            .clip(CircleShape)
            .background(
                when {
                    isLoading -> theme.colors.brandAccent
                    enabled -> theme.colors.brandAccent
                    else -> theme.colors.brandAccent.copy(alpha = 0.32f)
                },
            )
            .semantics {
                contentDescription = label
                if (!enabled) disabled()
            },
    ) {
        if (isLoading) {
            CircularProgressIndicator(
                modifier = Modifier.size(28.dp),
                color = theme.colors.onAction,
                strokeWidth = 3.dp,
            )
        } else {
            Icon(
                imageVector = if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                contentDescription = null,
                tint = if (enabled) theme.colors.onAction else theme.colors.onAction.copy(alpha = 0.62f),
                modifier = Modifier.size(30.dp),
            )
        }
    }
}

@Composable
private fun AudioIconButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    onClick: () -> Unit,
    enabled: Boolean,
) {
    val theme = WarmPageThemeValues
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier
            .size(theme.components.controls.minimumTouchTarget)
            .semantics {
                contentDescription = label
                if (!enabled) disabled()
            },
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (enabled) theme.colors.textPrimary else theme.colors.textTertiary,
            modifier = Modifier.size(32.dp),
        )
    }
}

@Composable
private fun AudioSkipButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    seconds: String,
    label: String,
    onClick: () -> Unit,
    enabled: Boolean,
) {
    val theme = WarmPageThemeValues
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier
            .size(theme.components.controls.minimumTouchTarget)
            .semantics {
                contentDescription = label
                if (!enabled) disabled()
            },
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = if (enabled) theme.colors.textPrimary else theme.colors.textTertiary,
                modifier = Modifier.size(34.dp),
            )
            Text(
                text = seconds,
                style = theme.typography.caption.copy(fontWeight = FontWeight.Bold),
                color = if (enabled) theme.colors.textPrimary else theme.colors.textTertiary,
            )
        }
    }
}

@Composable
private fun AudioToolButton(
    label: String,
    contentDescription: String,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable (tint: androidx.compose.ui.graphics.Color) -> Unit,
) {
    val theme = WarmPageThemeValues
    val tint = if (enabled) theme.colors.textPrimary else theme.colors.textTertiary
    TextButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier
            .heightIn(min = 80.dp)
            .semantics {
                this.contentDescription = contentDescription
                if (!enabled) disabled()
            },
        contentPadding = androidx.compose.foundation.layout.PaddingValues(
            horizontal = theme.spacing.half,
            vertical = theme.spacing.one,
        ),
        colors = ButtonDefaults.textButtonColors(
            contentColor = theme.colors.textPrimary,
            disabledContentColor = theme.colors.textTertiary,
        ),
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
        ) {
            content(tint)
            Text(
                text = label,
                style = theme.typography.caption,
                color = tint,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
fun AudioNowPlayingDialog(
    visible: Boolean,
    snapshot: AndroidAudioPlaybackSnapshot,
    runtime: AndroidAudioPlaybackRuntime,
    onDismiss: () -> Unit,
) {
    if (!visible) return
    val dismissPlayer = {
        runtime.cancelScrubbing()
        onDismiss()
    }
    Dialog(
        onDismissRequest = dismissPlayer,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.safeDrawing),
            color = WarmPageThemeValues.colors.surfaceRaised,
        ) {
            BackHandler(onBack = dismissPlayer)
            AudioNowPlayingScreen(snapshot = snapshot, runtime = runtime, onClose = dismissPlayer)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AudioQueueSheet(
    snapshot: AndroidAudioPlaybackSnapshot,
    intentTracks: List<AndroidAudioTrack>,
    onSelectAsset: (String) -> Unit,
    onSelectChapter: (assetId: String, chapterId: String) -> Unit,
    onDismiss: () -> Unit,
) {
    val theme = WarmPageThemeValues
    val currentTrackLabel = stringResource(R.string.audio_track_current)
    val currentChapterLabel = stringResource(R.string.audio_chapter_current)
    val entries = remember(intentTracks) {
        intentTracks.flatMap { track ->
            if (track.chapters.isNotEmpty()) {
                track.chapters.map { chapter ->
                    AudioQueueEntry(
                        key = "chapter:${track.assetId}:${chapter.id}",
                        assetId = track.assetId,
                        chapterId = chapter.id,
                        title = chapter.title,
                        supportingText = "${track.title} · ${formatMillis(chapter.startMillis)}",
                    )
                }
            } else {
                listOf(
                    AudioQueueEntry(
                        key = "track:${track.assetId}",
                        assetId = track.assetId,
                        chapterId = null,
                        title = track.title,
                        supportingText = formatMillis(track.durationMillis ?: 0),
                    ),
                )
            }
        }
    }
    val exactCurrentEntryIndex = entries.indexOfFirst { entry ->
        entry.assetId == snapshot.assetId &&
            (
                entry.chapterId == snapshot.chapterId ||
                    (entry.chapterId == null && snapshot.chapterId == null)
                )
    }
    val currentEntryIndex = exactCurrentEntryIndex.takeIf { it >= 0 }
        ?: entries.indexOfFirst { it.assetId == snapshot.assetId }
    val anchorIndex = currentEntryIndex.coerceAtLeast(0)
    var windowStart by remember(entries, currentEntryIndex) {
        mutableIntStateOf((anchorIndex - AUDIO_QUEUE_PAGE_SIZE).coerceAtLeast(0))
    }
    var windowEndExclusive by remember(entries, currentEntryIndex) {
        mutableIntStateOf((anchorIndex + AUDIO_QUEUE_PAGE_SIZE + 1).coerceAtMost(entries.size))
    }
    val listState = rememberLazyListState()
    val safeWindowStart = windowStart.coerceIn(0, entries.size)
    val safeWindowEnd = windowEndExclusive.coerceIn(safeWindowStart, entries.size)
    val visibleEntries = entries.subList(safeWindowStart, safeWindowEnd)

    LaunchedEffect(entries, currentEntryIndex) {
        val start = (anchorIndex - AUDIO_QUEUE_PAGE_SIZE).coerceAtLeast(0)
        val end = (anchorIndex + AUDIO_QUEUE_PAGE_SIZE + 1).coerceAtMost(entries.size)
        windowStart = start
        windowEndExclusive = end
        if (entries.isNotEmpty()) {
            listState.scrollToItem((anchorIndex - start).coerceIn(0, end - start - 1))
        }
    }
    LaunchedEffect(listState, entries, safeWindowStart, safeWindowEnd) {
        snapshotFlow {
            val visibleItems = listState.layoutInfo.visibleItemsInfo
            (visibleItems.firstOrNull()?.index == 0) to
                (visibleItems.lastOrNull()?.index == visibleEntries.lastIndex)
        }
            .distinctUntilChanged()
            .collect { (atTop, atBottom) ->
                if (atTop && safeWindowStart > 0) {
                    val added = minOf(AUDIO_QUEUE_PAGE_SIZE, safeWindowStart)
                    windowStart = safeWindowStart - added
                    // Keep the same item under the user's finger after prepending a page.
                    listState.scrollToItem(added)
                } else if (atBottom && safeWindowEnd < entries.size) {
                    windowEndExclusive = minOf(
                        entries.size,
                        safeWindowEnd + AUDIO_QUEUE_PAGE_SIZE,
                    )
                }
            }
    }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Text(
            text = stringResource(R.string.audio_queue_title),
            style = theme.typography.sectionTitle,
            color = theme.colors.textPrimary,
            modifier = Modifier.padding(horizontal = theme.spacing.two, vertical = theme.spacing.one),
        )
        LazyColumn(
            state = listState,
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPaddingCompat(),
        ) {
            items(visibleEntries, key = { entry -> entry.key }) { entry ->
                val isCurrent = entry.key == entries.getOrNull(currentEntryIndex)?.key
                val supportingText = when {
                    entry.chapterId != null && isCurrent ->
                        "${entry.supportingText} · $currentChapterLabel"
                    entry.chapterId == null && isCurrent -> currentTrackLabel
                    else -> entry.supportingText
                }
                ListItem(
                    headlineContent = {
                        Text(entry.title, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    },
                    supportingContent = {
                        Text(supportingText, color = theme.colors.textSecondary)
                    },
                    modifier = Modifier
                        .heightIn(min = theme.components.controls.minimumTouchTarget)
                        .clickable(role = Role.Button) {
                            val chapterId = entry.chapterId
                            if (chapterId == null) {
                                onSelectAsset(entry.assetId)
                            } else {
                                onSelectChapter(entry.assetId, chapterId)
                            }
                        },
                )
            }
        }
    }
}

private const val AUDIO_QUEUE_PAGE_SIZE = 20

private data class AudioQueueEntry(
    val key: String,
    val assetId: String,
    val chapterId: String?,
    val title: String,
    val supportingText: String,
)

/**
 * The runtime intentionally supplies no unauthenticated remote image path to this surface. The
 * optional bitmap branch documents the media slot contract for a future authenticated adapter;
 * every ratio is rendered with ContentScale.Fit and the fallback remains a real brand affordance.
 */
@Composable
private fun AudioArtwork(
    title: String,
    modifier: Modifier = Modifier,
    artwork: ImageBitmap? = null,
    iconSize: Dp = 48.dp,
) {
    val theme = WarmPageThemeValues
    val shape = RoundedCornerShape(theme.radii.coverHero)
    val coverDescription = stringResource(R.string.audio_cover_description, title)
    Box(
        modifier = modifier
            .aspectRatio(1f)
            .shadow(4.dp, shape)
            .clip(shape)
            .background(theme.colors.surfaceRaised)
            .semantics { contentDescription = coverDescription },
        contentAlignment = Alignment.Center,
    ) {
        if (artwork != null) {
            Image(
                bitmap = artwork,
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Image(
                painter = painterResource(R.drawable.ermao_library_brand),
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(if (iconSize > 24.dp) theme.spacing.three else theme.spacing.half),
            )
        }
    }
}

@Composable
private fun audioStatusLabel(phase: AndroidAudioPhase): String = when (phase) {
    AndroidAudioPhase.Idle -> ""
    AndroidAudioPhase.Loading -> stringResource(R.string.audio_status_loading)
    AndroidAudioPhase.Ready -> stringResource(R.string.audio_status_ready)
    AndroidAudioPhase.Playing -> stringResource(R.string.audio_status_playing)
    AndroidAudioPhase.Paused -> stringResource(R.string.audio_status_paused)
    AndroidAudioPhase.Buffering -> stringResource(R.string.audio_status_buffering)
    AndroidAudioPhase.Ended -> stringResource(R.string.audio_status_ended)
    AndroidAudioPhase.Error -> stringResource(R.string.audio_status_error)
}

private fun formatMillis(millis: Long): String {
    val totalSeconds = (millis / 1_000).coerceAtLeast(0)
    val hours = totalSeconds / 3_600
    val minutes = (totalSeconds % 3_600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) {
        String.format(Locale.ROOT, "%d:%02d:%02d", hours, minutes, seconds)
    } else {
        String.format(Locale.ROOT, "%d:%02d", minutes, seconds)
    }
}

private fun formatPlaybackTime(position: Long, duration: Long): String =
    "${formatMillis(position)} / ${formatMillis(duration)}"

private fun formatPlaybackRate(rate: Float): String = NumberFormat.getNumberInstance().run {
    minimumFractionDigits = 0
    maximumFractionDigits = 2
    format(rate)
}

@Composable
private fun Modifier.navigationBarsPaddingCompat(): Modifier =
    windowInsetsPadding(WindowInsets.navigationBars)
