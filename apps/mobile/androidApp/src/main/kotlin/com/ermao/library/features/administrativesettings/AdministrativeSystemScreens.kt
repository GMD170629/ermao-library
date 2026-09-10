package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material3.TextButton
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import com.ermao.library.ui.components.SettingsTextField
import com.ermao.library.shared.modules.administrativesettings.createOpdsEditState
import com.ermao.library.shared.modules.administrativesettings.opdsFocusCommitDelayMilliseconds
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Backup
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.DeleteSweep
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Error
import androidx.compose.material.icons.outlined.KeyboardArrowDown
import androidx.compose.material.icons.outlined.KeyboardArrowUp
import androidx.compose.material.icons.outlined.MonitorHeart
import androidx.compose.material.icons.outlined.Restore
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.components.SettingsTextField
import com.ermao.library.ui.components.WarmSettingsEmptyState
import com.ermao.library.ui.components.WarmSettingsFilterBar
import com.ermao.library.ui.components.WarmSettingsFilterOption
import com.ermao.library.ui.components.WarmSettingsInlineMessage

@Composable
fun OpdsScreen(
    state: AdministrativePageState<OpdsSnapshot>,
    locale: AdministrativeLocale,
    onCopy: (String) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(title = AdministrativeCopy.Opds, locale = locale, onBack = onBack, modifier = modifier) {
        PageStateContent(state, locale, onRetry) { confirmed ->
            var editor by remember { mutableStateOf(createOpdsEditState(confirmed.enabled, confirmed.publicBaseUrl)) }
            var addressShown by remember { mutableStateOf(false) }
            var addressFocused by remember { mutableStateOf(false) }
            var focusCommit by remember { mutableStateOf<Job?>(null) }
            val scope = rememberCoroutineScope()
            val focusManager = LocalFocusManager.current
            val busy = editor.isSubmitting || state.mutationInFlight

            LaunchedEffect(state.snapshot, state.failure, state.mutationInFlight, state.phase) {
                if (!state.mutationInFlight) {
                    editor = if (state.failure != null) editor.reject()
                    else if (state.phase == AdministrativePagePhase.Content) editor.accept(confirmed.enabled, confirmed.publicBaseUrl)
                    else editor
                }
                if (confirmed.catalogUrl.isBlank()) addressShown = false
            }

            fun submit() {
                focusCommit?.cancel()
                if (editor.isSubmitting || state.mutationInFlight) return
                val next = editor.beginSubmission()
                val request = next.submission ?: return
                editor = next
                onCommand(AdministrativeCommand.SaveOpds(request.enabled, request.publicBaseUrl))
            }

            fun commitAfterFocusLoss() {
                if (editor.isSubmitting) return
                focusCommit?.cancel()
                focusCommit = scope.launch {
                    delay(opdsFocusCommitDelayMilliseconds())
                    focusCommit = null
                    submit()
                }
            }

            AdministrativeSwitchRow(
                AdministrativeCopy.EnableOpds.text(locale), editor.draft.enabled,
                onCheckedChange = { next ->
                    focusCommit?.cancel()
                    editor = editor.changeEnabled(next)
                    submit()
                    focusManager.clearFocus()
                },
                enabled = !busy,
            )
            SettingsTextField(
                value = editor.draft.publicBaseUrl,
                onValueChange = { editor = editor.editAddress(it) },
                label = AdministrativeCopy.PublicAddress.text(locale),
                enabled = !busy,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { submit(); focusManager.clearFocus() }),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)
                    .onFocusChanged { focus ->
                        val lostFocus = addressFocused && !focus.isFocused
                        addressFocused = focus.isFocused
                        if (focus.isFocused) focusCommit?.cancel()
                        if (lostFocus) commitAfterFocusLoss()
                    },
            )
            if (confirmed.catalogUrl.isNotBlank()) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(AdministrativeCopy.CatalogAddress.text(locale), modifier = Modifier.weight(1f))
                    IconButton(onClick = { addressShown = true }) {
                        Icon(Icons.Outlined.Visibility, contentDescription = AdministrativeCopy.ViewCatalogAddress.text(locale))
                    }
                    IconButton(onClick = { onCopy(confirmed.catalogUrl) }) {
                        Icon(Icons.Outlined.ContentCopy, contentDescription = AdministrativeCopy.CopyCatalogAddress.text(locale))
                    }
                }
            }
            WarmSettingsInlineMessage(
                (if (confirmed.catalogUrl.isNotBlank()) AdministrativeCopy.OpdsInstructions else AdministrativeCopy.OpdsEnableHint).text(locale),
            )
            if (addressShown) AlertDialog(
                onDismissRequest = { addressShown = false },
                title = { Text(AdministrativeCopy.CatalogAddress.text(locale)) },
                text = { SelectionContainer { Text(confirmed.catalogUrl) } },
                confirmButton = { TextButton(onClick = { addressShown = false }) { Text(AdministrativeCopy.Close.text(locale)) } },
            )
        }
    }
}

@Composable
fun BackupsScreen(
    state: AdministrativePageState<BackupsSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var restoreBackup by remember { mutableStateOf<BackupRecord?>(null) }
    var deleteBackup by remember { mutableStateOf<BackupRecord?>(null) }
    AdministrativePage(
        AdministrativeCopy.DataAndBackups, locale, onBack, modifier,
        toolbarActions = { OutlinedButton(enabled = !state.mutationInFlight, onClick = { onCommand(AdministrativeCommand.CreateBackup) }) {
            Icon(Icons.Outlined.Backup, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(AdministrativeCopy.CreateBackup.text(locale)) } },
    ) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.backups.forEach { backup ->
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    Text(backup.fileName, style = MaterialTheme.typography.titleMedium)
                    Text("${if (backup.automatic) AdministrativeCopy.AutomaticallyOrganize.text(locale) else AdministrativeCopy.Manual.text(locale)} · ${backup.sizeLabel} · ${backup.createdAtLabel}")
                    Text("${backup.workCount} ${AdministrativeCopy.Works.text(locale)} · ${backup.progressCount} ${AdministrativeCopy.Progress.text(locale)} · ${backup.sourceCount} ${AdministrativeCopy.LibrarySources.text(locale)}")
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        OutlinedButton({ onCommand(AdministrativeCommand.DownloadBackup(backup.id)) }) {
                            Icon(Icons.Outlined.Download, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                            Text(AdministrativeCopy.DownloadFile.text(locale)) }
                        OutlinedButton({ restoreBackup = backup }) {
                            Icon(Icons.Outlined.Restore, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                            Text(AdministrativeCopy.Restore.text(locale)) }
                        OutlinedButton({ deleteBackup = backup }) {
                            Icon(Icons.Outlined.Delete, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                            Text(AdministrativeCopy.Delete.text(locale), color = MaterialTheme.colorScheme.error) }
                    }
                }
                AdministrativeDivider()
            }
        }
    }
    restoreBackup?.let { backup -> RestoreBackupDialog(backup, locale, onDismiss = { restoreBackup = null }) { confirmation ->
        restoreBackup = null
        onCommand(AdministrativeCommand.RestoreBackup(backup.id, confirmation))
    } }
    deleteBackup?.let { backup -> AdministrativeConfirmDialog(
        AdministrativeCopy.DeleteBackupTitle, AdministrativeCopy.DeleteBackupBody, AdministrativeCopy.DeleteBackup, locale,
        onConfirm = { deleteBackup = null; onCommand(AdministrativeCommand.DeleteBackup(backup.id)) }, onDismiss = { deleteBackup = null },
    ) }
}

@Composable
private fun RestoreBackupDialog(
    backup: BackupRecord,
    locale: AdministrativeLocale,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var confirmation by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(AdministrativeCopy.RestoreBackup.text(locale)) },
        text = {
            Column {
                Text(backup.fileName)
                Text(AdministrativeCopy.RestoreWarning.text(locale), color = MaterialTheme.colorScheme.error)
                SettingsTextField(
                    value = confirmation,
                    onValueChange = { confirmation = it },
                    label = AdministrativeCopy.TypeRestore.text(locale),
                )
            }
        },
        confirmButton = { OutlinedButton(enabled = confirmation == "RESTORE", onClick = { onConfirm(confirmation) }) {
            Icon(Icons.Outlined.Restore, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(AdministrativeCopy.Restore.text(locale)) } },
        dismissButton = { OutlinedButton(onClick = onDismiss) {
            Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(AdministrativeCopy.Cancel.text(locale)) } },
    )
}

@Composable
fun DetailOrderScreen(
    state: AdministrativePageState<DetailOrderSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var confirmReset by remember { mutableStateOf(false) }
    AdministrativePage(AdministrativeCopy.WorkDetailOrder, locale, onBack, modifier) {
        Text(AdministrativeCopy.HiddenEmptySections.text(locale), Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        PageStateContent(state, locale, onRetry) { initial ->
            var items by remember(initial) { mutableStateOf(initial.items) }
            items.forEachIndexed { index, section ->
                ListItem(
                    headlineContent = { Text(section.label) },
                    leadingContent = { Text("${index + 1}") },
                    trailingContent = {
                        Row {
                            IconButton(enabled = index > 0, onClick = { items = items.moved(index, index - 1) }) {
                        Icon(Icons.Outlined.KeyboardArrowUp, contentDescription = AdministrativeCopy.MoveUp.text(locale))
                    }
                            IconButton(enabled = index < items.lastIndex, onClick = { items = items.moved(index, index + 1) }) {
                        Icon(Icons.Outlined.KeyboardArrowDown, contentDescription = AdministrativeCopy.MoveDown.text(locale))
                    }
                        }
                    },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                )
                AdministrativeDivider()
            }
            Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                androidx.compose.material3.OutlinedButton({ confirmReset = true }, modifier = Modifier.weight(1f)) { Text(AdministrativeCopy.RestoreDefaults.text(locale)) }
                androidx.compose.material3.Button({ onCommand(AdministrativeCommand.SaveDetailOrder(items.map(DetailSection::id))) }, enabled = !state.mutationInFlight, modifier = Modifier.weight(1f)) { Text(AdministrativeCopy.SaveOrder.text(locale)) }
            }
            if (confirmReset) AdministrativeConfirmDialog(
                AdministrativeCopy.RestoreDefaultsTitle, AdministrativeCopy.RestoreDefaultsBody, AdministrativeCopy.RestoreDefaults, locale,
                onConfirm = { confirmReset = false; items = initial.items }, onDismiss = { confirmReset = false },
            )
        }
    }
}

@Composable
fun HealthScreen(
    state: AdministrativePageState<HealthSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.SystemHealth, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            ListItem(
                headlineContent = { Text("${AdministrativeCopy.LastChecked.text(locale)} ${snapshot.startedAtLabel ?: AdministrativeCopy.NotAvailable.text(locale)}") },
                supportingContent = { Text("${snapshot.healthyCount} / ${snapshot.totalCount} ${AdministrativeCopy.Healthy.text(locale)}") },
                colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
            )
            OutlinedButton({ onCommand(AdministrativeCommand.RunHealthCheck) }, enabled = !state.mutationInFlight, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Outlined.MonitorHeart, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(AdministrativeCopy.RunHealthCheck.text(locale)) }
            HealthGroup.entries.forEach { group ->
                AdministrativeSection(group.copy(), locale)
                snapshot.checks.filter { it.group == group }.forEach { check ->
                    ListItem(
                        headlineContent = { Text(check.label) },
                        supportingContent = check.detail?.let { ({ Text(it) }) },
                        leadingContent = { Icon(check.status.icon(), null, tint = check.status.color()) },
                        trailingContent = { Text(check.status.copy().text(locale)) },
                        colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                    )
                    AdministrativeDivider()
                }
            }
        }
    }
}

private fun HealthGroup.copy(): AdministrativeCopy = when (this) {
    HealthGroup.StorageAndDatabase -> AdministrativeCopy.DataAndBackups
    HealthGroup.BackgroundQueues -> AdministrativeCopy.Queue
    HealthGroup.FeatureConfiguration -> AdministrativeCopy.SaveConfiguration
}

private fun HealthStatus.copy(): AdministrativeCopy = when (this) {
    HealthStatus.Healthy -> AdministrativeCopy.Healthy
    HealthStatus.Warning -> AdministrativeCopy.Warning
    HealthStatus.Checking -> AdministrativeCopy.Checking
    HealthStatus.Failed -> AdministrativeCopy.Failed
}

private fun HealthStatus.icon() = when (this) {
    HealthStatus.Healthy -> Icons.Outlined.CheckCircle
    HealthStatus.Warning -> Icons.Outlined.Warning
    HealthStatus.Checking -> Icons.Outlined.CheckCircle
    HealthStatus.Failed -> Icons.Outlined.Error
}

@Composable
private fun HealthStatus.color() = when (this) {
    HealthStatus.Failed -> MaterialTheme.colorScheme.error
    HealthStatus.Warning -> MaterialTheme.colorScheme.tertiary
    else -> MaterialTheme.colorScheme.primary
}

@Composable
fun LogsScreen(
    state: AdministrativePageState<LogsSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var manageOpen by remember { mutableStateOf(false) }
    val query = state.snapshot?.query
    var search by remember(query) { mutableStateOf(query?.search.orEmpty()) }
    var level by remember(query) { mutableStateOf(query?.level) }
    AdministrativePage(
        AdministrativeCopy.SystemLogs, locale, onBack, modifier,
        toolbarActions = { OutlinedButton({ manageOpen = true }) {
            Icon(Icons.Outlined.Settings, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(AdministrativeCopy.ManageLogCapacity.text(locale)) } },
        tabs = {
            if (state.snapshot != null) {
                WarmSettingsFilterBar(
                    options = listOf(
                        WarmSettingsFilterOption<LogLevel?>(null, AdministrativeCopy.All.text(locale)),
                    ) + LogLevel.entries.map { item ->
                        WarmSettingsFilterOption<LogLevel?>(item, item.copy().text(locale))
                    },
                    selected = level,
                    onSelect = { level = it },
                    modifier = Modifier.testTag("administrative-log-filters"),
                )
            }
        },
    ) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            AdministrativeTextField(search, { search = it }, AdministrativeCopy.SearchLogs, locale, textAlign = TextAlign.Start)
            Text("${snapshot.usedMegabytes} MB / ${snapshot.capacityMegabytes} MB", Modifier.padding(16.dp))
            val filteredRecords = snapshot.records.filter { record ->
                (search.isBlank() || record.summary.contains(search, true) || record.target.orEmpty().contains(search, true)) && (level == null || record.level == level)
            }
            if (filteredRecords.isEmpty()) {
                WarmSettingsEmptyState(
                    title = AdministrativeCopy.Empty.text(locale),
                    message = AdministrativeCopy.SearchLogs.text(locale),
                )
            }
            filteredRecords.forEach { record ->
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(record.timestampLabel, style = MaterialTheme.typography.bodySmall)
                        Text(record.level.copy().text(locale), color = record.level.color())
                    }
                    Text("${record.source} · ${record.summary}")
                    record.correlationId?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    record.target?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                }
                AdministrativeDivider()
            }
            OutlinedButton(
                onClick = { onCommand(AdministrativeCommand.ExportLogs(snapshot.query.copy(search = search, level = level))) },
                enabled = !state.mutationInFlight,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Outlined.Download, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(AdministrativeCopy.ExportFilteredLogs.text(locale)) }
        }
    }
    if (manageOpen) ManageLogsDialog(state, locale, onDismiss = { manageOpen = false }, onCommand = onCommand)
}

private fun LogLevel.copy(): AdministrativeCopy = when (this) {
    LogLevel.Information -> AdministrativeCopy.Information
    LogLevel.Warning -> AdministrativeCopy.Warning
    LogLevel.Error -> AdministrativeCopy.Failed
}

@Composable
private fun LogLevel.color() = when (this) {
    LogLevel.Error -> MaterialTheme.colorScheme.error
    LogLevel.Warning -> MaterialTheme.colorScheme.tertiary
    LogLevel.Information -> MaterialTheme.colorScheme.primary
}

@Composable
private fun ManageLogsDialog(
    state: AdministrativePageState<LogsSnapshot>,
    locale: AdministrativeLocale,
    onDismiss: () -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
) {
    var capacity by remember(state.snapshot) { mutableIntStateOf(state.snapshot?.capacityMegabytes ?: 50) }
    var clearConfirm by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(AdministrativeCopy.ManageLogCapacity.text(locale)) },
        text = {
            Column {
                StepperRow(AdministrativeCopy.CapacityMegabytes.text(locale), locale, capacity, 10..500) { capacity = it }
                OutlinedButton({ clearConfirm = true }) {
                    Icon(Icons.Outlined.DeleteSweep, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(AdministrativeCopy.ClearInformationAndWarnings.text(locale), color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { OutlinedButton({ onCommand(AdministrativeCommand.SaveLogCapacity(capacity)); onDismiss() }) {
            Icon(Icons.Outlined.Check, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(AdministrativeCopy.SaveCapacity.text(locale)) } },
        dismissButton = { OutlinedButton(onClick = onDismiss) {
            Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(AdministrativeCopy.Cancel.text(locale)) } },
    )
    if (clearConfirm) AdministrativeConfirmDialog(
        AdministrativeCopy.ConfirmClearLogs, AdministrativeCopy.ConfirmClearLogsBody, AdministrativeCopy.Delete, locale,
        onConfirm = { clearConfirm = false; onDismiss(); onCommand(AdministrativeCommand.ClearInformationalLogs) },
        onDismiss = { clearConfirm = false },
    )
}
