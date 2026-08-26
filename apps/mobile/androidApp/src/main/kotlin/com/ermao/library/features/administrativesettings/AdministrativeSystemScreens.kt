package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Error
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp

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
    var pendingDisable by remember { mutableStateOf(false) }
    AdministrativePage(AdministrativeCopy.Opds, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { initial ->
            var enabled by remember(initial) { mutableStateOf(initial.enabled) }
            var publicAddress by remember(initial) { mutableStateOf(initial.publicBaseUrl) }
            AdministrativeSwitchRow(
                AdministrativeCopy.EnableOpds.text(locale), enabled,
                onCheckedChange = { next -> if (!next && enabled) pendingDisable = true else enabled = next },
                supporting = if (initial.running) AdministrativeCopy.Running.text(locale) else AdministrativeCopy.Disabled.text(locale),
            )
            AdministrativeTextField(publicAddress, { publicAddress = it }, AdministrativeCopy.PublicAddress, locale)
            AdministrativeValueRow(AdministrativeCopy.CatalogAddress.text(locale), initial.catalogUrl, onClick = { onCopy(initial.catalogUrl) })
            Text(
                "1. OPDS 1.2\n2. ${AdministrativeCopy.CatalogAddress.text(locale)}\n3. ${AdministrativeCopy.Enabled.text(locale)}",
                Modifier.padding(16.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            PrimaryAction(AdministrativeCopy.SaveOpds, locale, !state.mutationInFlight && publicAddress.isNotBlank()) {
                onCommand(AdministrativeCommand.SaveOpds(enabled, publicAddress.trim()))
            }
            if (pendingDisable) AdministrativeConfirmDialog(
                AdministrativeCopy.DisableOpdsTitle, AdministrativeCopy.DisableOpdsBody, AdministrativeCopy.DisableService, locale,
                onConfirm = { pendingDisable = false; enabled = false }, onDismiss = { pendingDisable = false },
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
        toolbarActions = { TextButton(enabled = !state.mutationInFlight, onClick = { onCommand(AdministrativeCommand.CreateBackup) }) { Text(AdministrativeCopy.CreateBackup.text(locale)) } },
    ) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.backups.forEach { backup ->
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    Text(backup.fileName, style = MaterialTheme.typography.titleMedium)
                    Text("${if (backup.automatic) AdministrativeCopy.AutomaticallyOrganize.text(locale) else AdministrativeCopy.Manual.text(locale)} · ${backup.sizeLabel} · ${backup.createdAtLabel}")
                    Text("${backup.workCount} ${AdministrativeCopy.Works.text(locale)} · ${backup.progressCount} ${AdministrativeCopy.Progress.text(locale)} · ${backup.sourceCount} ${AdministrativeCopy.LibrarySources.text(locale)}")
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        TextButton({ onCommand(AdministrativeCommand.DownloadBackup(backup.id)) }) { Text(AdministrativeCopy.DownloadFile.text(locale)) }
                        TextButton({ restoreBackup = backup }) { Text(AdministrativeCopy.Restore.text(locale)) }
                        TextButton({ deleteBackup = backup }) { Text(AdministrativeCopy.Delete.text(locale), color = MaterialTheme.colorScheme.error) }
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
                OutlinedTextField(confirmation, { confirmation = it }, label = { Text(AdministrativeCopy.TypeRestore.text(locale)) })
            }
        },
        confirmButton = { TextButton(enabled = confirmation == "RESTORE", onClick = { onConfirm(confirmation) }) { Text(AdministrativeCopy.Restore.text(locale)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(AdministrativeCopy.Cancel.text(locale)) } },
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
                            TextButton(enabled = index > 0, onClick = { items = items.moved(index, index - 1) }) { Text("↑") }
                            TextButton(enabled = index < items.lastIndex, onClick = { items = items.moved(index, index + 1) }) { Text("↓") }
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
            TextButton({ onCommand(AdministrativeCommand.RunHealthCheck) }, enabled = !state.mutationInFlight, modifier = Modifier.fillMaxWidth()) { Text(AdministrativeCopy.RunHealthCheck.text(locale)) }
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
    AdministrativePage(
        AdministrativeCopy.SystemLogs, locale, onBack, modifier,
        toolbarActions = { TextButton({ manageOpen = true }) { Text(AdministrativeCopy.ManageLogCapacity.text(locale)) } },
    ) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            var search by remember(snapshot.query) { mutableStateOf(snapshot.query.search) }
            var level by remember(snapshot.query) { mutableStateOf(snapshot.query.level) }
            AdministrativeTextField(search, { search = it }, AdministrativeCopy.SearchLogs, locale)
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(level == null, { level = null }, { Text(AdministrativeCopy.All.text(locale)) })
                LogLevel.entries.forEach { item -> FilterChip(level == item, { level = item }, { Text(item.copy().text(locale)) }) }
            }
            Text("${snapshot.usedMegabytes} MB / ${snapshot.capacityMegabytes} MB", Modifier.padding(16.dp))
            snapshot.records.filter { record ->
                (search.isBlank() || record.summary.contains(search, true) || record.target.orEmpty().contains(search, true)) && (level == null || record.level == level)
            }.forEach { record ->
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
            TextButton(
                onClick = { onCommand(AdministrativeCommand.ExportLogs(snapshot.query.copy(search = search, level = level))) },
                enabled = !state.mutationInFlight,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(AdministrativeCopy.ExportFilteredLogs.text(locale)) }
        }
    }
    if (manageOpen) ManageLogsDialog(state, locale, onDismiss = { manageOpen = false }, onCommand = onCommand)
}

private fun LogLevel.copy(): AdministrativeCopy = when (this) {
    LogLevel.Information -> AdministrativeCopy.Checking
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
                StepperRow(AdministrativeCopy.CapacityMegabytes.text(locale), capacity, 10..500) { capacity = it }
                TextButton({ clearConfirm = true }) { Text(AdministrativeCopy.ClearInformationAndWarnings.text(locale), color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { TextButton({ onCommand(AdministrativeCommand.SaveLogCapacity(capacity)); onDismiss() }) { Text(AdministrativeCopy.SaveCapacity.text(locale)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(AdministrativeCopy.Cancel.text(locale)) } },
    )
    if (clearConfirm) AdministrativeConfirmDialog(
        AdministrativeCopy.ConfirmClearLogs, AdministrativeCopy.ConfirmClearLogsBody, AdministrativeCopy.Delete, locale,
        onConfirm = { clearConfirm = false; onDismiss(); onCommand(AdministrativeCommand.ClearInformationalLogs) },
        onDismiss = { clearConfirm = false },
    )
}
