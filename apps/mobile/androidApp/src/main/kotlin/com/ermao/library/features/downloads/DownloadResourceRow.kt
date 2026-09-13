package com.ermao.library.features.downloads

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Pause
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Checkbox
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.platform.LocalConfiguration
import java.text.NumberFormat
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.downloads.DownloadRecord as AndroidDownloadRecord
import com.ermao.library.features.downloads.downloadFailureMessage
import com.ermao.library.shared.modules.downloads.DownloadManagementAction
import com.ermao.library.shared.modules.downloads.DownloadManagementResource
import com.ermao.library.ui.components.WarmPageIconAction
import com.ermao.library.ui.theme.WarmPageThemeValues

@Composable
fun DownloadResourceRow(
    resourceId: String,
    resourceTitle: String,
    format: String,
    sizeBytes: Long,
    management: DownloadManagementResource,
    record: AndroidDownloadRecord?,
    depth: Int,
    selectionMode: Boolean,
    selected: Boolean,
    isSubmitting: Boolean,
    onToggleSelection: () -> Unit,
    onSubmitAction: (DownloadManagementAction) -> Unit,
    onRequestRemoval: () -> Unit,
    onOpenDownloaded: (AndroidDownloadRecord) -> Unit,
    modifier: Modifier = Modifier,
    displayTitle: String = resourceTitle,
) {
    val theme = WarmPageThemeValues
    val rowAction = management.primaryAction?.takeUnless { it == DownloadManagementAction.Open }
    val actionContent: @Composable RowScope.() -> Unit = {
        rowAction?.let { action ->
            WarmPageIconAction(
                icon = downloadManagementActionIcon(action),
                label = downloadManagementActionLabel(action),
                onClick = { onSubmitAction(action) },
                enabled = !isSubmitting,
                modifier = Modifier.testTag("download-resource-primary-${resourceId}"),
            )
        }
        if (DownloadManagementAction.Remove in management.actions) {
            WarmPageIconAction(
                icon = Icons.Outlined.Delete,
                label = stringResource(R.string.downloads_remove_action),
                onClick = onRequestRemoval,
                enabled = !isSubmitting,
                modifier = Modifier.testTag("download-resource-remove-${resourceId}"),
            )
        }
    }
    val rowModifier = modifier
        .fillMaxWidth()
        .clickable(
            enabled = !isSubmitting && (selectionMode || DownloadManagementAction.Open in management.actions),
            onClick = {
                when {
                    selectionMode && management.selectable -> onToggleSelection()
                    !selectionMode && DownloadManagementAction.Open in management.actions && record != null ->
                        onOpenDownloaded(record)
                }
            },
        )
        .padding(
            start = (if (selectionMode) theme.spacing.one else theme.components.page.compactGutter) + (depth * 20).dp,
            end = theme.components.page.compactGutter,
            top = theme.spacing.one,
            bottom = theme.spacing.one,
        )
    Row(rowModifier, verticalAlignment = Alignment.CenterVertically) {
        if (selectionMode) {
            Checkbox(
                checked = selected,
                onCheckedChange = { onToggleSelection() },
                enabled = management.selectable && !isSubmitting,
                modifier = Modifier.testTag("download-resource-checkbox-${resourceId}"),
            )
        }
        Column(
            Modifier.weight(1f).heightIn(min = theme.components.controls.minimumTouchTarget),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                displayTitle,
                style = theme.typography.body, maxLines = 1, softWrap = false, overflow = TextOverflow.Clip,
                modifier = Modifier.fillMaxWidth().testTag("download-resource-title-${resourceId}")
                    .semantics { contentDescription = resourceTitle },
            )
            Spacer(Modifier.size(theme.spacing.half))
            val showProgress = record != null && management.status in setOf(
                com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Downloading,
                com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Paused,
            )
            val progress = record?.takeIf { it.expectedBytes > 0 }?.let { (it.transferredBytes.toDouble() / it.expectedBytes).coerceIn(0.0, 1.0) }
            val locale = LocalConfiguration.current.locales[0]
            val status = downloadManagementStatusLabel(management.status)
            FlowRow(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.half),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
            ) {
            Text(
                listOfNotNull(
                    format.takeIf(String::isNotBlank),
                    sizeBytes.takeIf { it > 0 }?.let(::formatBytes),
                ).joinToString(" · ") + " ·",
                modifier = Modifier.alignByBaseline(),
                style = theme.typography.caption,
                color = theme.colors.textSecondary,
            )
            Row(modifier = Modifier.alignByBaseline(), verticalAlignment = Alignment.CenterVertically) {
                if (management.status == com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Completed) {
                    Icon(Icons.Outlined.Check, contentDescription = null, tint = theme.colors.textSecondary,
                        modifier = Modifier.size(with(LocalDensity.current) { theme.typography.caption.fontSize.toDp() }))
                    Spacer(Modifier.size(theme.spacing.half))
                }
                Text(
                    if (showProgress && progress != null) "$status · ${NumberFormat.getPercentInstance(locale).format(progress)}" else status,
                    style = theme.typography.caption, color = theme.colors.textSecondary,
                    modifier = Modifier.alignByBaseline().testTag("download-resource-status-${resourceId}"),
                )
            }
            }
            if (showProgress && progress != null) {
                LinearProgressIndicator(
                    progress = { progress.toFloat() },
                    modifier = Modifier.fillMaxWidth().padding(vertical = theme.spacing.half),
                    color = theme.colors.actionAccent,
                    trackColor = theme.colors.divider,
                )
            }
            if (management.status in setOf(
                    com.ermao.library.shared.modules.downloads.DownloadManagementStatus.FailedRetryable,
                    com.ermao.library.shared.modules.downloads.DownloadManagementStatus.FailedTerminal,
                    com.ermao.library.shared.modules.downloads.DownloadManagementStatus.InvalidLocal,
                )
            ) {
                record?.errorCode?.let { code ->
                    Text(downloadFailureMessage(code), style = theme.typography.caption, color = androidx.compose.material3.MaterialTheme.colorScheme.error)
                }
            }
        }
        if (!selectionMode) {
            Row(verticalAlignment = Alignment.CenterVertically) { actionContent() }
        }
    }
    HorizontalDivider(
        color = theme.colors.divider,
        modifier = Modifier.padding(
            start = (if (selectionMode) theme.spacing.one + theme.components.controls.minimumTouchTarget
                else theme.components.page.compactGutter) + (depth * 20).dp,
            end = theme.components.page.compactGutter,
        ),
    )
}

fun downloadManagementActionIcon(action: DownloadManagementAction): ImageVector = when (action) {
    DownloadManagementAction.Open -> Icons.AutoMirrored.Outlined.OpenInNew
    DownloadManagementAction.Download -> Icons.Outlined.Download
    DownloadManagementAction.Pause -> Icons.Outlined.Pause
    DownloadManagementAction.Resume -> Icons.Outlined.PlayArrow
    DownloadManagementAction.Retry -> Icons.Outlined.Refresh
    DownloadManagementAction.Remove -> Icons.Outlined.Delete
}


@Composable
fun downloadManagementStatusLabel(
    status: com.ermao.library.shared.modules.downloads.DownloadManagementStatus,
): String = stringResource(
    when (status) {
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.NotDownloaded -> R.string.multi_download_not_downloaded
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Queued -> R.string.multi_download_queued
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Downloading -> R.string.multi_download_downloading
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Paused -> R.string.multi_download_paused
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Completed -> R.string.multi_download_downloaded
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.InvalidLocal -> R.string.multi_download_invalid_local
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.FailedRetryable -> R.string.multi_download_failed_retryable
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.FailedTerminal -> R.string.multi_download_failed_terminal
        com.ermao.library.shared.modules.downloads.DownloadManagementStatus.Unavailable -> R.string.multi_download_unavailable
    },
)


@Composable
fun downloadManagementActionLabel(action: DownloadManagementAction): String = stringResource(
    when (action) {
        DownloadManagementAction.Download -> R.string.multi_download_download
        DownloadManagementAction.Pause -> R.string.multi_download_pause
        DownloadManagementAction.Resume -> R.string.multi_download_resume
        DownloadManagementAction.Retry -> R.string.multi_download_retry
        DownloadManagementAction.Remove -> R.string.downloads_remove_action
        DownloadManagementAction.Open -> R.string.work_download_open_offline
    },
)


private fun formatBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024L * 1024L -> "%.1f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
    bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
    bytes >= 1024L -> "%.1f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}
