package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.outlined.CreateNewFolder
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
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
import com.ermao.library.ui.components.rememberForwardProgress

@Composable
fun LibrarySourcesScreen(
    state: AdministrativePageState<LibrarySourcesSnapshot>,
    locale: AdministrativeLocale,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(
        AdministrativeCopy.LibrarySources, locale, onBack, modifier,
        toolbarActions = { IconButton({ onNavigate(AdministrativeSettingsRoute.LibrarySourceEdit()) }) { Icon(Icons.Outlined.CreateNewFolder, AdministrativeCopy.AddSource.text(locale)) } },
    ) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            AdministrativeSection(AdministrativeCopy.LibraryRoots, locale)
            snapshot.sources.forEach { source ->
                ListItem(
                    headlineContent = { Text(source.name) },
                    supportingContent = { Text("${source.path}\n${if (source.enabled) AdministrativeCopy.Enabled.text(locale) else AdministrativeCopy.Disabled.text(locale)} · ${source.organizationMode.name}") },
                    leadingContent = { Icon(Icons.Outlined.Folder, null) },
                    trailingContent = { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null) },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                    modifier = Modifier.fillMaxWidth().clickable(role = Role.Button) { onNavigate(AdministrativeSettingsRoute.LibrarySourceEdit(source.id)) },
                )
                AdministrativeDivider()
            }
            AdministrativeSection(AdministrativeCopy.Directory, locale)
            AdministrativeNavigationRow(
                AdministrativeCopy.BrowseDirectory.text(locale),
                AdministrativeCopy.ScanDirectory.text(locale),
                { onNavigate(AdministrativeSettingsRoute.ServerDirectory(path = null, purpose = ServerDirectoryPurpose.ScanDirectory)) },
                Icons.Outlined.Folder,
            )
        }
    }
}

@Composable
fun ServerDirectoryScreen(
    state: AdministrativePageState<ServerDirectorySnapshot>,
    locale: AdministrativeLocale,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onBack: () -> Unit,
    onSelect: (NativeDirectorySelection) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.BrowseDirectory, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            AdministrativeValueRow(AdministrativeCopy.Directory.text(locale), snapshot.path)
            snapshot.errorCode?.let { Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp)) }
            snapshot.children.forEach { child ->
                ListItem(
                    headlineContent = { Text(child.name) },
                    supportingContent = { Text(child.path) },
                    leadingContent = { Icon(Icons.Outlined.Folder, null) },
                    trailingContent = { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null) },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                    modifier = Modifier.fillMaxWidth().clickable(enabled = child.readable, role = Role.Button) {
                        onNavigate(AdministrativeSettingsRoute.ServerDirectory(child.path, snapshot.purpose))
                    },
                )
                AdministrativeDivider()
            }
            PrimaryAction(AdministrativeCopy.Done, locale, snapshot.readable) {
                onSelect(NativeDirectorySelection(snapshot.path, snapshot.name))
            }
        }
    }
}

@Composable
fun LibrarySourceEditScreen(
    state: AdministrativePageState<LibrarySourceEditorSnapshot>,
    locale: AdministrativeLocale,
    selectedPath: String?,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var showDelete by remember { mutableStateOf(false) }
    AdministrativePage(AdministrativeCopy.LibrarySources, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            val source = snapshot.source
            var name by remember(source) { mutableStateOf(source?.name.orEmpty()) }
            var directory by remember(source, selectedPath) {
                mutableStateOf(
                    selectedPath?.let { NativeDirectorySelection(it, it.substringAfterLast('/')) }
                        ?: source?.let { NativeDirectorySelection(it.path, it.path.substringAfterLast('/')) },
                )
            }
            var enabled by remember(source) { mutableStateOf(source?.enabled ?: true) }
            var organizationMode by remember(source) {
                mutableStateOf(source?.organizationMode ?: LibraryOrganizationMode.Flat)
            }
            var ignorePatterns by remember(snapshot) { mutableStateOf(snapshot.ignorePatterns) }
            var ignoreHidden by remember(snapshot) { mutableStateOf(snapshot.ignoreHidden) }
            var minimumFileSize by remember(snapshot) { mutableStateOf(snapshot.minimumFileSizeBytes.toString()) }
            var description by remember(source) { mutableStateOf(source?.description.orEmpty()) }
            AdministrativeTextField(name, { name = it }, AdministrativeCopy.DisplayNameField, locale)
            AdministrativeValueRow(
                AdministrativeCopy.Directory.text(locale),
                directory?.displayName ?: AdministrativeCopy.NotAvailable.text(locale),
                directory?.uri,
                onClick = {
                    onNavigate(
                        AdministrativeSettingsRoute.ServerDirectory(
                            path = directory?.uri,
                            purpose = source?.id?.let(ServerDirectoryPurpose::EditLibrarySource)
                                ?: ServerDirectoryPurpose.CreateLibrarySource,
                        ),
                    )
                },
            )
            AdministrativeSwitchRow(AdministrativeCopy.EnableScanning.text(locale), enabled, { enabled = it })
            EnumChoiceRow(
                AdministrativeCopy.OrganizationMode,
                LibraryOrganizationMode.entries,
                organizationMode,
                { organizationMode = it },
                locale,
            ) {
                when (it) {
                    LibraryOrganizationMode.Flat -> AdministrativeCopy.FlatLayout.text(locale)
                    LibraryOrganizationMode.Volumes -> AdministrativeCopy.VolumesLayout.text(locale)
                    LibraryOrganizationMode.Audiobook -> AdministrativeCopy.AudiobookLayout.text(locale)
                }
            }
            AdministrativeTextField(ignorePatterns, { ignorePatterns = it }, AdministrativeCopy.Filter, locale)
            AdministrativeSwitchRow(AdministrativeCopy.Enabled.text(locale), ignoreHidden, { ignoreHidden = it }, supporting = "ignoreHidden")
            AdministrativeTextField(minimumFileSize, { minimumFileSize = it.filter(Char::isDigit) }, AdministrativeCopy.Progress, locale)
            AdministrativeTextField(description, { description = it }, AdministrativeCopy.About, locale)
            if (source != null) TextButton(
                onClick = { onCommand(AdministrativeCommand.RescanLibrarySource(source.id)) },
                enabled = !state.mutationInFlight,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(AdministrativeCopy.RescanNow.text(locale)) }
            val selectedDirectory = directory
            PrimaryAction(AdministrativeCopy.SaveSource, locale, !state.mutationInFlight && name.isNotBlank() && selectedDirectory != null) {
                onCommand(
                    AdministrativeCommand.SaveLibrarySource(
                        LibrarySourceDraft(
                            source?.id, name.trim(), requireNotNull(selectedDirectory), enabled, organizationMode,
                            ignorePatterns, ignoreHidden, minimumFileSize.toLongOrNull() ?: 0L, description.ifBlank { null },
                        ),
                    ),
                )
            }
            if (source != null) DangerousAction(AdministrativeCopy.DeleteSource, locale, !state.mutationInFlight) { showDelete = true }
            if (showDelete) AdministrativeConfirmDialog(
                AdministrativeCopy.DeleteSourceTitle, AdministrativeCopy.DeleteSourceBody, AdministrativeCopy.DeleteSource, locale,
                onConfirm = { showDelete = false; onCommand(AdministrativeCommand.DeleteLibrarySource(source?.id.orEmpty())) },
                onDismiss = { showDelete = false },
            )
        }
    }
}

@Composable
fun ImportTasksScreen(
    state: AdministrativePageState<ImportTasksSnapshot>,
    locale: AdministrativeLocale,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var filter by remember { mutableStateOf(QueueFilterValue.All) }
    var deleteTask by remember { mutableStateOf<ImportTask?>(null) }
    AdministrativePage(AdministrativeCopy.ImportTasks, locale, onBack, modifier) {
        ListItem(
            headlineContent = { Text(if (state.snapshot?.queueHealthy == true) AdministrativeCopy.QueueHealthy.text(locale) else AdministrativeCopy.Warning.text(locale)) },
            supportingContent = { Text("${state.snapshot?.runningCount ?: 0} ${AdministrativeCopy.Running.text(locale)}") },
            colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
        )
        QueueFilterChips(filter, { filter = it }, locale)
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.tasks.filter { filter.matches(it.status) }.forEach { task ->
                Column(
                    Modifier.fillMaxWidth().clickable(role = Role.Button) {
                        onNavigate(AdministrativeSettingsRoute.ImportTaskDetail(task.id))
                    }.padding(16.dp),
                ) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(task.fileName, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        Text(task.status.copy().text(locale), color = if (task.status == QueueStatus.Failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(task.sourcePath)
                    Text(task.createdAtLabel, style = MaterialTheme.typography.bodySmall)
                    task.progress?.let { progress ->
                        val animatedProgress = rememberForwardProgress(progress, progressIdentity = task.id)
                        LinearProgressIndicator(progress = { animatedProgress }, Modifier.fillMaxWidth().padding(top = 8.dp))
                    }
                    task.statusCode?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        if (task.status == QueueStatus.Failed) TextButton({ onCommand(AdministrativeCommand.RetryImportTask(task.id)) }) { Text(AdministrativeCopy.Retry.text(locale)) }
                        if (task.status in setOf(QueueStatus.Completed, QueueStatus.Failed, QueueStatus.Cancelled)) TextButton({ deleteTask = task }) { Text(AdministrativeCopy.Delete.text(locale)) }
                    }
                }
                AdministrativeDivider()
            }
            TextButton({ onCommand(AdministrativeCommand.RescanAllSources) }, enabled = !state.mutationInFlight, modifier = Modifier.fillMaxWidth()) { Text(AdministrativeCopy.RescanAllSources.text(locale)) }
            TextButton({ onCommand(AdministrativeCommand.ClearCompletedImports) }, enabled = !state.mutationInFlight, modifier = Modifier.fillMaxWidth()) { Text(AdministrativeCopy.ClearCompleted.text(locale)) }
            TextButton({ onNavigate(AdministrativeSettingsRoute.ImportScanJobs) }, modifier = Modifier.fillMaxWidth()) { Text(AdministrativeCopy.ScanJobs.text(locale)) }
        }
    }
    deleteTask?.let { task -> AdministrativeConfirmDialog(
        AdministrativeCopy.DeleteTaskTitle, AdministrativeCopy.DeleteTaskBody, AdministrativeCopy.Delete, locale,
        onConfirm = { deleteTask = null; onCommand(AdministrativeCommand.DeleteImportTask(task.id)) }, onDismiss = { deleteTask = null },
    ) }
}

@Composable
fun ImportTaskDetailScreen(
    state: AdministrativePageState<ImportTaskDetailSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.ImportTaskDetail, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            AdministrativeValueRow(AdministrativeCopy.DisplayName.text(locale), snapshot.task.fileName)
            AdministrativeValueRow(AdministrativeCopy.Directory.text(locale), snapshot.task.sourcePath)
            AdministrativeValueRow(AdministrativeCopy.Progress.text(locale), "${snapshot.processedAssetCount} / ${snapshot.assetCount}")
            AdministrativeValueRow(AdministrativeCopy.Retry.text(locale), snapshot.attempts.toString())
            snapshot.errorSummary?.let { Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp)) }
            if (snapshot.retryable) TextButton(
                onClick = { onCommand(AdministrativeCommand.RetryImportTask(snapshot.task.id)) },
                enabled = !state.mutationInFlight,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(AdministrativeCopy.RetryTask.text(locale)) }
            AdministrativeSection(AdministrativeCopy.ImportTaskLogs, locale)
            snapshot.logs.forEach { log ->
                ListItem(
                    headlineContent = { Text(log.message) },
                    supportingContent = { Text(listOfNotNull(log.level, log.createdAtLabel).joinToString(" · ")) },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                )
                AdministrativeDivider()
            }
        }
    }
}

@Composable
fun ImportScanJobsScreen(
    state: AdministrativePageState<ImportScanJobsSnapshot>,
    locale: AdministrativeLocale,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.ScanJobs, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.jobs.forEach { job ->
                ListItem(
                    headlineContent = { Text(job.rootPath) },
                    supportingContent = { Text("${job.filesScanned} ${AdministrativeCopy.FilesScanned.text(locale)} · ${job.status.copy().text(locale)}") },
                    trailingContent = { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null) },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                    modifier = Modifier.fillMaxWidth().clickable(role = Role.Button) {
                        onNavigate(AdministrativeSettingsRoute.ImportScanJob(job.id))
                    },
                )
                AdministrativeDivider()
            }
        }
    }
}

@Composable
fun ImportScanJobScreen(
    state: AdministrativePageState<ImportScanJobSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.ScanJobs, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            val job = snapshot.job
            AdministrativeValueRow(AdministrativeCopy.Directory.text(locale), job.rootPath)
            AdministrativeValueRow(AdministrativeCopy.FilesScanned.text(locale), job.filesScanned.toString())
            AdministrativeValueRow(AdministrativeCopy.CandidatesFound.text(locale), job.candidatesFound.toString())
            AdministrativeValueRow(AdministrativeCopy.Queued.text(locale), job.queuedCount.toString())
            if (job.active) {
                LinearProgressIndicator(Modifier.fillMaxWidth().padding(16.dp))
                DangerousAction(AdministrativeCopy.CancelTask, locale, !state.mutationInFlight) {
                    onCommand(AdministrativeCommand.CancelImportScan(job.id))
                }
            }
        }
    }
}

private enum class QueueFilterValue { All, Running, Failed }

private fun QueueFilterValue.matches(status: QueueStatus): Boolean = when (this) {
    QueueFilterValue.All -> true
    QueueFilterValue.Running -> status in setOf(QueueStatus.Queued, QueueStatus.Running)
    QueueFilterValue.Failed -> status == QueueStatus.Failed
}

@Composable
private fun QueueFilterChips(value: QueueFilterValue, onSelect: (QueueFilterValue) -> Unit, locale: AdministrativeLocale) {
    Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        QueueFilterValue.entries.forEach { item ->
            val copy = when (item) {
                QueueFilterValue.All -> AdministrativeCopy.All
                QueueFilterValue.Running -> AdministrativeCopy.Running
                QueueFilterValue.Failed -> AdministrativeCopy.Failed
            }
            FilterChip(value == item, { onSelect(item) }, { Text(copy.text(locale)) })
        }
    }
}

@Composable
fun ImportPreferencesScreen(
    state: AdministrativePageState<ImportPreferencesSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.ImportPreferences, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { initial ->
            var extensions by remember(initial) { mutableStateOf(initial.allowedExtensions.joinToString(", ")) }
            var ignorePatterns by remember(initial) { mutableStateOf(initial.ignorePatterns) }
            AdministrativeTextField(extensions, { extensions = it }, AdministrativeCopy.FileFormat, locale)
            AdministrativeTextField(ignorePatterns, { ignorePatterns = it }, AdministrativeCopy.Filter, locale)
            PrimaryAction(AdministrativeCopy.SaveImportPreferences, locale, !state.mutationInFlight) {
                onCommand(AdministrativeCommand.SaveImportPreferences(ImportPreferencesSnapshot(extensions.split(',').map(String::trim).filter(String::isNotBlank), ignorePatterns)))
            }
        }
    }
}

@Composable
internal fun StepperRow(label: String, value: Int, range: IntRange, onChange: (Int) -> Unit) {
    ListItem(
        headlineContent = { Text(label) },
        trailingContent = {
            Row {
                TextButton(onClick = { onChange(value - 1) }, enabled = value > range.first) { Text("−") }
                Text(value.toString(), Modifier.padding(vertical = 12.dp))
                TextButton(onClick = { onChange(value + 1) }, enabled = value < range.last) { Text("+") }
            }
        },
        colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
    )
    AdministrativeDivider()
}
