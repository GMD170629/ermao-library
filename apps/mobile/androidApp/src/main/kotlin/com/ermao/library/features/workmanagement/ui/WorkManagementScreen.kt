package com.ermao.library.features.workmanagement.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.clickable
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.AutoStories
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.outlined.MoveToInbox
import androidx.compose.material.icons.outlined.Source
import androidx.compose.material.icons.outlined.Splitscreen
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.VolumeContent
import com.ermao.library.features.content.model.WorkDetailContent
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.workmanagement.application.WorkManagementUiState
import com.ermao.library.features.workmanagement.application.WorkManagementViewModel
import com.ermao.library.features.workmanagement.application.WorkManagementCompletion
import com.ermao.library.features.workmanagement.infrastructure.AndroidCoverSelectionReader
import com.ermao.library.features.workmanagement.infrastructure.CoverSelectionResult
import com.ermao.library.shared.modules.workmanagement.domain.ManagedMediaKind
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.VolumeMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkTransferTarget
import com.ermao.library.ui.components.WarmPageNavigationAction
import com.ermao.library.ui.components.WarmPageModalBottomSheet
import com.ermao.library.ui.components.WarmPagePrimaryAction
import com.ermao.library.ui.components.WarmPageScaffold
import com.ermao.library.ui.components.WarmPageTopBarRole
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.launch

sealed interface WorkManagementTarget {
    data object Work : WorkManagementTarget
    data class Volume(val value: VolumeContent) : WorkManagementTarget
}

enum class WorkManagementTask {
    AddSeries,
    EditWork,
    Recognize,
    Cover,
    EditVolume,
    MediaKind,
    Split,
    Transfer,
    Kindle,
    DeleteWork,
    DeleteVolume,
}

@Composable
fun WorkManagementTaskSheet(
    task: WorkManagementTask,
    target: WorkManagementTarget,
    content: WorkDetailContent,
    state: WorkManagementUiState,
    viewModel: WorkManagementViewModel,
    downloadRecordsByVolume: Map<String, AndroidDownloadRecord>,
    workCover: @Composable () -> Unit,
    onDismiss: () -> Unit,
) {
    val volume = (target as? WorkManagementTarget.Volume)?.value
    val download = volume?.let { downloadRecordsByVolume[it.id] }
    val activeDownload = download?.status in setOf(
        AndroidDownloadStatus.Queued,
        AndroidDownloadStatus.Downloading,
        AndroidDownloadStatus.Verifying,
    )
    if (task == WorkManagementTask.DeleteWork) {
        DeleteWorkForm(content, viewModel, onDismiss)
        return
    }
    if (task == WorkManagementTask.DeleteVolume) {
        volume?.let { DeleteVolumeForm(it, activeDownload, viewModel, onDismiss) }
        return
    }
    val theme = WarmPageThemeValues
    val androidContext = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val coverSelectionReader = remember(androidContext) {
        AndroidCoverSelectionReader(androidContext.contentResolver)
    }
    var coverSelectionError by remember(task) { mutableStateOf<Int?>(null) }
    var confirmsCoverRegeneration by remember(task) { mutableStateOf(false) }
    val coverLauncher = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            coroutineScope.launch {
                when (val result = coverSelectionReader.read(uri)) {
                    is CoverSelectionResult.Ready -> {
                        coverSelectionError = null
                        viewModel.uploadCover(result.upload)
                    }
                    CoverSelectionResult.UnsupportedType -> coverSelectionError = R.string.management_cover_unsupported
                    CoverSelectionResult.TooLarge -> coverSelectionError = R.string.management_cover_too_large
                    CoverSelectionResult.Empty,
                    CoverSelectionResult.Unreadable,
                    -> coverSelectionError = R.string.management_cover_unreadable
                }
            }
        }
    }
    WarmPageModalBottomSheet(
        onDismissRequest = { if (!state.busy) onDismiss() },
        skipPartiallyExpanded = true,
        modifier = Modifier.testTag("work-management-task-sheet"),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .imePadding(),
        ) {
            if (state.busy) {
                LinearProgressIndicator(
                    color = theme.colors.brandAccent,
                    trackColor = theme.colors.divider,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = theme.spacing.two, vertical = theme.spacing.one),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(task.titleResource()),
                    style = theme.typography.headline,
                    color = theme.colors.textPrimary,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onDismiss, enabled = !state.busy) {
                    Text(stringResource(R.string.cancel_action))
                }
            }
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f, fill = false)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = theme.spacing.two, vertical = theme.spacing.one),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                state.errorCode?.let {
                    Text(
                        text = stringResource(R.string.management_failed, it),
                        style = theme.typography.callout,
                        color = androidx.compose.material3.MaterialTheme.colorScheme.error,
                    )
                }
                coverSelectionError?.let { errorResource ->
                    Text(
                        text = stringResource(errorResource),
                        style = theme.typography.callout,
                        color = androidx.compose.material3.MaterialTheme.colorScheme.error,
                    )
                }
                when (task) {
                    WorkManagementTask.AddSeries -> EditSeriesForm(content, viewModel)
                    WorkManagementTask.EditWork -> EditWorkForm(content, viewModel)
                    WorkManagementTask.Recognize -> MetadataForm(content, state, viewModel)
                    WorkManagementTask.Cover -> CoverManagement(
                        onChooseCover = { coverLauncher.launch("image/*") },
                        onRegenerateCover = { confirmsCoverRegeneration = true },
                        workCover = workCover,
                    )
                    WorkManagementTask.EditVolume -> volume?.let { EditVolumeForm(it, viewModel) }
                    WorkManagementTask.MediaKind -> volume?.let {
                        MediaKindForm(it, content, activeDownload, viewModel)
                    }
                    WorkManagementTask.Split -> volume?.let { SplitForm(it, activeDownload, viewModel) }
                    WorkManagementTask.Transfer -> volume?.let {
                        TransferForm(it, activeDownload, state, viewModel)
                    }
                    WorkManagementTask.Kindle -> KindleForm(content, volume, state, viewModel)
                    WorkManagementTask.DeleteWork,
                    WorkManagementTask.DeleteVolume,
                    -> Unit
                }
            }
        }
    }
    if (confirmsCoverRegeneration) {
        AlertDialog(
            onDismissRequest = { confirmsCoverRegeneration = false },
            title = { Text(stringResource(R.string.management_regenerate_cover_confirm_title)) },
            text = { Text(stringResource(R.string.management_regenerate_cover_confirm_message)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmsCoverRegeneration = false
                    viewModel.regenerateCover()
                }) { Text(stringResource(R.string.management_regenerate_cover)) }
            },
            dismissButton = {
                TextButton(onClick = { confirmsCoverRegeneration = false }) {
                    Text(stringResource(R.string.cancel_action))
                }
            },
        )
    }
}

private fun WorkManagementTask.titleResource(): Int = when (this) {
    WorkManagementTask.AddSeries -> R.string.work_control_add_series
    WorkManagementTask.EditWork -> R.string.management_edit_work
    WorkManagementTask.Recognize -> R.string.management_metadata
    WorkManagementTask.Cover -> R.string.management_cover
    WorkManagementTask.EditVolume -> R.string.management_edit_volume
    WorkManagementTask.MediaKind -> R.string.management_media_kind
    WorkManagementTask.Split -> R.string.management_split
    WorkManagementTask.Transfer -> R.string.management_transfer
    WorkManagementTask.Kindle -> R.string.management_kindle
    WorkManagementTask.DeleteWork -> R.string.management_delete_work
    WorkManagementTask.DeleteVolume -> R.string.management_delete_volume
}

@Composable
private fun EditSeriesForm(content: WorkDetailContent, viewModel: WorkManagementViewModel) {
    var series by remember { mutableStateOf(content.seriesName.orEmpty()) }
    var seriesIndex by remember { mutableStateOf(content.seriesIndex?.toString().orEmpty()) }
    Field(series, { series = it }, R.string.management_series)
    Field(seriesIndex, { seriesIndex = it }, R.string.management_series_index)
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_save),
        modifier = Modifier.fillMaxWidth(),
        enabled = series.isNotBlank() && (seriesIndex.isBlank() || seriesIndex.toDoubleOrNull() != null),
        onClick = {
            viewModel.updateWork(
                WorkMetadataDraft(
                    content.work.title,
                    content.work.author,
                    content.description.orEmpty(),
                    series,
                    seriesIndex.toDoubleOrNull(),
                    content.tags,
                ),
            )
        },
    )
}

@Composable
private fun EditWorkForm(content: WorkDetailContent, viewModel: WorkManagementViewModel) {
    var title by remember { mutableStateOf(content.work.title) }
    var author by remember { mutableStateOf(content.work.author) }
    var description by remember { mutableStateOf(content.description.orEmpty()) }
    var series by remember { mutableStateOf(content.seriesName.orEmpty()) }
    var seriesIndex by remember { mutableStateOf(content.seriesIndex?.toString().orEmpty()) }
    var tags by remember { mutableStateOf(content.tags.joinToString(", ")) }
    Field(title, { title = it }, R.string.management_title)
    Field(author, { author = it }, R.string.management_author)
    Field(description, { description = it }, R.string.management_description)
    Field(series, { series = it }, R.string.management_series)
    Field(seriesIndex, { seriesIndex = it }, R.string.management_series_index)
    Field(tags, { tags = it }, R.string.management_tags)
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_save),
        modifier = Modifier.fillMaxWidth(),
        enabled = title.isNotBlank() && (seriesIndex.isBlank() || seriesIndex.toDoubleOrNull() != null),
        onClick = {
            viewModel.updateWork(
                WorkMetadataDraft(
                    title, author, description, series.ifBlank { null }, seriesIndex.toDoubleOrNull(),
                    tags.split(',').map(String::trim).filter(String::isNotBlank),
                ),
            )
        },
    )
}

@Composable
private fun MenuButton(
    label: Int,
    enabled: Boolean,
    supportingText: Int,
    icon: ImageVector,
    onClick: () -> Unit,
) {
    val theme = WarmPageThemeValues
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(theme.radii.control),
        border = BorderStroke(1.dp, theme.colors.divider),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = theme.colors.textPrimary),
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp))
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(horizontal = theme.spacing.one),
        ) {
            Text(stringResource(label), style = theme.typography.body)
            Text(
                stringResource(supportingText),
                style = theme.typography.caption,
                color = theme.colors.textSecondary,
            )
        }
    }
}

@Composable
private fun CoverManagement(
    onChooseCover: () -> Unit,
    onRegenerateCover: () -> Unit,
    workCover: @Composable () -> Unit,
) {
    val theme = WarmPageThemeValues
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = theme.spacing.two),
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.width(152.dp)) { workCover() }
    }
    MenuButton(
        label = R.string.management_upload_cover,
        enabled = true,
        supportingText = R.string.management_upload_cover_description,
        icon = Icons.Outlined.Image,
        onClick = onChooseCover,
    )
    MenuButton(
        label = R.string.management_regenerate_cover,
        enabled = true,
        supportingText = R.string.management_regenerate_cover_description,
        icon = Icons.Outlined.Source,
        onClick = onRegenerateCover,
    )
}

@Composable
private fun ReadingStatusForm(
    content: WorkDetailContent,
    viewModel: WorkManagementViewModel,
) {
    val volume = content.allVolumes.firstOrNull { it.selected }
        ?: content.allVolumes.firstOrNull()
    var selected by remember(content.work.id) {
        mutableStateOf(if (content.completed) ManagedReadingStatus.Finished else ManagedReadingStatus.Unread)
    }
    val theme = WarmPageThemeValues
    if (volume == null) {
        Text(
            text = stringResource(R.string.management_no_volume),
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
        )
        return
    }
    Text(
        text = volume.title,
        style = theme.typography.headline,
        color = theme.colors.textPrimary,
        modifier = Modifier.padding(vertical = theme.spacing.one),
    )
    ManagedReadingStatus.entries.forEach { status ->
        val label = if (status == ManagedReadingStatus.Unread) {
            R.string.reading_unread
        } else {
            R.string.reading_finished
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = theme.components.controls.minimumTouchTarget)
                .clickable { selected = status }
                .padding(horizontal = theme.spacing.half),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(selected = selected == status, onClick = { selected = status })
            Text(
                text = stringResource(label),
                style = theme.typography.body,
                color = theme.colors.textPrimary,
            )
        }
    }
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_save),
        modifier = Modifier.fillMaxWidth(),
        onClick = { viewModel.setReadingStatus(volume.id, selected) },
    )
}

@Composable
private fun EditVolumeForm(volume: VolumeContent, viewModel: WorkManagementViewModel) {
    var title by remember { mutableStateOf(volume.title) }
    var index by remember { mutableStateOf(volume.volumeIndex?.toString().orEmpty()) }
    var sortOrder by remember { mutableStateOf(volume.sortOrder.toString()) }
    var publisher by remember { mutableStateOf(volume.publisher.orEmpty()) }
    var language by remember { mutableStateOf(volume.language.orEmpty()) }
    var isbn by remember { mutableStateOf(volume.isbn.orEmpty()) }
    var identifier by remember { mutableStateOf(volume.identifier.orEmpty()) }
    var narrator by remember { mutableStateOf(volume.narrator.orEmpty()) }
    Field(title, { title = it }, R.string.management_title)
    Field(index, { index = it }, R.string.management_volume_index)
    Field(sortOrder, { sortOrder = it }, R.string.management_sort_order)
    Field(publisher, { publisher = it }, R.string.management_publisher)
    Field(language, { language = it }, R.string.management_language)
    Field(isbn, { isbn = it }, R.string.management_isbn)
    Field(identifier, { identifier = it }, R.string.management_identifier)
    Field(narrator, { narrator = it }, R.string.management_narrator)
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_save),
        modifier = Modifier.fillMaxWidth(),
        enabled = title.isNotBlank() && sortOrder.toIntOrNull()?.let { it >= 0 } == true &&
            (index.isBlank() || index.toDoubleOrNull() != null),
        onClick = {
            viewModel.updateVolume(
                volume.id,
                VolumeMetadataDraft(
                    title, index.toDoubleOrNull(), checkNotNull(sortOrder.toIntOrNull()),
                    publisher, language, isbn, identifier, narrator,
                ),
            )
        },
    )
}

@Composable
private fun MetadataForm(
    content: WorkDetailContent,
    state: WorkManagementUiState,
    viewModel: WorkManagementViewModel,
) {
    val kind = (content.allVolumes.firstOrNull { it.selected } ?: content.allVolumes.firstOrNull())
        ?.toManagedMediaKind() ?: ManagedMediaKind.Ebook
    var query by remember { mutableStateOf(content.work.title) }
    var providerId by remember { mutableStateOf("") }
    var candidate by remember { mutableStateOf<MetadataCandidate?>(null) }
    var selectedFields by remember { mutableStateOf<Set<MetadataField>>(emptySet()) }
    var applyToAllVolumes by remember { mutableStateOf(true) }
    LaunchedEffect(kind) { viewModel.loadMetadataProviders(kind) }
    LaunchedEffect(state.metadataProviders) {
        if (providerId.isBlank()) providerId = state.metadataProviders.firstOrNull { it.enabled }?.id.orEmpty()
    }
    Field(query, { query = it }, R.string.management_query)
    state.metadataProviders.forEach { provider ->
        OutlinedButton(
            enabled = provider.enabled,
            onClick = { providerId = provider.id },
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (provider.id == providerId) "✓ ${provider.name}" else provider.name) }
    }
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_search),
        modifier = Modifier.fillMaxWidth(),
        enabled = providerId.isNotBlank() && query.isNotBlank(),
        onClick = { viewModel.searchMetadata(providerId, query) },
    )
    state.metadataCandidates.forEach { value ->
        OutlinedButton(onClick = {
            candidate = value
            selectedFields = value.availableFields()
        }, modifier = Modifier.fillMaxWidth()) {
            Text((if (candidate?.id == value.id) "✓ " else "") + (value.title ?: value.id))
        }
    }
    candidate?.let { selected ->
        selected.availableFields().forEach { field ->
            Row(modifier = Modifier.fillMaxWidth()) {
                Checkbox(
                    checked = field in selectedFields,
                    onCheckedChange = { checked ->
                        selectedFields = if (checked) selectedFields + field else selectedFields - field
                    },
                )
                Text(stringResource(field.labelResource()))
            }
        }
        Row(modifier = Modifier.fillMaxWidth()) {
            Checkbox(checked = applyToAllVolumes, onCheckedChange = { applyToAllVolumes = it })
            Text(stringResource(R.string.management_apply_all_volumes))
        }
        WarmPagePrimaryAction(
            label = stringResource(R.string.management_apply),
            enabled = selectedFields.isNotEmpty(),
            onClick = {
                viewModel.applyMetadata(
                    providerId,
                    selected,
                    selectedFields,
                    content.allVolumes.firstOrNull { it.selected }?.id
                        ?: content.allVolumes.firstOrNull()?.id,
                    applyToAllVolumes = applyToAllVolumes,
                )
            },
            modifier = Modifier.fillMaxWidth(),
        )
    }
    state.metadataMessage?.let { Text(it) }
}

@Composable
private fun MediaKindForm(
    volume: VolumeContent,
    content: WorkDetailContent,
    blocked: Boolean,
    viewModel: WorkManagementViewModel,
) {
    val current = volume.toManagedMediaKind()
    var selected by remember(volume.id) { mutableStateOf(current) }
    val theme = WarmPageThemeValues
    ManagedMediaKind.entries.forEach { kind ->
        val label = when (kind) {
            ManagedMediaKind.Ebook -> R.string.management_ebook
            ManagedMediaKind.Comic -> R.string.management_comic
            ManagedMediaKind.Audiobook -> R.string.management_audiobook
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = theme.components.controls.minimumTouchTarget)
                .clickable(enabled = !blocked) { selected = kind }
                .padding(horizontal = theme.spacing.half),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(selected = selected == kind, enabled = !blocked, onClick = { selected = kind })
            Text(
                text = stringResource(label),
                style = theme.typography.body,
                color = if (blocked) theme.colors.textTertiary else theme.colors.textPrimary,
            )
        }
    }
    if (blocked) {
        Text(
            text = stringResource(R.string.management_active_download_blocked),
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
        )
    }
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_media_kind),
        enabled = !blocked && selected != current,
        modifier = Modifier.fillMaxWidth(),
        onClick = {
            viewModel.reclassifyVolume(volume.id, selected)
        },
    )
}

@Composable
private fun SplitForm(volume: VolumeContent, blocked: Boolean, viewModel: WorkManagementViewModel) {
    var title by remember { mutableStateOf(volume.title) }
    var author by remember { mutableStateOf("") }
    Field(title, { title = it }, R.string.management_title)
    Field(author, { author = it }, R.string.management_author)
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_split),
        enabled = !blocked && title.isNotBlank(),
        onClick = { viewModel.splitVolume(volume.id, title, author.ifBlank { null }) },
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun TransferForm(
    volume: VolumeContent,
    blocked: Boolean,
    state: WorkManagementUiState,
    viewModel: WorkManagementViewModel,
) {
    var query by remember { mutableStateOf("") }
    var selectedTarget by remember { mutableStateOf<WorkTransferTarget?>(null) }
    Field(query, { query = it }, R.string.management_query)
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_search),
        enabled = !blocked,
        onClick = { viewModel.searchTransferTargets(query) },
        modifier = Modifier.fillMaxWidth(),
    )
    state.transferTargets.forEach { target ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 64.dp)
                .clickable(enabled = !blocked) { selectedTarget = target }
                .padding(vertical = WarmPageThemeValues.spacing.half),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(
                selected = selectedTarget?.id == target.id,
                enabled = !blocked,
                onClick = { selectedTarget = target },
            )
            Text(
                text = listOf(target.title, target.author).filter(String::isNotBlank).joinToString(" · "),
                style = WarmPageThemeValues.typography.body,
                color = if (blocked) WarmPageThemeValues.colors.textTertiary else WarmPageThemeValues.colors.textPrimary,
            )
        }
        HorizontalDivider(color = WarmPageThemeValues.colors.divider)
    }
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_move_to_selected_work),
        enabled = !blocked && selectedTarget != null,
        modifier = Modifier.fillMaxWidth(),
        onClick = { selectedTarget?.let { viewModel.transferVolume(volume.id, it) } },
    )
}

@Composable
private fun KindleForm(
    content: WorkDetailContent,
    selectedVolume: VolumeContent?,
    state: WorkManagementUiState,
    viewModel: WorkManagementViewModel,
) {
    LaunchedEffect(Unit) { viewModel.loadKindleSettings() }
    val settings = state.kindleSettings
    val targetVolumes = selectedVolume?.let(::listOf) ?: content.allVolumes
    val files = targetVolumes.flatMap { volume ->
        volume.files.filter { it.path.endsWith(".epub", true) || it.path.endsWith(".pdf", true) }
            .map { volume to it }
    }
    var selectedFileId by remember(selectedVolume?.id, files.map { it.second.id }) {
        mutableStateOf(files.firstOrNull()?.second?.id)
    }
    val theme = WarmPageThemeValues
    if (settings?.ready == true) {
        Text(
            text = stringResource(R.string.management_kindle_ready),
            style = theme.typography.label,
            color = theme.colors.textPrimary,
        )
        Text(
            text = stringResource(
                R.string.management_kindle_addresses,
                settings.recipientEmail,
                settings.senderEmail,
            ),
            style = theme.typography.caption,
            color = theme.colors.textSecondary,
        )
    } else if (settings != null) {
        Text(
            text = stringResource(R.string.management_kindle_not_ready),
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
        )
    }
    if (files.isEmpty()) {
        Text(
            text = stringResource(R.string.management_no_kindle_file),
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
        )
    }
    files.forEach { (volume, file) ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 64.dp)
                .clickable(enabled = settings?.ready == true) { selectedFileId = file.id }
                .padding(vertical = theme.spacing.half),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(
                selected = selectedFileId == file.id,
                enabled = settings?.ready == true,
                onClick = { selectedFileId = file.id },
            )
            Column(Modifier.weight(1f)) {
                Text(
                    text = file.path.substringAfterLast('/'),
                    style = theme.typography.body,
                    color = theme.colors.textPrimary,
                )
                Text(
                    text = "${volume.title} · ${file.displaySize}",
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                )
            }
        }
        HorizontalDivider(color = theme.colors.divider)
    }
    WarmPagePrimaryAction(
        label = stringResource(R.string.management_add_to_kindle_queue),
        enabled = settings?.ready == true && selectedFileId != null,
        onClick = { selectedFileId?.let(viewModel::sendToKindle) },
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun DeleteWorkForm(
    content: WorkDetailContent,
    viewModel: WorkManagementViewModel,
    onCancel: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text(stringResource(R.string.management_delete_work)) },
        text = { Text(stringResource(R.string.management_confirm_delete_work)) },
        confirmButton = {
            TextButton(
                onClick = { viewModel.deleteWork(content.allVolumes.map { it.id }) },
                colors = ButtonDefaults.textButtonColors(
                    contentColor = androidx.compose.material3.MaterialTheme.colorScheme.error,
                ),
            ) { Text(stringResource(R.string.management_delete_work)) }
        },
        dismissButton = {
            TextButton(onClick = onCancel) { Text(stringResource(R.string.cancel_action)) }
        },
    )
}

@Composable
private fun DeleteVolumeForm(
    volume: VolumeContent,
    blocked: Boolean,
    viewModel: WorkManagementViewModel,
    onCancel: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text(stringResource(R.string.management_delete_volume)) },
        text = { Text(stringResource(R.string.management_confirm_delete_volume)) },
        confirmButton = {
            TextButton(
                enabled = !blocked,
                onClick = { viewModel.deleteVolume(volume.id) },
                colors = ButtonDefaults.textButtonColors(
                    contentColor = androidx.compose.material3.MaterialTheme.colorScheme.error,
                ),
            ) { Text(stringResource(R.string.management_delete_volume)) }
        },
        dismissButton = {
            TextButton(onClick = onCancel) { Text(stringResource(R.string.cancel_action)) }
        },
    )
}

@Composable
private fun Field(value: String, onValueChange: (String) -> Unit, label: Int) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(stringResource(label)) },
        modifier = Modifier.fillMaxWidth(),
    )
}

private fun VolumeContent.toManagedMediaKind(): ManagedMediaKind =
    when (suggestedMediaKind?.uppercase()) {
        "COMIC" -> ManagedMediaKind.Comic
        "AUDIOBOOK" -> ManagedMediaKind.Audiobook
        "EBOOK" -> ManagedMediaKind.Ebook
        else -> when {
            readerType.equals("audio", ignoreCase = true) -> ManagedMediaKind.Audiobook
            readerType.equals("comic", ignoreCase = true) -> ManagedMediaKind.Comic
            format.uppercase() in setOf("CBZ", "CBR", "ZIP") -> ManagedMediaKind.Comic
            format.uppercase() in setOf("M4B", "MP3", "M4A", "AUDIO") -> ManagedMediaKind.Audiobook
            else -> ManagedMediaKind.Ebook
        }
    }

private fun MetadataCandidate.availableFields(): Set<MetadataField> = buildSet {
    if (coverUrl != null) add(MetadataField.Cover)
    if (title != null) add(MetadataField.Title)
    if (author != null) add(MetadataField.Author)
    if (description != null) add(MetadataField.Description)
    if (tags.isNotEmpty()) add(MetadataField.Tags)
    if (seriesName != null) add(MetadataField.SeriesName)
    if (publisher != null) add(MetadataField.Publisher)
    if (publishedAt != null) add(MetadataField.PublishedAt)
    if (language != null) add(MetadataField.Language)
    if (isbn != null) add(MetadataField.Isbn)
}

private fun MetadataField.labelResource(): Int = when (this) {
    MetadataField.Cover -> R.string.management_cover
    MetadataField.Title -> R.string.management_title
    MetadataField.Author -> R.string.management_author
    MetadataField.Description -> R.string.management_description
    MetadataField.Tags -> R.string.management_tags_label
    MetadataField.SeriesName -> R.string.management_series
    MetadataField.Publisher -> R.string.management_publisher
    MetadataField.PublishedAt -> R.string.management_published_at
    MetadataField.Language -> R.string.management_language
    MetadataField.Isbn -> R.string.management_isbn
}
