package com.ermao.library.features.workmanagement.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Inert boundary while native management is disabled for the Book/Resource/Asset cutover. */
data class WorkManagementUiState(
    val isBusy: Boolean = false,
    val errorCode: String? = null,
    val completedMutation: WorkManagementCompletion? = null,
)

enum class WorkManagementCompletion {
    WorkUpdated,
    CoverUpdated,
    VolumeUpdated,
    VolumeReclassified,
    MetadataApplied,
    KindleQueued,
    ReadingStatusUpdated,
}

class WorkManagementViewModel : ViewModel() {
    private val mutableUiState = MutableStateFlow(WorkManagementUiState())
    val uiState: StateFlow<WorkManagementUiState> = mutableUiState.asStateFlow()

    fun consumeFeedback() {
        mutableUiState.value = mutableUiState.value.copy(errorCode = null, completedMutation = null)
    }

    @Suppress("UNUSED_PARAMETER")
    fun setReadingStatus(resourceId: String, status: Any) = Unit

    companion object {
        @Suppress("UNUSED_PARAMETER")
        fun factory(
            repository: WorkManagementRepository? = null,
            context: Any? = null,
            bookId: String = "",
            onUnauthorized: () -> Unit = {},
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { WorkManagementViewModel() }
        }
    }
}
