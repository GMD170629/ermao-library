package com.ermao.library.features.library.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudDownload
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.VolumeContent
import com.ermao.library.features.content.model.WorkDetailContent
import com.ermao.library.features.content.ui.ContentAreaMessage
import com.ermao.library.features.content.ui.CoverSize
import com.ermao.library.features.content.ui.WorkCover
import com.ermao.library.features.library.application.WorkDetailContentTab
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.theme.WarmPageThemeValues

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkDetailScreen(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onBack: () -> Unit,
    onSelectMedia: (String) -> Unit,
    onSelectVolume: (String) -> Unit,
    onSelectContentTab: (WorkDetailContentTab) -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    var showActions by remember { mutableStateOf(false) }
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
                onSelectContentTab = onSelectContentTab,
                onOpenFacet = onOpenFacet,
                modifier = Modifier.padding(padding),
            )
        }
    }

    if (showActions && state.content != null) {
        WorkActionsSheet(state.content, onDismiss = { showActions = false })
    }
}

@Composable
private fun WorkDetailBody(
    state: WorkDetailUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onSelectMedia: (String) -> Unit,
    onSelectVolume: (String) -> Unit,
    onSelectContentTab: (WorkDetailContentTab) -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    val content = requireNotNull(state.content)
    val selectedMedia = content.media.firstOrNull { it.kind == state.selectedMediaKind }
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = theme.spacing.three, end = theme.spacing.three, bottom = theme.spacing.six),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
    ) {
        item { IdentityHeader(content, repository, context, onOpenFacet) }
        item { ReadingSummary(content) }
        item {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Button(
                    onClick = {},
                    enabled = false,
                    modifier = Modifier.fillMaxWidth().testTag("work-reader-disabled"),
                    colors = ButtonDefaults.buttonColors(disabledContainerColor = theme.colors.actionAccent.copy(alpha = 0.45f)),
                ) {
                    Icon(Icons.Outlined.Book, contentDescription = null)
                    Text(primaryActionLabel(state.selectedMediaKind), modifier = Modifier.padding(start = theme.spacing.one))
                }
                Text(
                    stringResource(R.string.work_reader_next_phase_message),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                    modifier = Modifier.padding(top = theme.spacing.one),
                )
            }
        }
        if (content.showsContentTabs) {
            item {
                PrimaryTabRow(selectedTabIndex = state.selectedContentTab.ordinal, containerColor = theme.colors.canvas) {
                    WorkDetailContentTab.entries.forEach { tab ->
                        Tab(
                            selected = state.selectedContentTab == tab,
                            onClick = { onSelectContentTab(tab) },
                            text = { Text(contentTabLabel(tab)) },
                        )
                    }
                }
            }
        }
        when (state.selectedContentTab.takeIf { content.showsContentTabs } ?: WorkDetailContentTab.MediaVersions) {
            WorkDetailContentTab.Description -> item { DescriptionContent(content) }
            WorkDetailContentTab.MediaVersions -> {
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
                    item { ChapterFallbackMessage() }
                    items(content.readingUnits, key = ReadingUnitContent::id) { chapter -> ChapterRow(chapter) }
                } else {
                    item {
                        Text(
                            if (content.showsMediaPicker) {
                                pluralStringResource(
                                    R.plurals.work_media_volume_count,
                                    selectedMedia?.volumes?.size ?: 0,
                                    mediaLabel(state.selectedMediaKind.orEmpty()),
                                    selectedMedia?.volumes?.size ?: 0,
                                )
                            } else {
                                val count = selectedMedia?.volumes?.size ?: 0
                                pluralStringResource(R.plurals.work_volume_count, count, count)
                            },
                            style = theme.typography.sectionTitle,
                        )
                    }
                    if (selectedMedia == null || selectedMedia.volumes.isEmpty()) {
                        item { Text(stringResource(R.string.work_no_readable_volumes), color = theme.colors.textSecondary) }
                    } else {
                        items(selectedMedia.volumes, key = VolumeContent::id) { volume ->
                            VolumeRow(volume, volume.id == state.selectedVolumeId, onSelectVolume)
                        }
                    }
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
            CoverSize.Large,
            Modifier.width(112.dp),
        )
        Column(
            Modifier.weight(1f).height(168.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(content.work.title, style = theme.typography.title)
            FacetLink(content.work.author, content.authorFacetId != null) {
                content.authorFacetId?.let { onOpenFacet(LibraryScope.Authors, it) }
            }
            if (content.tags.isNotEmpty()) {
                Row(
                    modifier = Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
                ) {
                    content.tags.forEach { tag -> TagLabel(tag) }
                }
            }
            if (content.completed || content.work.progressPercent != null) {
                ReadingStatusLabel(content)
            }
            content.seriesName?.let { series ->
                Spacer(Modifier.weight(1f))
                FacetLink(series, content.seriesId != null, accent = true, underline = true) {
                    content.seriesId?.let { onOpenFacet(LibraryScope.Series, it) }
                }
            }
        }
    }
}

@Composable
private fun FacetLink(
    label: String,
    enabled: Boolean,
    accent: Boolean = false,
    underline: Boolean = false,
    onClick: () -> Unit,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = Modifier.clickable(enabled = enabled, onClick = onClick).padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = theme.typography.body.copy(
                textDecoration = if (underline) androidx.compose.ui.text.style.TextDecoration.Underline else null,
            ),
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
private fun ReadingStatusLabel(content: WorkDetailContent) {
    val theme = WarmPageThemeValues
    Surface(shape = RoundedCornerShape(8.dp), color = theme.colors.accentSoft) {
        Text(
            if (content.completed) stringResource(R.string.reading_status_finished)
            else if (content.work.progressPercent != null) stringResource(R.string.reading_status_reading)
            else stringResource(R.string.reading_status_unread),
            style = theme.typography.callout,
            color = theme.colors.actionAccent,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
        )
    }
}

@Composable
private fun ReadingSummary(content: WorkDetailContent) {
    val theme = WarmPageThemeValues
    val progress = content.work.progressPercent ?: 0
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(theme.spacing.two)) {
            Text("$progress%", style = theme.typography.display)
            Text(stringResource(R.string.work_overall_reading_progress), style = theme.typography.callout, color = theme.colors.textSecondary)
        }
        LinearProgressIndicator(
            progress = { progress / 100f },
            modifier = Modifier.fillMaxWidth().height(3.dp),
            color = theme.colors.brandAccent,
            trackColor = theme.colors.divider,
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Schedule, contentDescription = null, tint = theme.colors.textSecondary)
            Text(stringResource(R.string.work_progress_sync_hint), style = theme.typography.caption, color = theme.colors.textSecondary)
        }
    }
}

@Composable
private fun DescriptionContent(content: WorkDetailContent) {
    val theme = WarmPageThemeValues
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.two)) {
        Text(stringResource(R.string.work_description_title), style = theme.typography.sectionTitle)
        Text(
            content.description?.takeIf(String::isNotBlank) ?: stringResource(R.string.work_description_empty),
            style = theme.typography.body,
            color = if (content.description.isNullOrBlank()) theme.colors.textSecondary else theme.colors.textPrimary,
        )
    }
}

@Composable
private fun VolumeRow(volume: VolumeContent, selected: Boolean, onSelectVolume: (String) -> Unit) {
    val theme = WarmPageThemeValues
    Column {
        Row(
            modifier = Modifier.fillMaxWidth().clickable { onSelectVolume(volume.id) }.padding(vertical = theme.spacing.two),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (selected) Box(Modifier.width(3.dp).height(52.dp).background(theme.colors.brandAccent, RoundedCornerShape(2.dp)))
            Column(Modifier.weight(1f).padding(start = if (selected) theme.spacing.two else 0.dp)) {
                Text(volume.title, style = theme.typography.headline)
                Text(
                    stringResource(R.string.work_volume_reading_progress, volume.progressPercent ?: 0),
                    style = theme.typography.callout,
                    color = theme.colors.textSecondary,
                )
                Text(
                    listOfNotNull(volume.format.takeIf(String::isNotBlank), formatBytes(volume.sizeBytes)).joinToString(" · "),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                )
            }
            IconButton(onClick = {}, enabled = false, modifier = Modifier.semantics { disabled() }) {
                Icon(Icons.Outlined.CloudDownload, contentDescription = stringResource(R.string.work_download_unavailable))
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = theme.colors.textSecondary)
        }
        HorizontalDivider(color = theme.colors.divider)
    }
}

@Composable
private fun ChapterFallbackMessage() {
    val theme = WarmPageThemeValues
    Text(stringResource(R.string.work_single_ebook_fallback), style = theme.typography.callout, color = theme.colors.textSecondary)
}

@Composable
private fun ChapterRow(chapter: ReadingUnitContent) {
    val theme = WarmPageThemeValues
    Column {
        Row(Modifier.fillMaxWidth().padding(vertical = theme.spacing.two), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(chapter.title, style = theme.typography.headline)
                chapter.progressPercent?.let {
                    Text(stringResource(R.string.work_volume_reading_progress, it), color = theme.colors.textSecondary)
                }
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = theme.colors.textSecondary)
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
            UnavailableAction(Icons.Outlined.CheckCircle, R.string.work_action_add_shelf)
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
private fun contentTabLabel(tab: WorkDetailContentTab): String = when (tab) {
    WorkDetailContentTab.Description -> stringResource(R.string.work_tab_description)
    WorkDetailContentTab.MediaVersions -> stringResource(R.string.work_tab_media_versions)
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
