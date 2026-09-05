package com.ermao.library.features.downloads.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.ermao.library.features.downloads.application.DownloadCenterUiState
import com.ermao.library.features.downloads.application.DownloadedBookUiState
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.DownloadedBookGroup
import com.ermao.library.features.downloads.model.DownloadedResourceGroup
import com.ermao.library.ui.components.rememberForwardProgress
import com.ermao.library.ui.components.WarmPageSearchField
import com.ermao.library.ui.components.WarmSettingsEmptyState
import com.ermao.library.ui.components.WarmSettingsContentState
import com.ermao.library.ui.components.WarmSettingsContentStateKind
import com.ermao.library.ui.components.WarmSettingsDivider
import com.ermao.library.ui.components.WarmSettingsNavigationRow
import com.ermao.library.ui.components.WarmSettingsScaffold
import com.ermao.library.ui.components.WarmSettingsScaffoldRole
import com.ermao.library.ui.components.WarmSettingsSection
import com.ermao.library.ui.theme.WarmPageThemeValues

@Composable
fun DownloadCenterScreen(
    state: DownloadCenterUiState,
    onBack: () -> Unit,
    onQueryChanged: (String) -> Unit,
    onClearQuery: () -> Unit,
    onOpenBook: (String) -> Unit,
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
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail,
        title = stringResource(R.string.downloads_title),
        onBack = onBack.takeIf { showBackNavigation },
        navigationContentDescription = stringResource(R.string.navigate_back),
        modifier = modifier.testTag("downloads-center"),
    ) { padding ->
        if (state.isLoading) {
            WarmSettingsContentState(
                kind = WarmSettingsContentStateKind.Loading,
                title = stringResource(R.string.content_loading_title),
                message = stringResource(R.string.downloads_loading),
                modifier = Modifier.padding(padding),
            )
        } else if (state.errorCode != null) {
            WarmSettingsContentState(
                kind = WarmSettingsContentStateKind.Error,
                title = stringResource(R.string.content_error_title),
                message = stringResource(R.string.downloads_error),
                actionLabel = stringResource(R.string.retry_action),
                onAction = onRetry,
                modifier = Modifier.padding(padding),
            )
        } else {
            LazyColumn(
                Modifier.fillMaxSize().padding(padding).testTag("settings-page-scroll"),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
            ) {
                item {
                    WarmSettingsSection(stringResource(R.string.downloads_storage)) {
                        Text(
                            stringResource(R.string.downloads_used_space, formatBytes(state.totalCompletedBytes)),
                            style = theme.typography.callout,
                            color = theme.colors.textSecondary,
                            modifier = Modifier.padding(horizontal = theme.spacing.two, vertical = theme.spacing.one),
                        )
                    }
                }
                if (state.active.isNotEmpty()) {
                    item { WarmSettingsSection(stringResource(R.string.downloads_active)) {} }
                    items(state.active, key = AndroidDownloadRecord::taskId) {
                        ActiveRow(it, onCancelDownload.takeIf { allowManagementActions })
                    }
                }
                item {
                    WarmPageSearchField(
                        value = state.query,
                        onValueChange = onQueryChanged,
                        placeholder = stringResource(R.string.downloads_search),
                        onClear = onClearQuery,
                        clearLabel = stringResource(R.string.clear_action),
                        modifier = Modifier.fillMaxWidth().padding(horizontal = theme.spacing.two).testTag("downloads-search"),
                    )
                }
                item { WarmSettingsSection(stringResource(R.string.downloads_completed)) {} }
                if (state.completedBooks.isEmpty()) {
                    item {
                        WarmSettingsEmptyState(
                            title = stringResource(if (state.query.isBlank()) R.string.downloads_empty else R.string.downloads_search_empty),
                            modifier = Modifier.testTag("settings-empty"),
                        )
                    }
                } else {
                    items(state.completedBooks, key = DownloadedBookGroup::bookId) { DownloadedBookRow(it, onOpenBook) }
                }
                if (state.failed.isNotEmpty()) {
                    item { WarmSettingsSection(stringResource(R.string.downloads_failed)) {} }
                    items(state.failed, key = AndroidDownloadRecord::taskId) {
                        FailedRow(
                            it,
                            onRetry = { onRetryDownload(it.resourceId) }.takeIf { allowManagementActions },
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
            text = { Text(stringResource(R.string.downloads_remove_message, record.bookTitle)) },
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

@Composable
fun DownloadedBookScreen(
    state: DownloadedBookUiState,
    onBack: () -> Unit,
    onOpenResource: (AndroidDownloadRecord) -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail,
        title = state.book?.title ?: stringResource(R.string.downloads_title),
        onBack = onBack,
        navigationContentDescription = stringResource(R.string.navigate_back),
        modifier = modifier.testTag("downloads-book"),
    ) { padding ->
        val book = state.book
        if (state.isLoading) {
            WarmSettingsContentState(
                kind = WarmSettingsContentStateKind.Loading,
                title = stringResource(R.string.content_loading_title),
                message = stringResource(R.string.downloads_loading),
                modifier = Modifier.padding(padding),
            )
        } else if (book == null) {
            WarmSettingsEmptyState(
                title = stringResource(R.string.downloads_unavailable_title),
                message = stringResource(R.string.downloads_unavailable_message),
                modifier = Modifier.padding(padding).testTag("settings-empty"),
            )
        } else LazyColumn(Modifier.fillMaxSize().padding(padding).testTag("settings-page-scroll")) {
            item {
                Text(
                    book.author,
                    style = theme.typography.callout,
                    color = theme.colors.textSecondary,
                    modifier = Modifier.padding(theme.components.settings.horizontalInset),
                )
            }
            book.resources.forEach { resource ->
                item(key = "resource-${resource.resourceId}") {
                    ResourceHeader(resource)
                }
                items(resource.artifacts, key = AndroidDownloadRecord::assetId) { record ->
                    WarmSettingsNavigationRow(
                        title = resource.title,
                        summary = "${record.format} · ${formatBytes(record.expectedBytes)}",
                        modifier = Modifier.testTag("settings-row-resource-${record.assetId}"),
                        onClick = { onOpenResource(record) },
                    )
                    WarmSettingsDivider()
                }
            }
        }
    }
}

@Composable
private fun ResourceHeader(resource: DownloadedResourceGroup) {
    val theme = WarmPageThemeValues
    Column(
        Modifier.fillMaxWidth().padding(
            horizontal = theme.components.settings.horizontalInset,
            vertical = theme.components.settings.verticalInset,
        ),
    ) {
        Text(resource.title, style = theme.typography.sectionTitle)
        Text(
            pluralStringResource(
                R.plurals.downloads_resource_summary,
                resource.artifacts.size,
                resource.artifacts.size,
                formatBytes(resource.totalBytes),
            ),
            color = theme.colors.textSecondary,
            style = theme.typography.caption,
        )
    }
}

@Composable
private fun ActiveRow(record: AndroidDownloadRecord, onCancel: ((String) -> Unit)?) {
    val theme = WarmPageThemeValues
    val progress = if (record.expectedBytes == 0L) 0f else record.transferredBytes.toFloat() / record.expectedBytes
    val animatedProgress = rememberForwardProgress(progress, progressIdentity = record.assetId)
    Column(
        Modifier.padding(horizontal = theme.components.settings.horizontalInset),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(record.bookTitle, Modifier.weight(1f), style = theme.typography.body)
            Text("${(progress * 100).toInt()}%", style = theme.typography.label, color = theme.colors.textSecondary)
        }
        Text(
            stringResource(R.string.downloads_task_context, record.resourceTitle, record.format),
            color = theme.colors.textSecondary,
        )
        LinearProgressIndicator(progress = { animatedProgress }, modifier = Modifier.fillMaxWidth().height(4.dp), color = theme.colors.brandAccent, trackColor = theme.colors.divider)
        if (onCancel != null) {
            TextButton(onClick = { onCancel(record.resourceId) }) { Text(stringResource(R.string.cancel_action)) }
        }
    }
}

@Composable
private fun DownloadedBookRow(book: DownloadedBookGroup, onOpenBook: (String) -> Unit) {
    val theme = WarmPageThemeValues
    WarmSettingsNavigationRow(
        title = book.title,
        summary = pluralStringResource(
            R.plurals.downloads_book_summary,
            book.resources.size,
            book.resources.size,
            formatBytes(book.totalBytes),
        ),
        modifier = Modifier.testTag("settings-row-book-${book.bookId}"),
        onClick = { onOpenBook(book.bookId) },
    )
    WarmSettingsDivider()
}

@Composable
private fun FailedRow(
    record: AndroidDownloadRecord,
    onRetry: (() -> Unit)?,
    onRemove: (() -> Unit)?,
) {
    val theme = WarmPageThemeValues
    Row(
        Modifier.fillMaxWidth().padding(
            horizontal = theme.components.settings.horizontalInset,
            vertical = theme.components.settings.verticalInset,
        ),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(record.bookTitle)
            Text(
                stringResource(R.string.downloads_task_context, record.resourceTitle, record.format),
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
internal fun downloadFailureSummary(errorCode: String?): String = stringResource(
    when (errorCode) {
        "DOWNLOAD_INTERRUPTED" -> R.string.downloads_failed_interrupted
        "INSUFFICIENT_SPACE", "DOWNLOAD_INSUFFICIENT_SPACE", "DOWNLOAD_STORAGE_FAILURE" -> R.string.downloads_failed_storage
        "ASSET_VERSION_CHANGED" -> R.string.reader_error_publication_changed
        "NETWORK_UNAVAILABLE", "TIMEOUT", "SERVICE_UNAVAILABLE", "SERVER_FAILURE" -> R.string.downloads_failed_network
        else -> R.string.downloads_failed_generic
    },
)

private fun formatBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024L * 1024L -> "%.1f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
    bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
    else -> "%.1f KB".format(bytes / 1024.0)
}
