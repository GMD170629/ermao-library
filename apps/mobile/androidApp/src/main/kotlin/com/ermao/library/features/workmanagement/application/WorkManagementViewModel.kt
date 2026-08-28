package com.ermao.library.features.workmanagement.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.CoverMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class WorkManagementUiState(
    val capabilityChecked: Boolean = true,
    val supported: Boolean = true,
    val isBusy: Boolean = false,
    val errorCode: String? = null,
    val completedMutation: WorkManagementCompletion? = null,
    val coverMutation: CoverMutationOutcome? = null,
    val metadataProviders: List<MetadataProvider> = emptyList(),
    val metadataCandidates: List<MetadataCandidate> = emptyList(),
)

enum class WorkManagementCompletion {
    WorkUpdated, CoverUpdated, MetadataApplied, RescanQueued, BookDeleted, ReadingStatusUpdated,
}

class WorkManagementViewModel(
    private val repository: WorkManagementRepository,
    contentContext: ContentRequestContext,
    private val bookId: String,
    private val onUnauthorized: () -> Unit,
) : ViewModel() {
    private val context = BookManagementContext(contentContext.profile, contentContext.namespace)
    private val mutableUiState = MutableStateFlow(WorkManagementUiState())
    val uiState: StateFlow<WorkManagementUiState> = mutableUiState.asStateFlow()


    fun consumeFeedback() {
        mutableUiState.value = mutableUiState.value.copy(
            errorCode = null,
            completedMutation = null,
            coverMutation = null,
        )
    }

    fun setReadingStatus(status: ManagedReadingStatus) = run(WorkManagementCompletion.ReadingStatusUpdated) {
        repository.setBookReadingStatus(context, bookId, status)
    }

    fun setResourceReadingStatus(resourceId: String, status: ManagedReadingStatus) = run(WorkManagementCompletion.ReadingStatusUpdated) {
        repository.setReadingStatus(context, resourceId, status)
    }

    private fun run(completion: WorkManagementCompletion, operation: suspend () -> WorkManagementResult<*>) {
        if (mutableUiState.value.isBusy) return
        mutableUiState.value = mutableUiState.value.copy(isBusy = true, errorCode = null)
        viewModelScope.launch {
            when (val result = operation()) {
                is WorkManagementResult.Content -> mutableUiState.value = mutableUiState.value.copy(
                    isBusy = false,
                    completedMutation = completion,
                )
                is WorkManagementResult.Failure -> fail(result)
            }
        }
    }



    private fun fail(result: WorkManagementResult.Failure) {
        if (result.error.kind.name == "Unauthorized") onUnauthorized()
        mutableUiState.value = mutableUiState.value.copy(
            capabilityChecked = true,
            isBusy = false,
            errorCode = result.error.code,
        )
    }

    companion object {
        fun factory(
            repository: WorkManagementRepository,
            context: ContentRequestContext,
            bookId: String,
            onUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { WorkManagementViewModel(repository, context, bookId, onUnauthorized) }
        }
    }
}
