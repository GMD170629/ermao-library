package com.ermao.library.features.library.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudDownload
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.PauseCircle
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.ermao.library.R
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.VolumeContent
import com.ermao.library.features.content.model.WorkDetailContent
import com.ermao.library.features.content.ui.ContentAreaMessage
import com.ermao.library.features.content.ui.ContentCover
import com.ermao.library.features.content.ui.CoverProgress
import com.ermao.library.features.content.ui.CoverRole
import com.ermao.library.features.content.ui.ReadingProgress
import com.ermao.library.features.content.ui.WorkCover
import com.ermao.library.features.content.ui.responsiveCoverColumnCount
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.theme.WarmPageThemeValues
import com.ermao.library.ui.components.WarmPagePrimaryAction
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.isSupportedNativeReaderEntry
import com.ermao.library.features.downloads.model.AndroidDownloadStatus

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkDetailScreen(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onBack: () -> Unit,
    onSelectMedia: (String) -> Unit,
    onSelectVolume: (String) -> Unit,
    onOpenShelfPicker: () -> Unit,
    onDismissShelfPicker: () -> Unit,
    onToggleShelf: (String) -> Unit,
    onSaveShelves: () -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    onRefresh: () -> Unit = {},
    downloadRecordsByVolume: Map<String, AndroidDownloadRecord> = emptyMap(),
    downloadFailuresByVolume: Map<String, String> = emptyMap(),
    onDownloadVolume: (String) -> Unit = {},
    onCancelDownload: (String) -> Unit = {},
    onOpenSelectedVolume: (VolumeContent) -> Unit = {},
) {
    val theme = WarmPageThemeValues
    var showActions by remember { mutableStateOf(false) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { onRefresh() }
    Scaffold(
        modifier = modifier.testTag("work-detail"),
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.work_detail_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.navigate_back))
                    }
                },
                actions = {
                    IconButton(onClick = { showActions = true }, enabled = state.content != null) {
                        Icon(Icons.Outlined.MoreVert, contentDescription = stringResource(R.string.work_more_actions))
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = theme.colors.canvas),
            )
        },
    ) { padding ->
        when {
            state.isLoading -> ContentAreaMessage(
                stringResource(R.string.content_loading_title),
                stringResource(R.string.work_detail_loading_message),
                loading = true,
                modifier = Modifier.padding(padding),
            )
            state.content == null -> ContentAreaMessage(
                stringResource(R.string.work_unavailable_title),
                stringResource(R.string.work_unavailable_message),
                modifier = Modifier.padding(padding),
                actionLabel = stringResource(R.string.retry_action),
                onAction = onRetry,
            )
            else -> WorkDetailBody(
                state = state,
                repository = repository,
                context = context,
                onSelectMedia = onSelectMedia,
                onSelectVolume = onSelectVolume,
                onOpenShelfPicker = onOpenShelfPicker,
                onOpenFacet = onOpenFacet,
                downloadRecordsByVolume = downloadRecordsByVolume,
                downloadFailuresByVolume = downloadFailuresByVolume,
                onDownloadVolume = onDownloadVolume,
                onCancelDownload = onCancelDownload,
                onOpenSelectedVolume = onOpenSelectedVolume,
                modifier = Modifier.padding(padding),
            )
        }
    }

    if (showActions && state.content != null) {
        WorkActionsSheet(state.content, onDismiss = { showActions = false })
    }
    if (state.isShelfPickerVisible) {
        ShelfPickerSheet(state, onDismissShelfPicker, onToggleShelf, onSaveShelves)
    }
}

@Composable
private fun WorkDetailBody(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onSelectMedia: (String) -> Unit,
    onSelectVolume: (String) -> Unit,
    onOpenShelfPicker: () -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    downloadRecordsByVolume: Map<String, AndroidDownloadRecord>,
    downloadFailuresByVolume: Map<String, String>,
    onDownloadVolume: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    onOpenSelectedVolume: (VolumeContent) -> Unit,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    val content = requireNotNull(state.content)
    val selectedMedia = content.media.firstOrNull { it.kind == state.selectedMediaKind }
    val selectedVolume = selectedMedia?.volumes?.firstOrNull { it.id == state.selectedVolumeId }
        ?: selectedMedia?.volumes?.firstOrNull { it.selected }
        ?: selectedMedia?.volumes?.firstOrNull()
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = theme.spacing.two, end = theme.spacing.two, bottom = theme.spacing.six),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
    ) {
        item {
            Box(Modifier.testTag("work-identity")) {
                IdentityHeader(content, repository, context, onOpenFacet)
            }
        }
        item {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Row(horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
                    Button(
                        onClick = onOpenShelfPicker,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = theme.colors.accentSoft,
                            contentColor = theme.colors.actionAccent,
                        ),
                        modifier = Modifier.weight(1f).height(56.dp).testTag("work-shelf-action"),
                    ) {
                        Icon(Icons.Outlined.BookmarkBorder, contentDescription = null)
                        Text(stringResource(R.string.work_action_add_shelf), modifier = Modifier.padding(start = theme.spacing.one))
                    }
                WarmPagePrimaryAction(
                    label = primaryActionLabel(state.selectedMediaKind),
                    onClick = { selectedVolume?.let(onOpenSelectedVolume) },
                    enabled = selectedVolume?.readable == true,
                    modifier = Modifier.weight(1f).height(56.dp).testTag("work-reader-action"),
                )
                }
                val captionResource = if (selectedVolume == null) {
                    R.string.work_reader_next_phase_message
                } else {
                    val volume = selectedVolume
                    when {
                        !isSupportedNativeReaderEntry(volume.readerType, volume.format) ->
                            R.string.work_reader_renderer_pending
                        else -> null
                    }
                }
                captionResource?.let { resource ->
                    Text(
                        stringResource(resource),
                        style = theme.typography.caption,
                        color = theme.colors.textSecondary,
                        modifier = Modifier.padding(top = theme.spacing.one),
                    )
                }
            }
        }
        if (content.hasDescription) item { DescriptionContent(content) }
        item { HorizontalDivider(color = theme.colors.divider, modifier = Modifier.padding(vertical = theme.spacing.one)) }
        run {
                if (content.showsMediaPicker) item {
                    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                        content.media.forEachIndexed { index, media ->
                            SegmentedButton(
                                selected = media.kind == state.selectedMediaKind,
                                onClick = { onSelectMedia(media.kind) },
                                shape = SegmentedButtonDefaults.itemShape(index, content.media.size),
                                label = { Text(mediaLabel(media.kind)) },
                                icon = {},
                            )
                        }
                    }
                }
                if (content.usesEbookChapterFallback(state.selectedMediaKind)) {
                    item { ChapterCard(content.readingUnits) }
                } else {
                    item {
                        val count = selectedMedia?.volumes?.size ?: 0
                        SectionHeader(
                            stringResource(R.string.work_all_volumes),
                            pluralStringResource(R.plurals.work_volume_total, count, count),
                        )
                    }
                    if (selectedMedia == null || selectedMedia.volumes.isEmpty()) {
                        item { Text(stringResource(R.string.work_no_readable_volumes), color = theme.colors.textSecondary) }
                    } else item {
                        VolumeCoverGrid(
                            volumes = selectedMedia.volumes,
                            selectedVolumeId = selectedVolume?.id,
                            repository = repository,
                            context = context,
                            downloadRecordsByVolume = downloadRecordsByVolume,
                            downloadFailuresByVolume = downloadFailuresByVolume,
                            onSelectVolume = onSelectVolume,
                            onDownloadVolume = onDownloadVolume,
                            onCancelDownload = onCancelDownload,
                        )
                    }
                    if (content.readingUnits.isNotEmpty()) {
                        item { ChapterCard(content.readingUnits) }
                    }
                }
        }
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
    Row(horizontalArrangement = Arrangement.spacedBy(theme.spacing.three)) {
        WorkCover(
            content.work,
            repository,
            context,
            CoverRole.Hero,
            Modifier.width(112.dp),
        )
        Column(
            Modifier.weight(1f).heightIn(min = 168.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(content.work.title, style = theme.typography.title)
            FacetLink(content.work.author, content.authorFacetId != null) {
                content.authorFacetId?.let { onOpenFacet(LibraryScope.Authors, it) }
            }
            val format = content.media.firstOrNull()?.volumes?.firstOrNull()?.format?.takeIf(String::isNotBlank)
            val chips = (listOfNotNull(format?.lowercase()) + content.tags).distinctBy { it.lowercase() }
            if (chips.isNotEmpty()) {
                Row(
                    modifier = Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
                ) {
                    chips.forEach { tag -> TagLabel(tag) }
                }
            }
            content.seriesName?.let { series ->
                FacetLink(series, content.seriesId != null, accent = true) {
                    content.seriesId?.let { onOpenFacet(LibraryScope.Series, it) }
                }
            }
            Spacer(Modifier.weight(1f))
            ReadingSummary(content)
        }
    }
}

@Composable
private fun FacetLink(
    label: String,
    enabled: Boolean,
    accent: Boolean = false,
    onClick: () -> Unit,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = Modifier.clickable(enabled = enabled, onClick = onClick).padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = theme.typography.body,
            color = if (accent) theme.colors.actionAccent else theme.colors.textSecondary,
        )
    }
}

@Composable
private fun TagLabel(tag: String) {
    val theme = WarmPageThemeValues
    Surface(
        shape = RoundedCornerShape(3.dp),
        color = theme.colors.surface,
        border = BorderStroke(1.dp, theme.colors.divider),
        tonalElevation = 0.dp,
    ) {
        Text(tag, style = theme.typography.callout, modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
    }
}

@Composable
private fun ReadingSummary(content: WorkDetailContent) {
    val theme = WarmPageThemeValues
    val progress = content.work.progressPercent ?: 0
    if (progress <= 0) return
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.work_reading_progress), style = theme.typography.callout, color = theme.colors.textSecondary)
            Spacer(Modifier.weight(1f))
            content.readingUnits.firstOrNull { it.readingState == ChapterReadingState.Current }?.title?.let { title ->
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
        ReadingProgress(
            progressPercent = progress,
            stateDescription = stringResource(R.string.work_volume_accessibility_progress, progress),
        )
    }
}

@Composable
private fun DescriptionContent(content: WorkDetailContent) {
    val theme = WarmPageThemeValues
    var expanded by remember { mutableStateOf(false) }
    Column(
        verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
    ) {
        Text(stringResource(R.string.work_description_title), style = theme.typography.sectionTitle)
        Text(
            content.description.orEmpty(),
            style = theme.typography.body,
            maxLines = if (expanded) Int.MAX_VALUE else 3,
            overflow = TextOverflow.Ellipsis,
        )
        TextButton(onClick = { expanded = !expanded }, modifier = Modifier.align(Alignment.End)) {
            Text(stringResource(if (expanded) R.string.work_collapse else R.string.work_expand))
            Icon(if (expanded) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, contentDescription = null)
        }
    }
}

@Composable
private fun VolumeCoverGrid(
    volumes: List<VolumeContent>,
    selectedVolumeId: String?,
    repository: ContentRepository,
    context: ContentRequestContext,
    downloadRecordsByVolume: Map<String, AndroidDownloadRecord>,
    downloadFailuresByVolume: Map<String, String>,
    onSelectVolume: (String) -> Unit,
    onDownloadVolume: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
) {
    val theme = WarmPageThemeValues
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val columns = responsiveCoverColumnCount(maxWidth, LocalDensity.current.fontScale)
        Column(
            verticalArrangement = Arrangement.spacedBy(theme.spacing.three),
        ) {
            volumes.chunked(columns).forEach { rowVolumes ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
                ) {
                    rowVolumes.forEach { volume ->
                        val position = volumes.indexOf(volume)
                        VolumeCoverItem(
                            volume = volume,
                            position = position,
                            selected = volume.id == selectedVolumeId,
                            repository = repository,
                            context = context,
                            download = downloadRecordsByVolume[volume.id],
                            downloadFailure = downloadFailuresByVolume[volume.id],
                            onSelectVolume = onSelectVolume,
                            onDownloadVolume = onDownloadVolume,
                            onCancelDownload = onCancelDownload,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    repeat(columns - rowVolumes.size) { Spacer(Modifier.weight(1f)) }
                }
            }
        }
    }
}

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
    onDownloadVolume: (String) -> Unit,
    onCancelDownload: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val index = volume.displayIndex(position)
    val progress = volume.progressPercent?.coerceIn(0, 100) ?: 0
    val state = when {
        progress >= 100 -> stringResource(R.string.work_volume_accessibility_finished)
        progress > 0 -> stringResource(R.string.work_volume_accessibility_progress, progress)
        else -> stringResource(R.string.work_volume_accessibility_not_started)
    }
    val downloadLabel = when {
        download?.isReadable == true -> stringResource(R.string.downloads_offline_available)
        download?.status == AndroidDownloadStatus.Downloading || download?.status == AndroidDownloadStatus.Queued ->
            stringResource(R.string.work_download_pause)
        else -> stringResource(R.string.work_volume_download_action)
    }
    val volumeLabel = stringResource(R.string.work_volume_accessibility_label, index, volume.title)
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        Box {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (selected) Modifier.border(
                            width = 2.dp,
                            color = theme.colors.brandAccent,
                            shape = RoundedCornerShape(theme.radii.coverCompact),
                        ) else Modifier,
                    )
                    .clickable(enabled = volume.readable) { onSelectVolume(volume.id) }
                    .semantics(mergeDescendants = true) {
                        contentDescription = volumeLabel
                        this.selected = selected
                        stateDescription = state
                        if (!volume.readable) disabled()
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
                    modifier = Modifier.fillMaxWidth().alpha(if (volume.readable) 1f else 0.5f),
                )
                if (progress > 0) {
                    CoverProgress(
                        progressPercent = progress,
                        stateDescription = state,
                        modifier = Modifier.align(Alignment.BottomCenter),
                    )
                }
            }
            Surface(
                shape = RoundedCornerShape(theme.radii.coverCompact),
                color = theme.colors.surfaceRaised.copy(alpha = 0.92f),
                modifier = Modifier.align(Alignment.TopStart).padding(theme.spacing.one),
            ) {
                Text(
                    index,
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                    modifier = Modifier.padding(horizontal = theme.spacing.one, vertical = theme.spacing.half),
                )
            }
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .size(theme.metrics.androidMinimumTouchTarget)
                    .clickable(enabled = download?.isReadable != true) {
                        if (download?.status == AndroidDownloadStatus.Downloading ||
                            download?.status == AndroidDownloadStatus.Queued
                        ) onCancelDownload(volume.id) else onDownloadVolume(volume.id)
                    }
                    .semantics { contentDescription = downloadLabel },
                contentAlignment = Alignment.Center,
            ) {
                Surface(
                    shape = CircleShape,
                    color = theme.colors.surfaceRaised.copy(alpha = 0.92f),
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(
                        imageVector = when {
                            download?.isReadable == true -> Icons.Outlined.CheckCircle
                            download?.status == AndroidDownloadStatus.Downloading ||
                                download?.status == AndroidDownloadStatus.Queued -> Icons.Outlined.PauseCircle
                            else -> Icons.Outlined.CloudDownload
                        },
                        contentDescription = null,
                        tint = if (download?.isReadable == true) theme.colors.brandAccent else theme.colors.textSecondary,
                        modifier = Modifier.padding(5.dp),
                    )
                }
            }
        }
        Text(
            volume.title,
            style = theme.typography.callout,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
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
private fun SectionHeader(title: String, trailing: String) {
    val theme = WarmPageThemeValues
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = theme.typography.sectionTitle)
        Spacer(Modifier.weight(1f))
        Text(trailing, style = theme.typography.callout, color = theme.colors.textSecondary)
    }
}

@Composable
private fun ChapterCard(chapters: List<ReadingUnitContent>) {
    val theme = WarmPageThemeValues
    Column(
        verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
    ) {
        SectionHeader(
            stringResource(R.string.work_directory_title),
            pluralStringResource(R.plurals.work_chapter_total, chapters.size, chapters.size),
        )
        chapters.forEach { ChapterRow(it) }
    }
}

@Composable
private fun ChapterRow(chapter: ReadingUnitContent) {
    val theme = WarmPageThemeValues
    val stateLabel = when (chapter.readingState) {
        ChapterReadingState.Current -> stringResource(R.string.work_chapter_current)
        ChapterReadingState.Read -> stringResource(R.string.work_chapter_read)
        ChapterReadingState.Unread -> stringResource(R.string.work_chapter_unread)
    }
    val isCurrent = chapter.readingState == ChapterReadingState.Current
    Column {
        Row(
            Modifier.fillMaxWidth()
                .semantics { stateDescription = stateLabel }
                .background(
                    color = if (isCurrent) theme.colors.accentSoft else androidx.compose.ui.graphics.Color.Transparent,
                    shape = RoundedCornerShape(theme.radii.control),
                )
                .padding(horizontal = theme.spacing.one, vertical = theme.spacing.two),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
        ) {
            Box(
                Modifier.width(3.dp).height(32.dp).background(
                    color = if (isCurrent) theme.colors.brandAccent else androidx.compose.ui.graphics.Color.Transparent,
                    shape = RoundedCornerShape(2.dp),
                ),
            )
            Column(Modifier.weight(1f)) {
                Text(
                    chapter.title,
                    style = theme.typography.headline,
                    color = if (isCurrent) theme.colors.actionAccent else theme.colors.textPrimary,
                )
                chapter.progressPercent?.let { progress ->
                    Text(
                        "$progress%",
                        style = theme.typography.caption,
                        color = theme.colors.textSecondary,
                    )
                }
            }
            Text(
                stateLabel,
                style = theme.typography.label,
                color = if (isCurrent) theme.colors.actionAccent else theme.colors.textSecondary,
            )
            Icon(
                imageVector = when (chapter.readingState) {
                    ChapterReadingState.Current -> Icons.Outlined.BarChart
                    ChapterReadingState.Read -> Icons.Outlined.CheckCircle
                    ChapterReadingState.Unread -> Icons.AutoMirrored.Filled.KeyboardArrowRight
                },
                contentDescription = null,
                tint = if (isCurrent) theme.colors.brandAccent else theme.colors.textTertiary,
            )
        }
        HorizontalDivider(color = theme.colors.divider)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WorkActionsSheet(content: WorkDetailContent, onDismiss: () -> Unit) {
    val theme = WarmPageThemeValues
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = theme.colors.surface) {
        Column(Modifier.padding(bottom = theme.spacing.three)) {
            Text(stringResource(R.string.work_actions_title), style = theme.typography.sectionTitle, modifier = Modifier.padding(horizontal = theme.spacing.three))
            Text(
                listOf(content.work.title, content.work.author).joinToString(" · "),
                style = theme.typography.callout,
                color = theme.colors.textSecondary,
                modifier = Modifier.padding(horizontal = theme.spacing.three, vertical = theme.spacing.one),
            )
            UnavailableAction(Icons.Outlined.Book, R.string.work_primary_read_action)
            UnavailableAction(Icons.Outlined.Edit, R.string.work_action_edit)
            UnavailableAction(Icons.Outlined.Image, R.string.work_action_set_cover)
            UnavailableAction(Icons.Outlined.CloudDownload, R.string.work_action_download)
            UnavailableAction(Icons.Outlined.BookmarkBorder, R.string.work_action_reading_status)
            TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.cancel_action)) }
        }
    }
}

@Composable
private fun UnavailableAction(icon: androidx.compose.ui.graphics.vector.ImageVector, labelResource: Int) {
    val theme = WarmPageThemeValues
    ListItem(
        headlineContent = { Text(stringResource(labelResource)) },
        supportingContent = { Text(stringResource(R.string.work_action_unavailable)) },
        leadingContent = { Icon(icon, contentDescription = null) },
        colors = ListItemDefaults.colors(containerColor = theme.colors.surface),
        modifier = Modifier.semantics { disabled() },
    )
}

@Composable
private fun mediaLabel(kind: String): String = when (kind.uppercase()) {
    "EBOOK" -> stringResource(R.string.media_ebook)
    "COMIC" -> stringResource(R.string.media_comic)
    "AUDIOBOOK" -> stringResource(R.string.media_audiobook)
    else -> kind
}

@Composable
private fun primaryActionLabel(kind: String?): String = if (kind.equals("AUDIOBOOK", ignoreCase = true)) {
    stringResource(R.string.work_primary_listen_action)
} else {
    stringResource(R.string.work_primary_read_action)
}

private fun formatBytes(bytes: Long): String? = when {
    bytes <= 0 -> null
    bytes >= 1024L * 1024L * 1024L -> "${formatSizeNumber(bytes / (1024.0 * 1024.0 * 1024.0))} GB"
    bytes >= 1024L * 1024L -> "${formatSizeNumber(bytes / (1024.0 * 1024.0))} MB"
    else -> "${formatSizeNumber(bytes / 1024.0)} KB"
}

private fun formatSizeNumber(value: Double): String = java.text.NumberFormat.getNumberInstance().run {
    maximumFractionDigits = 1
    minimumFractionDigits = 0
    format(value)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ShelfPickerSheet(
    state: WorkDetailUiState,
    onDismiss: () -> Unit,
    onToggleShelf: (String) -> Unit,
    onSave: () -> Unit,
) {
    val theme = WarmPageThemeValues
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = theme.colors.surface) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = theme.spacing.three, vertical = theme.spacing.two),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
        ) {
            Text(stringResource(R.string.work_shelf_picker_title), style = theme.typography.sectionTitle)
            when {
                state.isLoadingShelves -> Box(Modifier.fillMaxWidth().height(112.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                state.shelfErrorCode != null -> {
                    Text(stringResource(R.string.work_shelf_load_failed), color = androidx.compose.material3.MaterialTheme.colorScheme.error)
                    TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel_action)) }
                }
                state.shelves.isEmpty() -> Text(
                    stringResource(R.string.work_shelf_empty),
                    style = theme.typography.body,
                    color = theme.colors.textSecondary,
                )
                else -> {
                    state.shelves.forEach { shelf ->
                        Row(
                            Modifier.fillMaxWidth().clickable(enabled = !state.isSavingShelves) { onToggleShelf(shelf.id) },
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(
                                checked = shelf.id in state.selectedShelfIds,
                                onCheckedChange = { onToggleShelf(shelf.id) },
                                enabled = !state.isSavingShelves,
                            )
                            Text(shelf.name, style = theme.typography.body, modifier = Modifier.weight(1f))
                        }
                    }
                    Button(
                        onClick = onSave,
                        enabled = !state.isSavingShelves,
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                    ) {
                        if (state.isSavingShelves) CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                        else Text(stringResource(R.string.work_shelf_save))
                    }
                }
            }
        }
    }
}
