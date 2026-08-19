package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
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
fun OrganizeQueueScreen(
    state: AdministrativePageState<OrganizeQueueSnapshot>,
    locale: AdministrativeLocale,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.SmartOrganization, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            AdministrativeNavigationRow(
                AdministrativeCopy.OrganizeRuns.text(locale), null,
                { onNavigate(AdministrativeSettingsRoute.OrganizeRuns) },
            )
            ListItem(
                headlineContent = { Text("${snapshot.pendingCount} ${AdministrativeCopy.Items.text(locale)}") },
                colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
            )
            snapshot.tasks.forEach { task ->
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    Text(task.title, style = MaterialTheme.typography.titleMedium)
                    Text(task.subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(task.status.copy().text(locale))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        if (task.status == OrganizeStatus.AwaitingRecognition) {
                            TextButton({ onCommand(AdministrativeCommand.StartRecognition(task.id)) }) { Text(AdministrativeCopy.RecognizeNow.text(locale)) }
                            TextButton({ onCommand(AdministrativeCommand.DeleteOrganizeTask(task.id)) }) { Text(AdministrativeCopy.Delete.text(locale)) }
                        }
                        if (task.status == OrganizeStatus.NeedsConfirmation) {
                            TextButton({ onNavigate(AdministrativeSettingsRoute.OrganizeCandidates) }) { Text(AdministrativeCopy.ViewCandidates.text(locale)) }
                        }
                    }
                }
                AdministrativeDivider()
            }
        }
    }
}

@Composable
fun OrganizeRunsScreen(
    state: AdministrativePageState<OrganizeRunsSnapshot>,
    locale: AdministrativeLocale,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.OrganizeRuns, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.runs.forEach { run ->
                ListItem(
                    headlineContent = { Text("${run.trigger} · ${run.status}") },
                    supportingContent = { Text("${run.completedCount}/${run.queuedCount} · ${run.reviewCount} / ${run.failedCount}") },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                )
                AdministrativeDivider()
            }
        }
    }
}

private fun OrganizeStatus.copy(): AdministrativeCopy = when (this) {
    OrganizeStatus.AwaitingRecognition -> AdministrativeCopy.Queued
    OrganizeStatus.NeedsConfirmation -> AdministrativeCopy.Checking
    OrganizeStatus.Organized -> AdministrativeCopy.Completed
    OrganizeStatus.Failed -> AdministrativeCopy.Failed
}

@Composable
fun OrganizeCandidatesScreen(
    state: AdministrativePageState<OrganizeCandidatesSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.ChooseRecognitionResult, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            var selectedId by remember(snapshot) { mutableStateOf(snapshot.candidates.firstOrNull()?.id) }
            snapshot.candidates.forEach { candidate ->
                ListItem(
                    headlineContent = { Text(candidate.title) },
                    supportingContent = { Text(candidate.author) },
                    trailingContent = { Text("${candidate.confidencePercent}%") },
                    leadingContent = { RadioButton(selectedId == candidate.id, null) },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                    modifier = Modifier.fillMaxWidth().clickable(role = Role.RadioButton) { selectedId = candidate.id },
                )
                AdministrativeDivider()
            }
            TextButton(onClick = onBack, modifier = Modifier.fillMaxWidth()) { Text(AdministrativeCopy.Done.text(locale)) }
        }
    }
}

@Composable
fun RecognitionPolicyScreen(
    state: AdministrativePageState<RecognitionPolicySnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.RecognitionPolicy, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { initial ->
            var scheduled by remember(initial) { mutableStateOf(initial.scheduled) }
            var hours by remember(initial) { mutableIntStateOf(initial.intervalHours) }
            var runAfterImport by remember(initial) { mutableStateOf(initial.runAfterImport) }
            var saveOpf by remember(initial) { mutableStateOf(initial.saveMetadataToOpf) }
            var localFirst by remember(initial) { mutableStateOf(initial.localMetadataFirst) }
            var priority by remember(initial) { mutableStateOf(initial.sourcePriority) }
            var includeUnrecognized by remember(initial) { mutableStateOf(initial.includeUnrecognized) }
            var includeMissing by remember(initial) { mutableStateOf(initial.includeMissingAuthorOrCover) }
            AdministrativeSection(AdministrativeCopy.Policy, locale)
            AdministrativeSwitchRow(AdministrativeCopy.ScheduledRecognition.text(locale), scheduled, { scheduled = it })
            StepperRow(AdministrativeCopy.EveryHours.text(locale), hours, 1..48) { hours = it }
            AdministrativeSwitchRow(AdministrativeCopy.RunAfterImport.text(locale), runAfterImport, { runAfterImport = it })
            AdministrativeSwitchRow(AdministrativeCopy.SaveMetadataToOpf.text(locale), saveOpf, { saveOpf = it })
            if (initial.opfQueueTotal > 0) {
                val progress = initial.opfQueueCompleted.toFloat() / initial.opfQueueTotal.toFloat()
                val animatedProgress = rememberForwardProgress(progress)
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    Text("${initial.opfQueueCompleted} / ${initial.opfQueueTotal}")
                    LinearProgressIndicator(
                        progress = { animatedProgress },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
            AdministrativeSwitchRow(AdministrativeCopy.LocalMetadataFirst.text(locale), localFirst, { localFirst = it })
            AdministrativeSection(AdministrativeCopy.MetadataPriority, locale)
            ReorderableSourceList(priority, locale) { priority = it }
            AdministrativeSection(AdministrativeCopy.RecognitionScope, locale)
            AdministrativeSwitchRow(AdministrativeCopy.IncludeUnrecognized.text(locale), includeUnrecognized, { includeUnrecognized = it })
            AdministrativeSwitchRow(AdministrativeCopy.IncludeMissingMetadata.text(locale), includeMissing, { includeMissing = it })
            PrimaryAction(AdministrativeCopy.SaveRecognitionPolicy, locale, !state.mutationInFlight) {
                onCommand(AdministrativeCommand.SaveRecognitionPolicy(RecognitionPolicyDraft(scheduled, hours, runAfterImport, saveOpf, localFirst, priority, includeUnrecognized, includeMissing)))
            }
        }
    }
}

@Composable
private fun ReorderableSourceList(
    sources: List<MetadataSource>,
    locale: AdministrativeLocale,
    onChange: (List<MetadataSource>) -> Unit,
) {
    sources.forEachIndexed { index, source ->
        ListItem(
            headlineContent = { Text(source.name) },
            leadingContent = { Text("${index + 1}") },
            trailingContent = {
                Row {
                    TextButton(enabled = index > 0, onClick = { onChange(sources.moved(index, index - 1)) }) { Text("↑") }
                    TextButton(enabled = index < sources.lastIndex, onClick = { onChange(sources.moved(index, index + 1)) }) { Text("↓") }
                }
            },
            colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
        )
        AdministrativeDivider()
    }
}

internal fun <T> List<T>.moved(from: Int, to: Int): List<T> = toMutableList().also {
    val item = it.removeAt(from)
    it.add(to, item)
}

@Composable
fun DuplicatesScreen(
    state: AdministrativePageState<DuplicatesSnapshot>,
    locale: AdministrativeLocale,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.DuplicatesAndCategories, locale, onBack, modifier) {
        AdministrativeNavigationRow(
            AdministrativeCopy.OperationHistory.text(locale), null,
            { onNavigate(AdministrativeSettingsRoute.LibraryOperations) },
        )
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.groups.forEach { group ->
                ListItem(
                    headlineContent = { Text("${group.title} · ${group.versions.size}") },
                    supportingContent = { Text("${group.author} · ${group.confidencePercent}%") },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                )
                AdministrativeDivider()
            }
        }
    }
}

@Composable
fun LibraryOperationsScreen(
    state: AdministrativePageState<LibraryOperationsSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.OperationHistory, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.operations.forEach { operation ->
                ListItem(
                    headlineContent = { Text(operation.summary) },
                    supportingContent = { Text("${operation.action} · ${operation.status}") },
                    trailingContent = operation.takeIf { it.undoAvailable }?.let {
                        ({ TextButton(
                            enabled = !state.mutationInFlight,
                            onClick = { onCommand(AdministrativeCommand.UndoLibraryOperation(it.id)) },
                        ) { Text(AdministrativeCopy.Undo.text(locale)) } })
                    },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                )
                AdministrativeDivider()
            }
        }
    }
}

@Composable
private fun CheckboxRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(role = Role.Checkbox) { onCheckedChange(!checked) }) {
        Checkbox(checked, null)
        Text(label, Modifier.padding(top = 12.dp))
    }
}

@Composable
fun CategoryGovernanceScreen(
    state: AdministrativePageState<CategoryGovernanceSnapshot>,
    locale: AdministrativeLocale,
    onReplace: (AdministrativeSettingsRoute) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var selected by remember(state.snapshot) { mutableStateOf(state.snapshot?.entries?.filter(CategoryEntry::selected)?.map(CategoryEntry::id)?.toSet().orEmpty()) }
    var mergeOpen by remember { mutableStateOf(false) }
    var renameEntry by remember { mutableStateOf<CategoryEntry?>(null) }
    var deleteEntry by remember { mutableStateOf<CategoryEntry?>(null) }
    AdministrativePage(AdministrativeCopy.CategoryGovernance, locale, onBack, modifier) {
        Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CategoryKind.entries.forEach { kind ->
                FilterChip(state.snapshot?.kind == kind, { onReplace(AdministrativeSettingsRoute.CategoryGovernance(kind)) }, { Text(kind.copy().text(locale)) })
            }
        }
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.entries.forEach { entry ->
                ListItem(
                    headlineContent = { Text(entry.canonicalName) },
                    supportingContent = { Text(entry.aliases.joinToString() + " · ${entry.workCount} ${AdministrativeCopy.Works.text(locale)}") },
                    leadingContent = { Checkbox(selected.contains(entry.id), null) },
                    trailingContent = {
                        Row {
                            TextButton({ renameEntry = entry }) { Text(AdministrativeCopy.Rename.text(locale)) }
                            TextButton({ deleteEntry = entry }) { Text(AdministrativeCopy.Delete.text(locale)) }
                        }
                    },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                    modifier = Modifier.fillMaxWidth().clickable(role = Role.Checkbox) {
                        selected = if (entry.id in selected) selected - entry.id else selected + entry.id
                    },
                )
                AdministrativeDivider()
            }
            PrimaryAction(AdministrativeCopy.Merge, locale, !state.mutationInFlight && selected.size >= 2) { mergeOpen = true }
            if (mergeOpen) {
                val selectedEntries = snapshot.entries.filter { selected.contains(it.id) }
                var target by remember(selected) { mutableStateOf(selectedEntries.firstOrNull()?.id) }
                AlertDialog(
                    onDismissRequest = { mergeOpen = false },
                    title = { Text(AdministrativeCopy.MergeCategoriesTitle.text(locale)) },
                    text = { Column { selectedEntries.forEach { entry -> ListItem(
                        headlineContent = { Text(entry.canonicalName) },
                        leadingContent = { RadioButton(target == entry.id, null) },
                        modifier = Modifier.clickable(role = Role.RadioButton) { target = entry.id },
                    ) } } },
                    confirmButton = { TextButton(enabled = target != null, onClick = {
                        target?.let { onCommand(AdministrativeCommand.MergeCategories(snapshot.kind, it, selected - it)) }
                        mergeOpen = false
                    }) { Text(AdministrativeCopy.ConfirmMerge.text(locale)) } },
                    dismissButton = { TextButton(onClick = { mergeOpen = false }) { Text(AdministrativeCopy.Cancel.text(locale)) } },
                )
            }
        }
    }
    renameEntry?.let { entry ->
        var name by remember(entry) { mutableStateOf(entry.canonicalName) }
        AlertDialog(
            onDismissRequest = { renameEntry = null },
            title = { Text(AdministrativeCopy.Rename.text(locale)) },
            text = { AdministrativeTextField(name, { name = it }, AdministrativeCopy.NewName, locale) },
            confirmButton = { TextButton(enabled = name.isNotBlank(), onClick = {
                onCommand(AdministrativeCommand.RenameCategory(state.snapshot?.kind ?: CategoryKind.Author, entry.id, name.trim()))
                renameEntry = null
            }) { Text(AdministrativeCopy.Save.text(locale)) } },
            dismissButton = { TextButton(onClick = { renameEntry = null }) { Text(AdministrativeCopy.Cancel.text(locale)) } },
        )
    }
    deleteEntry?.let { entry -> AdministrativeConfirmDialog(
        AdministrativeCopy.DeleteCategory, AdministrativeCopy.DeleteCategoryBody, AdministrativeCopy.Delete, locale,
        onConfirm = {
            onCommand(AdministrativeCommand.DeleteCategory(state.snapshot?.kind ?: CategoryKind.Author, entry.id))
            deleteEntry = null
        },
        onDismiss = { deleteEntry = null },
    ) }
}

private fun CategoryKind.copy(): AdministrativeCopy = when (this) {
    CategoryKind.Author -> AdministrativeCopy.Authors
    CategoryKind.Tag -> AdministrativeCopy.Tags
    CategoryKind.Series -> AdministrativeCopy.Series
}
