package com.ermao.library.features.downloads.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import com.ermao.library.R
import com.ermao.library.features.downloads.DownloadResourceRow
import com.ermao.library.features.downloads.downloadManagementItem
import com.ermao.library.features.downloads.downloadManagementStatusLabel
import com.ermao.library.features.downloads.application.DownloadCenterUiState
import com.ermao.library.features.downloads.application.DownloadedBookUiState
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.DownloadedBookGroup
import com.ermao.library.shared.modules.downloads.DownloadManagementAction
import com.ermao.library.shared.modules.downloads.DownloadManagementOutcome
import com.ermao.library.shared.modules.downloads.DownloadManagementPolicy
import com.ermao.library.shared.modules.downloads.DownloadManagementResult
import com.ermao.library.ui.components.*
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.launch
import java.text.NumberFormat

@Composable
fun DownloadCenterScreen(
    state: DownloadCenterUiState, onBack: () -> Unit,
    onQueryChanged: (String) -> Unit, onClearQuery: () -> Unit,
    onOpenBook: (String) -> Unit, onRetry: () -> Unit,
    modifier: Modifier = Modifier, showBackNavigation: Boolean = true,
    cover: @Composable (DownloadedBookGroup) -> Unit = { ContentListCoverPlaceholder() },
) {
    val theme = WarmPageThemeValues
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail, title = stringResource(R.string.downloads_title),
        onBack = onBack.takeIf { showBackNavigation },
        navigationContentDescription = stringResource(R.string.navigate_back),
        modifier = modifier.testTag("downloads-center"),
    ) { padding ->
        when {
            state.isLoading -> DownloadLoading(Modifier.padding(padding))
            state.errorCode != null -> DownloadError(onRetry, Modifier.padding(padding))
            else -> Column(Modifier.fillMaxSize().padding(padding)) {
                WarmPageSearchField(
                    value = state.query, onValueChange = onQueryChanged,
                    placeholder = stringResource(R.string.downloads_search),
                    onClear = onClearQuery, clearLabel = stringResource(R.string.clear_action),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = theme.components.page.compactGutter).testTag("downloads-search"),
                )
                Text(
                    stringResource(R.string.downloads_used_space, downloadBytes(state.totalCompletedBytes)),
                    style = theme.typography.callout, color = theme.colors.textSecondary,
                    modifier = Modifier.padding(theme.components.page.compactGutter).testTag("downloads-storage"),
                )
                LazyColumn(Modifier.weight(1f).testTag("settings-page-scroll")) {
                    if (state.books.isEmpty()) item {
                        WarmSettingsEmptyState(
                            title = stringResource(if (state.query.isBlank()) R.string.downloads_empty else R.string.downloads_search_empty),
                            modifier = Modifier.testTag("settings-empty"),
                        )
                    }
                    items(state.books, key = DownloadedBookGroup::bookId) { book ->
                        DownloadBookRow(book, cover = { cover(book) }) {
                            focusManager.clearFocus()
                            keyboard?.hide()
                            onOpenBook(book.bookId)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DownloadBookRow(book: DownloadedBookGroup, cover: @Composable () -> Unit, onClick: () -> Unit) {
    val theme = WarmPageThemeValues
    val counts = book.resources.map { resource ->
        val record = resource.artifacts.maxBy { it.updatedAtEpochMillis }
        DownloadManagementPolicy.project(downloadManagementItem(record.resourceId, record, false, true)).status
    }.groupingBy { it }.eachCount()
    val numbers = NumberFormat.getIntegerInstance(LocalConfiguration.current.locales[0])
    val summary = counts.entries.sortedBy { it.key.ordinal }.map { (status, count) ->
        "${numbers.format(count)} ${downloadManagementStatusLabel(status)}"
    }.joinToString(" · ")
    ContentListRow(
        title = book.title, cover = cover,
        modifier = Modifier.clickable(onClick = onClick).testTag("settings-row-book-${book.bookId}")
            .padding(horizontal = theme.components.page.compactGutter),
        actions = { WarmPageIconAction(Icons.AutoMirrored.Filled.KeyboardArrowRight,
            stringResource(R.string.downloads_view_resources), onClick) },
    ) {
            if (book.author.isNotBlank()) Text(book.author, style = theme.typography.caption, color = theme.colors.textSecondary)
            Text(pluralStringResource(R.plurals.downloads_resource_count, book.resources.size, book.resources.size) + " · " + summary,
                style = theme.typography.caption, color = theme.colors.textSecondary)
    }
    HorizontalDivider(color = theme.colors.divider, modifier = Modifier.padding(horizontal = theme.components.page.compactGutter))
}

@Composable
fun DownloadedBookScreen(
    state: DownloadedBookUiState, onBack: () -> Unit, onOpenResource: (AndroidDownloadRecord) -> Unit,
    onAction: suspend (DownloadManagementAction, AndroidDownloadRecord) -> DownloadManagementResult,
    onRetry: () -> Unit, modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    var pendingRemoval by remember { mutableStateOf<AndroidDownloadRecord?>(null) }
    var busy by remember { mutableStateOf(false) }
    var actionFailure by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    fun perform(action: DownloadManagementAction, record: AndroidDownloadRecord) {
        if (busy) return
        busy = true
        actionFailure = null
        scope.launch {
            try {
                val result = onAction(action, record)
                if (result.outcome == DownloadManagementOutcome.Failed) actionFailure = result.failureCode ?: "DOWNLOAD_FAILED"
                if (action == DownloadManagementAction.Open && result.outcome == DownloadManagementOutcome.Completed) onOpenResource(record)
            } finally { busy = false }
        }
    }
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail, title = state.book?.title ?: stringResource(R.string.downloads_title),
        onBack = onBack, navigationContentDescription = stringResource(R.string.navigate_back),
        modifier = modifier.testTag("downloads-book"),
    ) { padding ->
        val book = state.book
        when {
            state.isLoading -> DownloadLoading(Modifier.padding(padding))
            state.errorCode != null -> DownloadError(onRetry, Modifier.padding(padding))
            book == null -> WarmSettingsEmptyState(
                title = stringResource(R.string.downloads_unavailable_title), message = stringResource(R.string.downloads_unavailable_message),
                modifier = Modifier.padding(padding).testTag("settings-empty"),
            )
            else -> LazyColumn(Modifier.fillMaxSize().padding(padding).testTag("settings-page-scroll")) {
                item {
                    Text(listOf(book.author, pluralStringResource(R.plurals.downloads_resource_count, book.resources.size, book.resources.size))
                        .filter(String::isNotBlank).joinToString(" · "),
                        style = theme.typography.callout, color = theme.colors.textSecondary,
                        modifier = Modifier.padding(theme.components.page.compactGutter))
                }
                actionFailure?.let { code -> item {
                    Text(downloadFailureSummary(code), color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(theme.components.page.compactGutter).testTag("downloads-action-error"))
                } }
                items(book.artifacts, key = AndroidDownloadRecord::taskId) { record ->
                    val management = DownloadManagementPolicy.project(downloadManagementItem(record.resourceId, record, false, true))
                    DownloadResourceRow(
                        resourceId = record.resourceId, resourceTitle = record.resourceTitle,
                        format = record.format, sizeBytes = record.expectedBytes, management = management, record = record,
                        depth = 0, selectionMode = false, selected = false, isSubmitting = busy, onToggleSelection = {},
                        onSubmitAction = { perform(it, record) }, onRequestRemoval = { pendingRemoval = record },
                        onOpenDownloaded = { perform(DownloadManagementAction.Open, it) },
                        modifier = Modifier.testTag("settings-row-resource-${record.assetId}"),
                        displayTitle = DownloadManagementPolicy.displayTitle(book.title, record.resourceTitle),
                    )
                }
            }
        }
    }
    pendingRemoval?.let { record ->
        AlertDialog(
            onDismissRequest = { pendingRemoval = null }, title = { Text(stringResource(R.string.downloads_remove_title)) },
            text = { Text(stringResource(R.string.downloads_remove_message, record.resourceTitle)) },
            confirmButton = {
                OutlinedButton(onClick = { pendingRemoval = null; perform(DownloadManagementAction.Remove, record) }) {
                    Icon(Icons.Outlined.Delete, null, Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(stringResource(R.string.downloads_remove_action))
                }
            },
            dismissButton = {
                OutlinedButton(onClick = { pendingRemoval = null }) {
                    Icon(Icons.Outlined.Close, null, Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(stringResource(R.string.cancel_action))
                }
            },
        )
    }
}

@Composable
private fun DownloadLoading(modifier: Modifier) = WarmSettingsContentState(
    kind = WarmSettingsContentStateKind.Loading, title = stringResource(R.string.content_loading_title),
    message = stringResource(R.string.downloads_loading), modifier = modifier,
)
@Composable
private fun DownloadError(onRetry: () -> Unit, modifier: Modifier) = WarmSettingsContentState(
    kind = WarmSettingsContentStateKind.Error, title = stringResource(R.string.content_error_title),
    message = stringResource(R.string.downloads_error), actionLabel = stringResource(R.string.retry_action),
    onAction = onRetry, modifier = modifier,
)
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
@Composable
private fun downloadBytes(bytes: Long): String {
    val locale = LocalConfiguration.current.locales[0]
    return when {
        bytes >= 1024L * 1024L * 1024L -> String.format(locale, "%.1f GB", bytes / (1024.0 * 1024.0 * 1024.0))
        bytes >= 1024L * 1024L -> String.format(locale, "%.1f MB", bytes / (1024.0 * 1024.0))
        else -> String.format(locale, "%.1f KB", bytes / 1024.0)
    }
}
