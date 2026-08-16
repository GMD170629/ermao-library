package com.ermao.library.features.downloads.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudDownload
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
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
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.ui.ContentAreaMessage
import com.ermao.library.features.downloads.application.DownloadCenterUiState
import com.ermao.library.features.downloads.application.DownloadedWorkUiState
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.DownloadedWorkGroup
import com.ermao.library.features.downloads.model.DownloadedMediaVersionGroup
import com.ermao.library.ui.components.rememberForwardProgress
import com.ermao.library.ui.theme.WarmPageThemeValues

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DownloadCenterScreen(
    state: DownloadCenterUiState,
    onBack: () -> Unit,
    onQueryChanged: (String) -> Unit,
    onClearQuery: () -> Unit,
    onOpenWork: (String) -> Unit,
    onRetry: () -> Unit,
    onCancelDownload: (String) -> Unit,
    onRetryDownload: (String) -> Unit,
    onRemoveDownload: (AndroidDownloadRecord) -> Unit,
    modifier: Modifier = Modifier,
    showBackNavigation: Boolean = true,
    allowManagementActions: Boolean = true,
) {
    val theme = WarmPageThemeValues
    var pendingRemoval by remember { mutableStateOf<AndroidDownloadRecord?>(null) }
    Scaffold(
        modifier = modifier.testTag("downloads-center"),
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.downloads_title)) },
                navigationIcon = {
                    if (showBackNavigation) {
                        IconButton(onClick = onBack) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.navigate_back))
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = theme.colors.canvas),
            )
        },
    ) { padding ->
        if (state.isLoading) {
            ContentAreaMessage(stringResource(R.string.content_loading_title), stringResource(R.string.downloads_loading), modifier = Modifier.padding(padding), loading = true)
        } else if (state.errorCode != null) {
            ContentAreaMessage(stringResource(R.string.content_error_title), stringResource(R.string.downloads_error), modifier = Modifier.padding(padding), actionLabel = stringResource(R.string.retry_action), onAction = onRetry)
        } else {
            LazyColumn(
                Modifier.fillMaxSize().padding(padding),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
            ) {
                item {
                    Column(Modifier.padding(horizontal = theme.spacing.three)) {
                        Text(stringResource(R.string.downloads_storage), style = theme.typography.sectionTitle)
                        Text(stringResource(R.string.downloads_used_space, formatBytes(state.totalCompletedBytes)), color = theme.colors.textSecondary)
                    }
                }
                if (state.active.isNotEmpty()) {
                    item { SectionTitle(R.string.downloads_active) }
                    items(state.active, key = AndroidDownloadRecord::taskId) {
                        ActiveRow(it, onCancelDownload.takeIf { allowManagementActions })
                    }
                }
                item {
                    OutlinedTextField(
                        value = state.query,
                        onValueChange = onQueryChanged,
                        label = { Text(stringResource(R.string.downloads_search)) },
                        leadingIcon = { Icon(Icons.Outlined.Search, null) },
                        trailingIcon = if (state.query.isNotEmpty()) ({ TextButton(onClick = onClearQuery) { Text(stringResource(R.string.clear_action)) } }) else null,
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth().padding(horizontal = theme.spacing.three).testTag("downloads-search"),
                    )
                }
                item { SectionTitle(R.string.downloads_completed) }
                if (state.completedWorks.isEmpty()) {
                    item { Text(stringResource(if (state.query.isBlank()) R.string.downloads_empty else R.string.downloads_search_empty), modifier = Modifier.padding(horizontal = theme.spacing.three), color = theme.colors.textSecondary) }
                } else {
                    items(state.completedWorks, key = DownloadedWorkGroup::workId) { DownloadedWorkRow(it, onOpenWork) }
                }
                if (state.failed.isNotEmpty()) {
                    item { SectionTitle(R.string.downloads_failed) }
                    items(state.failed, key = AndroidDownloadRecord::taskId) {
                        FailedRow(
                            it,
                            onRetry = { onRetryDownload(it.volumeId) }.takeIf { allowManagementActions },
                            onRemove = { pendingRemoval = it }.takeIf { allowManagementActions },
                        )
                    }
                }
            }
        }
    }
    pendingRemoval?.let { record ->
        AlertDialog(
            onDismissRequest = { pendingRemoval = null },
            title = { Text(stringResource(R.string.downloads_remove_title)) },
            text = { Text(stringResource(R.string.downloads_remove_message, record.workTitle)) },
            confirmButton = {
                TextButton(onClick = {
                    pendingRemoval = null
                    onRemoveDownload(record)
                }) { Text(stringResource(R.string.downloads_remove_action)) }
            },
            dismissButton = {
                TextButton(onClick = { pendingRemoval = null }) { Text(stringResource(R.string.cancel_action)) }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DownloadedWorkScreen(
    state: DownloadedWorkUiState,
    onBack: () -> Unit,
    onOpenVolume: (AndroidDownloadRecord) -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Scaffold(
        modifier = modifier.testTag("downloads-work"),
        containerColor = theme.colors.canvas,
        topBar = { TopAppBar(title = { Text(state.work?.title ?: stringResource(R.string.downloads_title)) }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.navigate_back)) } }) },
    ) { padding ->
        val work = state.work
        if (state.isLoading) ContentAreaMessage(stringResource(R.string.content_loading_title), stringResource(R.string.downloads_loading), modifier = Modifier.padding(padding), loading = true)
        else if (work == null) ContentAreaMessage(stringResource(R.string.downloads_unavailable_title), stringResource(R.string.downloads_unavailable_message), modifier = Modifier.padding(padding))
        else LazyColumn(Modifier.fillMaxSize().padding(padding)) {
            item { Text(work.author, color = theme.colors.textSecondary, modifier = Modifier.padding(theme.spacing.three)) }
            work.mediaVersions.forEach { mediaVersion ->
                item(key = "media-${mediaVersion.mediaVersionId}") {
                    MediaVersionHeader(mediaVersion)
                }
                items(mediaVersion.volumes, key = AndroidDownloadRecord::volumeId) { volume ->
                    Row(
                        Modifier.fillMaxWidth().clickable { onOpenVolume(volume) }.padding(horizontal = theme.spacing.four, vertical = theme.spacing.two),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(volume.volumeTitle, style = theme.typography.headline)
                            Text("${volume.format} · ${formatBytes(volume.expectedBytes)}", color = theme.colors.textSecondary)
                        }
                        Icon(Icons.Outlined.CheckCircle, stringResource(R.string.downloads_offline_available), tint = theme.colors.brandAccent)
                    }
                    HorizontalDivider(color = theme.colors.divider)
                }
            }
        }
    }
}

@Composable
private fun MediaVersionHeader(mediaVersion: DownloadedMediaVersionGroup) {
    val theme = WarmPageThemeValues
    Column(Modifier.fillMaxWidth().padding(horizontal = theme.spacing.three, vertical = theme.spacing.one)) {
        Text(mediaKindLabel(mediaVersion.mediaKind), style = theme.typography.sectionTitle)
        Text(
            pluralStringResource(
                R.plurals.downloads_media_version_summary,
                mediaVersion.volumes.size,
                mediaVersion.volumes.size,
                formatBytes(mediaVersion.totalBytes),
            ),
            color = theme.colors.textSecondary,
            style = theme.typography.caption,
        )
    }
}

@Composable
private fun mediaKindLabel(mediaKind: String): String = stringResource(
    when (mediaKind.uppercase()) {
        "COMIC" -> R.string.media_comic
        "AUDIOBOOK" -> R.string.media_audiobook
        else -> R.string.media_ebook
    },
)

@Composable private fun SectionTitle(resource: Int) = Text(stringResource(resource), style = WarmPageThemeValues.typography.sectionTitle, modifier = Modifier.padding(horizontal = WarmPageThemeValues.spacing.three))

@Composable
private fun ActiveRow(record: AndroidDownloadRecord, onCancel: ((String) -> Unit)?) {
    val theme = WarmPageThemeValues
    val progress = if (record.expectedBytes == 0L) 0f else record.transferredBytes.toFloat() / record.expectedBytes
    val animatedProgress = rememberForwardProgress(progress, progressIdentity = record.volumeId)
    Column(Modifier.padding(horizontal = theme.spacing.three), verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        Row(verticalAlignment = Alignment.CenterVertically) { Icon(Icons.Outlined.CloudDownload, null); Text(record.workTitle, Modifier.padding(start = theme.spacing.one).weight(1f)); Text("${(progress * 100).toInt()}%") }
        Text(
            stringResource(R.string.downloads_task_context, mediaKindLabel(record.mediaKind), record.volumeTitle),
            color = theme.colors.textSecondary,
        )
        LinearProgressIndicator(progress = { animatedProgress }, modifier = Modifier.fillMaxWidth().height(4.dp), color = theme.colors.brandAccent, trackColor = theme.colors.divider)
        if (onCancel != null) {
            TextButton(onClick = { onCancel(record.volumeId) }) { Text(stringResource(R.string.cancel_action)) }
        }
    }
}

@Composable
private fun DownloadedWorkRow(work: DownloadedWorkGroup, onOpenWork: (String) -> Unit) {
    val theme = WarmPageThemeValues
    Row(Modifier.fillMaxWidth().clickable { onOpenWork(work.workId) }.padding(horizontal = theme.spacing.three, vertical = theme.spacing.two), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(work.title, style = theme.typography.headline)
            Text(
                pluralStringResource(
                    R.plurals.downloads_work_summary,
                    work.volumes.size,
                    work.volumes.size,
                    formatBytes(work.totalBytes),
                ),
                color = theme.colors.textSecondary,
            )
        }
        Icon(Icons.Outlined.CheckCircle, stringResource(R.string.downloads_offline_available), tint = theme.colors.brandAccent)
    }
    HorizontalDivider(color = theme.colors.divider)
}

@Composable
private fun FailedRow(
    record: AndroidDownloadRecord,
    onRetry: (() -> Unit)?,
    onRemove: (() -> Unit)?,
) {
    val theme = WarmPageThemeValues
    Row(Modifier.fillMaxWidth().padding(horizontal = theme.spacing.three, vertical = theme.spacing.two), verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Outlined.ErrorOutline, null, tint = androidx.compose.material3.MaterialTheme.colorScheme.error)
        Column(Modifier.padding(start = theme.spacing.two).weight(1f)) {
            Text(record.workTitle)
            Text(
                stringResource(R.string.downloads_task_context, mediaKindLabel(record.mediaKind), record.volumeTitle),
                color = theme.colors.textSecondary,
            )
            Text(downloadFailureSummary(record.errorCode), color = theme.colors.textSecondary)
            if (onRetry != null && onRemove != null) Row {
                TextButton(onClick = onRetry) { Text(stringResource(R.string.retry_action)) }
                TextButton(onClick = onRemove) { Text(stringResource(R.string.downloads_remove_action)) }
            }
        }
    }
}

@Composable
private fun downloadFailureSummary(errorCode: String?): String = stringResource(
    when (errorCode) {
        "DOWNLOAD_INTERRUPTED" -> R.string.downloads_failed_interrupted
        "INSUFFICIENT_SPACE" -> R.string.downloads_failed_storage
        "NETWORK_UNAVAILABLE", "TIMEOUT", "SERVICE_UNAVAILABLE", "SERVER_FAILURE" -> R.string.downloads_failed_network
        else -> R.string.downloads_failed_generic
    },
)

private fun formatBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024L * 1024L -> "%.1f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
    bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
    else -> "%.1f KB".format(bytes / 1024.0)
}
