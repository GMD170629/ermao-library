package com.ermao.library.features.workmanagement.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.workmanagement.application.WorkManagementUiState
import com.ermao.library.features.workmanagement.application.WorkManagementViewModel
import com.ermao.library.features.workmanagement.infrastructure.AndroidCoverSelectionReader
import com.ermao.library.features.workmanagement.infrastructure.CoverSelectionResult
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope

sealed interface WorkManagementTarget {
    data object Work : WorkManagementTarget
    data class Resource(val value: ResourceContent) : WorkManagementTarget
}

enum class WorkManagementTask { AddSeries, EditWork, Recognize, Cover, EditVolume, Kindle, Rescan, Delete }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkManagementTaskSheet(
    task: WorkManagementTask,
    target: WorkManagementTarget,
    content: BookDetailContent,
    state: WorkManagementUiState,
    viewModel: WorkManagementViewModel,
    downloadRecordsByResource: Map<String, Any?> = emptyMap(),
    workCover: (@Composable () -> Unit)? = null,
    onDismiss: () -> Unit,
) {
    val resource = when (target) {
        WorkManagementTarget.Work -> content.resources.firstOrNull { it.id == content.selectedResourceId }
            ?: content.resources.firstOrNull()
        is WorkManagementTarget.Resource -> target.value
    }
    val appContext = LocalContext.current.applicationContext
    val scope = rememberCoroutineScope()
    val coverReader = remember(appContext) { AndroidCoverSelectionReader(appContext.contentResolver) }
    var coverSelectionFailure by remember { mutableStateOf<CoverSelectionFailure?>(null) }
    fun handleCoverSelection(result: CoverSelectionResult) {
        when (result) {
            is CoverSelectionResult.Ready -> {
                coverSelectionFailure = null
                resource?.let { viewModel.uploadCover(it.id, result.upload) }
            }
            CoverSelectionResult.UnsupportedType -> coverSelectionFailure = CoverSelectionFailure.Unsupported
            CoverSelectionResult.TooLarge -> coverSelectionFailure = CoverSelectionFailure.TooLarge
            CoverSelectionResult.Empty -> coverSelectionFailure = CoverSelectionFailure.Empty
            CoverSelectionResult.Unreadable -> coverSelectionFailure = CoverSelectionFailure.Unreadable
        }
    }
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) scope.launch { handleCoverSelection(coverReader.readPhoto(uri)) }
    }
    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) scope.launch { handleCoverSelection(coverReader.read(uri)) }
    }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(titleFor(task))
            when (task) {
                WorkManagementTask.EditWork, WorkManagementTask.AddSeries -> EditBookForm(content, state, viewModel)
                WorkManagementTask.Recognize -> MetadataLookup(resource, content, state, viewModel)
                WorkManagementTask.Cover -> CoverManagement(
                    resource = resource,
                    state = state,
                    workCover = workCover,
                    failure = coverSelectionFailure,
                    onChoosePhoto = {
                        photoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                    },
                    onChooseFile = {
                        filePicker.launch(arrayOf("image/jpeg", "image/png", "image/webp"))
                    },
                    onRegenerate = { resource?.let { viewModel.regenerateCover(it.id) } },
                )
                WorkManagementTask.Rescan -> ConfirmAction(
                    message = stringResource(R.string.management_rescan_message),
                    enabled = resource?.sourceNodeId?.isNotBlank() == true && !state.isBusy,
                    actionLabel = stringResource(R.string.management_rescan),
                ) { resource?.sourceNodeId?.let(viewModel::rescan) }
                WorkManagementTask.Delete -> DeleteBookForm(content.book.title, state.isBusy, viewModel::deleteBook)
                WorkManagementTask.EditVolume, WorkManagementTask.Kindle -> Text(stringResource(R.string.management_resource))
            }
            TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.cancel_action)) }
        }
    }
}

private enum class CoverSelectionFailure { Unsupported, TooLarge, Empty, Unreadable }

@Composable
private fun CoverManagement(
    resource: ResourceContent?,
    state: WorkManagementUiState,
    workCover: (@Composable () -> Unit)?,
    failure: CoverSelectionFailure?,
    onChoosePhoto: () -> Unit,
    onChooseFile: () -> Unit,
    onRegenerate: () -> Unit,
) {
    workCover?.invoke()
    resource?.let { Text(stringResource(R.string.management_cover_target, it.title)) }
    if (state.isBusy) CircularProgressIndicator()
    Button(
        onClick = onChoosePhoto,
        enabled = resource != null && !state.isBusy,
        modifier = Modifier.fillMaxWidth(),
    ) { Text(stringResource(R.string.management_choose_cover_photo)) }
    Button(
        onClick = onChooseFile,
        enabled = resource != null && !state.isBusy,
        modifier = Modifier.fillMaxWidth(),
    ) { Text(stringResource(R.string.management_choose_cover_file)) }
    Button(
        onClick = onRegenerate,
        enabled = resource != null && !state.isBusy,
        modifier = Modifier.fillMaxWidth(),
    ) { Text(stringResource(R.string.work_control_regenerate_cover)) }
    Text(stringResource(R.string.management_cover_upload_hint))
    failure?.let {
        Text(
            stringResource(
                when (it) {
                    CoverSelectionFailure.Unsupported -> R.string.management_cover_unsupported
                    CoverSelectionFailure.TooLarge -> R.string.management_cover_too_large
                    CoverSelectionFailure.Empty -> R.string.management_cover_empty
                    CoverSelectionFailure.Unreadable -> R.string.management_cover_read_failed
                },
            ),
        )
    }
}

@Composable
private fun EditBookForm(content: BookDetailContent, state: WorkManagementUiState, viewModel: WorkManagementViewModel) {
    var title by remember(content.book.id) { mutableStateOf(content.book.title) }
    var author by remember(content.book.id) { mutableStateOf(content.book.author) }
    var description by remember(content.book.id) { mutableStateOf(content.description.orEmpty()) }
    var series by remember(content.book.id) { mutableStateOf(content.seriesName.orEmpty()) }
    var seriesIndex by remember(content.book.id) { mutableStateOf(content.seriesIndex?.toString().orEmpty()) }
    var tags by remember(content.book.id) { mutableStateOf(content.tags.joinToString(", ")) }
    OutlinedTextField(title, { title = it }, label = { Text(stringResource(R.string.management_title)) }, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(author, { author = it }, label = { Text(stringResource(R.string.management_author)) }, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(description, { description = it }, label = { Text(stringResource(R.string.management_description)) }, modifier = Modifier.fillMaxWidth(), minLines = 3)
    OutlinedTextField(series, { series = it }, label = { Text(stringResource(R.string.management_series)) }, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(seriesIndex, { seriesIndex = it }, label = { Text(stringResource(R.string.management_series_index)) }, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(tags, { tags = it }, label = { Text(stringResource(R.string.management_tags)) }, modifier = Modifier.fillMaxWidth())
    Button(
        enabled = title.isNotBlank() && !state.isBusy,
        onClick = {
            viewModel.updateBook(BookMetadataDraft(
                title.trim(), author.trim().ifBlank { null }, description.trim().ifBlank { null },
                series.trim().ifBlank { null }, seriesIndex.toDoubleOrNull(),
                tags.split(',').map(String::trim).filter(String::isNotEmpty), content.tags,
            ))
        },
        modifier = Modifier.fillMaxWidth(),
    ) { Text(stringResource(R.string.management_save)) }
}

@Composable
private fun MetadataLookup(resource: ResourceContent?, content: BookDetailContent, state: WorkManagementUiState, viewModel: WorkManagementViewModel) {
    var query by remember { mutableStateOf(content.book.title) }
    LaunchedEffect(Unit) { viewModel.loadMetadataProviders() }
    val provider = state.metadataProviders.firstOrNull { it.enabled }
    OutlinedTextField(query, { query = it }, label = { Text(stringResource(R.string.management_query)) }, modifier = Modifier.fillMaxWidth())
    Button(
        enabled = provider != null && resource?.sourceNodeId?.isNotBlank() == true && query.isNotBlank() && !state.isBusy,
        onClick = { if (provider != null && resource != null) viewModel.searchMetadata(resource.sourceNodeId, provider.id, query) },
        modifier = Modifier.fillMaxWidth(),
    ) { Text(stringResource(R.string.management_search)) }
    LazyColumn(modifier = Modifier.fillMaxWidth()) {
        items(state.metadataCandidates, key = { it.id }) { candidate ->
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text(candidate.title ?: candidate.id)
                    candidate.description?.let { Text(it, maxLines = 2) }
                }
                TextButton(onClick = { if (provider != null && resource != null) viewModel.applyMetadata(resource.sourceNodeId, provider.id, candidate) }) {
                    Text(stringResource(R.string.management_apply))
                }
            }
        }
    }
}

@Composable
private fun ConfirmAction(message: String, enabled: Boolean, actionLabel: String, action: () -> Unit) {
    Text(message)
    Button(onClick = action, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text(actionLabel) }
}

@Composable
private fun DeleteBookForm(title: String, busy: Boolean, delete: () -> Unit) {
    var confirmation by remember(title) { mutableStateOf("") }
    Text(stringResource(R.string.management_delete_message, title))
    OutlinedTextField(confirmation, { confirmation = it }, label = { Text(title) }, modifier = Modifier.fillMaxWidth())
    Button(onClick = delete, enabled = confirmation == title && !busy, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(R.string.management_delete))
    }
}

@Composable
private fun titleFor(task: WorkManagementTask) = when (task) {
    WorkManagementTask.EditWork, WorkManagementTask.AddSeries -> stringResource(R.string.work_control_edit)
    WorkManagementTask.Recognize -> stringResource(R.string.work_control_recognize)
    WorkManagementTask.Cover -> stringResource(R.string.work_control_regenerate_cover)
    WorkManagementTask.Rescan -> stringResource(R.string.management_rescan)
    WorkManagementTask.Delete -> stringResource(R.string.management_delete)
    WorkManagementTask.EditVolume, WorkManagementTask.Kindle -> stringResource(R.string.management_resource)
}
