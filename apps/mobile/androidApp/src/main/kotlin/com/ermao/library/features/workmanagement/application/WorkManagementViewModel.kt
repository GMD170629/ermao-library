package com.ermao.library.features.workmanagement.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedMediaKind
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.VolumeMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import com.ermao.library.shared.modules.workmanagement.domain.WorkMetadataDraft
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class WorkManagementUiState(
    val capabilityChecked: Boolean = false,
    val supported: Boolean = false,
    val busy: Boolean = false,
    val errorCode: String? = null,
    val fieldErrors: Map<String, List<String>> = emptyMap(),
    val completedMutation: WorkManagementCompletion? = null,
    val metadataProviders: List<MetadataProvider> = emptyList(),
    val metadataCandidates: List<MetadataCandidate> = emptyList(),
    val metadataMessage: String? = null,
    val kindleSettings: KindleSettings? = null,
    val kindleOutcome: KindleSendOutcome? = null,
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

class WorkManagementViewModel(
    private val repository: WorkManagementRepository,
    private val context: WorkManagementContext,
    private val workId: String,
    private val onUnauthorized: () -> Unit,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(WorkManagementUiState())
    val uiState: StateFlow<WorkManagementUiState> = mutableUiState.asStateFlow()

    init { checkCapability() }

    fun consumeFeedback() = mutableUiState.update {
        it.copy(
            errorCode = null,
            fieldErrors = emptyMap(),
            completedMutation = null,
            kindleOutcome = null,
        )
    }

    fun updateWork(draft: WorkMetadataDraft) = mutate(WorkManagementCompletion.WorkUpdated) {
        repository.updateWork(context, workId, draft)
    }

    fun uploadCover(upload: CoverUpload) = mutate(WorkManagementCompletion.CoverUpdated) {
        repository.uploadCover(context, workId, upload)
    }

    fun regenerateCover() = mutate(WorkManagementCompletion.CoverUpdated) {
        repository.regenerateCover(context, workId)
    }

    fun updateVolume(volumeId: String, draft: VolumeMetadataDraft) = mutate(WorkManagementCompletion.VolumeUpdated) {
        repository.updateVolume(context, workId, volumeId, draft)
    }

    fun reclassifyVolume(volumeId: String, mediaKind: ManagedMediaKind) {
        mutate(WorkManagementCompletion.VolumeReclassified) {
            repository.reclassifyVolume(context, workId, volumeId, mediaKind)
        }
    }

    fun loadMetadataProviders(mediaKind: ManagedMediaKind) = query(
        prepare = { it.copy(metadataProviders = emptyList(), metadataCandidates = emptyList()) },
        block = { repository.loadMetadataProviders(context, mediaKind) },
        onSuccess = { providers -> mutableUiState.update { it.copy(metadataProviders = providers) } },
    )

    fun searchMetadata(providerId: String, query: String) = query(
        prepare = { it.copy(metadataCandidates = emptyList(), metadataMessage = null) },
        block = { repository.searchMetadata(context, workId, providerId, query) },
        onSuccess = { result ->
            mutableUiState.update {
                it.copy(metadataCandidates = result.candidates, metadataMessage = result.message)
            }
        },
    )

    fun applyMetadata(
        providerId: String,
        candidate: MetadataCandidate,
        fields: Set<MetadataField>,
        volumeId: String?,
        applyToAllVolumes: Boolean,
    ) = mutate(WorkManagementCompletion.MetadataApplied) {
        repository.applyMetadata(context, workId, providerId, candidate, fields, volumeId, applyToAllVolumes)
    }

    fun loadKindleSettings() = query(
        prepare = { it.copy(kindleSettings = null) },
        block = { repository.loadKindleSettings(context) },
        onSuccess = { settings -> mutableUiState.update { it.copy(kindleSettings = settings) } },
    )

    fun sendToKindle(fileId: String) = mutate(
        completion = WorkManagementCompletion.KindleQueued,
        block = { repository.sendToKindle(context, workId, fileId) },
        onSuccess = { outcome -> mutableUiState.update { it.copy(kindleOutcome = outcome) } },
    )

    fun setReadingStatus(volumeId: String, status: ManagedReadingStatus) =
        mutate(WorkManagementCompletion.ReadingStatusUpdated) {
            repository.setReadingStatus(context, volumeId, status)
        }

    private fun checkCapability() {
        viewModelScope.launch {
            when (val result = repository.supportsNativeManagement(context)) {
                is WorkManagementResult.Content -> mutableUiState.update {
                    it.copy(capabilityChecked = true, supported = result.value)
                }
                is WorkManagementResult.Failure -> handleFailure(result)
            }
        }
    }

    private fun <T> query(
        prepare: (WorkManagementUiState) -> WorkManagementUiState = { it },
        block: suspend () -> WorkManagementResult<T>,
        onSuccess: suspend (T) -> Unit,
    ) = executeRequest(null, prepare, block, onSuccess)

    private fun <T> mutate(
        completion: WorkManagementCompletion,
        onSuccess: suspend (T) -> Unit = {},
        block: suspend () -> WorkManagementResult<T>,
    ) = executeRequest(completion, { it }, block, onSuccess)

    private fun <T> executeRequest(
        completion: WorkManagementCompletion?,
        prepare: (WorkManagementUiState) -> WorkManagementUiState,
        block: suspend () -> WorkManagementResult<T>,
        onSuccess: suspend (T) -> Unit,
    ) {
        if (mutableUiState.value.busy) return
        mutableUiState.update {
            prepare(it).copy(
                busy = true,
                errorCode = null,
                fieldErrors = emptyMap(),
                completedMutation = null,
            )
        }
        viewModelScope.launch {
            try {
                when (val result = block()) {
                    is WorkManagementResult.Content -> {
                        onSuccess(result.value)
                        mutableUiState.update {
                            it.copy(busy = false, completedMutation = completion)
                        }
                    }
                    is WorkManagementResult.Failure -> handleFailure(result)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update { it.copy(busy = false, errorCode = "MANAGEMENT_FAILED") }
            }
        }
    }

    private fun handleFailure(result: WorkManagementResult.Failure) {
        if (result.error.kind == WorkManagementErrorKind.Unauthorized) onUnauthorized()
        mutableUiState.update {
            it.copy(
                busy = false,
                capabilityChecked = true,
                errorCode = result.error.code,
                fieldErrors = result.error.fieldErrors,
            )
        }
    }

    companion object {
        fun factory(
            repository: WorkManagementRepository,
            context: WorkManagementContext,
            workId: String,
            onUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer {
                WorkManagementViewModel(
                    repository, context, workId, onUnauthorized,
                )
            }
        }
    }
}
