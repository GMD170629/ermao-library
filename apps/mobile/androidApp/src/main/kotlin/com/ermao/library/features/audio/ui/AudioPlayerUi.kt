package com.ermao.library.features.audio.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Headphones
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.Forward30
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.audio.application.AndroidAudioPlaybackRuntime
import com.ermao.library.features.audio.model.AndroidAudioPhase
import com.ermao.library.features.audio.model.AndroidAudioPlaybackSnapshot
import com.ermao.library.features.audio.model.AndroidAudioTrack
import com.ermao.library.features.audio.model.SUPPORTED_PLAYBACK_RATES
import com.ermao.library.ui.theme.WarmPageThemeValues
import java.util.Locale
import kotlin.math.roundToLong

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
    val playPauseLabel = if (snapshot.phase == AndroidAudioPhase.Playing) {
        stringResource(R.string.audio_pause)
    } else {
        stringResource(R.string.audio_play)
    }
    val progressLabel = stringResource(R.string.audio_progress)
    Surface(
        color = theme.colors.surface,
        modifier = modifier
            .fillMaxWidth()
            .semantics {
                stateDescription = status
            },
    ) {
        Column {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(72.dp)
                    .clickable(role = Role.Button, onClick = onOpen)
                    .padding(horizontal = theme.spacing.two),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                AudioArtwork(
                    title = title,
                    modifier = Modifier.size(48.dp),
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
                    modifier = Modifier
                        .size(theme.components.controls.minimumTouchTarget)
                        .semantics { contentDescription = "$playPauseLabel · $title" },
                ) {
                    Icon(
                        imageVector = if (snapshot.phase == AndroidAudioPhase.Playing) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                        contentDescription = null,
                        tint = theme.colors.textPrimary,
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
    var moreMenuVisible by remember { mutableStateOf(false) }
    val title = snapshot.title ?: stringResource(R.string.audio_unknown_title)
    val chapter = snapshot.chapterTitle ?: stringResource(R.string.audio_no_chapter)
    val duration = snapshot.durationMillis
    val current = snapshot.positionMillis
    val status = audioStatusLabel(snapshot.phase)
    val retryLabel = stringResource(R.string.audio_retry)
    val scrubberLabel = stringResource(R.string.audio_scrubber)
    val playPauseLabel = if (snapshot.phase == AndroidAudioPhase.Playing) {
        stringResource(R.string.audio_pause)
    } else {
        stringResource(R.string.audio_play)
    }
    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        contentColor = theme.colors.textPrimary,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = stringResource(R.string.audio_now_playing),
                        style = theme.typography.headline,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onClose) {
                        Icon(
                            imageVector = Icons.Filled.SkipPrevious,
                            contentDescription = stringResource(R.string.audio_collapse),
                        )
                    }
                },
                actions = {
                    Box {
                        IconButton(onClick = { moreMenuVisible = true }) {
                            Icon(
                                imageVector = Icons.Filled.MoreVert,
                                contentDescription = stringResource(R.string.audio_more_actions),
                            )
                        }
                        DropdownMenu(
                            expanded = moreMenuVisible,
                            onDismissRequest = { moreMenuVisible = false },
                        ) {
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.audio_stop)) },
                                onClick = {
                                    moreMenuVisible = false
                                    runtime.stop()
                                    onClose()
                                },
                            )
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = theme.colors.canvas,
                    scrolledContainerColor = theme.colors.surface,
                    titleContentColor = theme.colors.textPrimary,
                    navigationIconContentColor = theme.colors.textPrimary,
                    actionIconContentColor = theme.colors.textPrimary,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = theme.spacing.two, vertical = theme.spacing.three),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            AudioArtwork(title, Modifier.size(232.dp))
            Spacer(Modifier.height(theme.spacing.three))
            Text(
                text = title,
                style = theme.typography.title,
                color = theme.colors.textPrimary,
                modifier = Modifier.fillMaxWidth(),
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = chapter,
                style = theme.typography.body,
                color = theme.colors.textSecondary,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = theme.spacing.half),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = status,
                style = theme.typography.callout,
                color = if (snapshot.phase == AndroidAudioPhase.Error) {
                    MaterialTheme.colorScheme.error
                } else {
                    theme.colors.textSecondary
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = theme.spacing.one),
            )
            if (snapshot.phase == AndroidAudioPhase.Error) {
                TextButton(
                    onClick = runtime::retry,
                    modifier = Modifier
                        .align(Alignment.Start)
                        .semantics { contentDescription = retryLabel },
                ) {
                    Text(stringResource(R.string.audio_retry), color = theme.colors.actionAccent)
                }
            }
            Spacer(Modifier.height(theme.spacing.two))
            if (duration > 0) {
                Slider(
                    value = (current.toFloat() / duration.toFloat()).coerceIn(0f, 1f),
                    onValueChange = { fraction -> runtime.seekTo((fraction * duration).roundToLong()) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .semantics {
                            contentDescription = scrubberLabel
                            stateDescription = formatPlaybackTime(current, duration)
                        },
                )
            } else {
                LinearProgressIndicator(
                    progress = { 0f },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(4.dp)
                        .semantics { contentDescription = scrubberLabel },
                    color = theme.colors.brandAccent,
                    trackColor = theme.colors.divider,
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(formatMillis(current), style = theme.typography.caption, color = theme.colors.textSecondary)
                Text(formatMillis(duration), style = theme.typography.caption, color = theme.colors.textSecondary)
            }
            Spacer(Modifier.height(theme.spacing.two))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                AudioIconButton(
                    icon = Icons.Filled.SkipPrevious,
                    label = stringResource(R.string.audio_previous),
                    onClick = runtime::previous,
                )
                AudioIconButton(
                    icon = Icons.Filled.Replay10,
                    label = stringResource(R.string.audio_back_15),
                    onClick = runtime::skipBack,
                )
                IconButton(
                    onClick = {
                        if (snapshot.phase == AndroidAudioPhase.Playing) runtime.pause() else runtime.play()
                    },
                    modifier = Modifier
                        .size(64.dp)
                        .semantics { contentDescription = playPauseLabel },
                ) {
                    Icon(
                        imageVector = if (snapshot.phase == AndroidAudioPhase.Playing) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                        contentDescription = null,
                        tint = theme.colors.actionAccent,
                        modifier = Modifier.size(42.dp),
                    )
                }
                AudioIconButton(
                    icon = Icons.Filled.Forward30,
                    label = stringResource(R.string.audio_forward_30),
                    onClick = runtime::skipForward,
                )
                AudioIconButton(
                    icon = Icons.Filled.SkipNext,
                    label = stringResource(R.string.audio_next),
                    onClick = runtime::next,
                )
            }
            Spacer(Modifier.height(theme.spacing.two))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                Box {
                    TextButton(onClick = { speedMenuVisible = true }) {
                        Text(
                            text = stringResource(R.string.audio_speed_value, snapshot.playbackRate),
                            color = theme.colors.actionAccent,
                        )
                    }
                    DropdownMenu(
                        expanded = speedMenuVisible,
                        onDismissRequest = { speedMenuVisible = false },
                    ) {
                        SUPPORTED_PLAYBACK_RATES.forEach { rate ->
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        text = stringResource(R.string.audio_speed_value, rate),
                                        color = if (rate == snapshot.playbackRate) theme.colors.actionAccent else theme.colors.textPrimary,
                                    )
                                },
                                onClick = {
                                    speedMenuVisible = false
                                    runtime.setPlaybackRate(rate)
                                },
                            )
                        }
                    }
                }
                TextButton(onClick = { queueVisible = true }) {
                    Text(stringResource(R.string.audio_chapters_queue), color = theme.colors.actionAccent)
                }
            }
        }
    }
    if (queueVisible) {
        AudioQueueSheet(
            snapshot = snapshot,
            intentTracks = runtime.currentTracks(),
            onSelectAsset = runtime::selectAsset,
            onSelectChapter = runtime::selectChapter,
            onDismiss = { queueVisible = false },
        )
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
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.safeDrawing),
            color = WarmPageThemeValues.colors.canvas,
        ) {
            BackHandler(onBack = onDismiss)
            AudioNowPlayingScreen(snapshot = snapshot, runtime = runtime, onClose = onDismiss)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AudioQueueSheet(
    snapshot: AndroidAudioPlaybackSnapshot,
    intentTracks: List<AndroidAudioTrack>,
    onSelectAsset: (String) -> Unit,
    onSelectChapter: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        val theme = WarmPageThemeValues
        Text(
            text = stringResource(R.string.audio_chapters_queue),
            style = theme.typography.sectionTitle,
            color = theme.colors.textPrimary,
            modifier = Modifier.padding(horizontal = theme.spacing.two, vertical = theme.spacing.one),
        )
        LazyColumn(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPaddingCompat(),
        ) {
            intentTracks.forEach { track ->
                item(key = "track:${track.assetId}") {
                    ListItem(
                        headlineContent = { Text(track.title, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                        supportingContent = {
                            Text(
                                text = if (track.assetId == snapshot.assetId) {
                                    stringResource(R.string.audio_track_current)
                                } else {
                                    formatMillis(track.durationMillis ?: 0)
                                },
                                color = theme.colors.textSecondary,
                            )
                        },
                        modifier = Modifier.clickable {
                            onSelectAsset(track.assetId)
                        },
                    )
                }
                items(track.chapters, key = { chapter -> "chapter:${track.assetId}:${chapter.id}" }) { chapter ->
                    ListItem(
                        headlineContent = { Text(chapter.title, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                        supportingContent = { Text(formatMillis(chapter.startMillis), color = theme.colors.textSecondary) },
                        modifier = Modifier
                            .padding(start = theme.spacing.four)
                            .clickable { onSelectChapter(chapter.id) },
                    )
                }
            }
            item { Spacer(Modifier.height(theme.spacing.four)) }
        }
    }
}

@Composable
private fun AudioArtwork(title: String, modifier: Modifier = Modifier) {
    val theme = WarmPageThemeValues
    val coverDescription = stringResource(R.string.audio_cover_description, title)
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(theme.radii.coverHero))
            .background(theme.colors.accentSoft)
            .semantics { contentDescription = coverDescription },
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = Icons.Filled.Headphones,
            contentDescription = null,
            tint = theme.colors.brandAccent,
            modifier = Modifier.size(48.dp),
        )
    }
}

@Composable
private fun AudioIconButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    onClick: () -> Unit,
) {
    IconButton(
        onClick = onClick,
        modifier = Modifier
            .size(WarmPageThemeValues.components.controls.minimumTouchTarget)
            .semantics { contentDescription = label },
    ) {
        Icon(icon, contentDescription = null, tint = WarmPageThemeValues.colors.textPrimary)
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

@Composable
private fun Modifier.navigationBarsPaddingCompat(): Modifier = windowInsetsPadding(WindowInsets.navigationBars)
