package com.ermao.library.features.workmanagement.ui

import androidx.compose.runtime.Composable
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.workmanagement.application.WorkManagementUiState
import com.ermao.library.features.workmanagement.application.WorkManagementViewModel

/** Inert target types kept for the disabled native management capability. */
sealed interface WorkManagementTarget {
    data object Work : WorkManagementTarget
    data class Resource(val value: ResourceContent) : WorkManagementTarget
}

enum class WorkManagementTask {
    AddSeries,
    EditWork,
    Recognize,
    Cover,
    EditVolume,
    MediaKind,
    Kindle,
}

/** No native management UI is exposed during the contract cutover. */
@Composable
fun WorkManagementTaskSheet(
    task: WorkManagementTask,
    target: WorkManagementTarget,
    content: Any,
    state: WorkManagementUiState,
    viewModel: WorkManagementViewModel,
    downloadRecordsByResource: Map<String, Any?> = emptyMap(),
    workCover: (@Composable () -> Unit)? = null,
    onDismiss: () -> Unit,
) = Unit
