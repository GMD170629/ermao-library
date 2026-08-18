package com.ermao.library.features.workmanagement.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.shared.modules.downloads.DownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadsRuntime
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
import com.ermao.library.shared.modules.workmanagement.domain.WorkTransferTarget
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
    val deletedWork: Boolean = false,
    val transferTargets: List<WorkTransferTarget> = emptyList(),
    val metadataProviders: List<MetadataProvider> = emptyList(),
    val metadataCandidates: List<MetadataCandidate> = emptyList(),
    val metadataMessage: String? = null,
    val kindleSettings: KindleSettings? = null,
    val kindleOutcome: KindleSendOutcome? = null,
)

enum class WorkManagementCompletion {
    WorkUpdated,
    CoverUpdated,
    WorkDeleted,
    VolumeUpdated,
    VolumeReclassified,
    VolumeSplit,
    VolumeTransferred,
    VolumeDeleted,
    MetadataApplied,
    KindleQueued,
    ReadingStatusUpdated,
}

class WorkManagementViewModel(
    private val repository: WorkManagementRepository,
    private val context: WorkManagementContext,
    private val workId: String,
    private val downloadsRuntime: DownloadsRuntime,
    private val downloadNamespace: DownloadNamespace,
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

    fun deleteWork(volumeIds: List<String>) = mutate(
        completion = WorkManagementCompletion.WorkDeleted,
        block = { repository.deleteWork(context, workId) },
        onSuccess = {
            volumeIds.forEach { volumeId -> downloadsRuntime.removeArtifact(downloadNamespace, volumeId) }
            mutableUiState.update { state -> state.copy(deletedWork = true) }
        }
    )

    fun updateVolume(volumeId: String, draft: VolumeMetadataDraft) = mutate(WorkManagementCompletion.VolumeUpdated) {
        repository.updateVolume(context, workId, volumeId, draft)
    }

    fun reclassifyVolume(
        volumeId: String,
        mediaKind: ManagedMediaKind,
        workTitle: String,
        workAuthor: String?,
        coverApiPath: String?,
    ) {
        mutate(
            completion = WorkManagementCompletion.VolumeReclassified,
            block = { repository.reclassifyVolume(context, workId, volumeId, mediaKind) },
            onSuccess = success@{ _ ->
                val artifact = downloadsRuntime.artifact(downloadNamespace, volumeId) ?: return@success
                downloadsRuntime.rehomeCompletedArtifact(
                    namespace = downloadNamespace,
                    volumeId = volumeId,
                    targetWorkId = workId,
                    targetVersionId = artifact.descriptor.versionId,
                    targetVersionSourceKey = artifact.descriptor.versionSourceKey,
                    targetVersionSourceName = artifact.descriptor.versionSourceName,
                    targetWorkTitle = workTitle,
                    targetWorkAuthor = workAuthor,
                    targetCoverApiPath = coverApiPath,
                    targetVersionCompleted = artifact.descriptor.versionCompleted,
                )
            },
        )
    }

    fun splitVolume(volumeId: String, title: String, author: String?) {
        mutate(
            completion = WorkManagementCompletion.VolumeSplit,
            block = { repository.splitVolume(context, workId, volumeId, title, author) },
            onSuccess = success@{ outcome ->
                val targetWorkId = outcome.targetWorkId ?: return@success
                val artifact = downloadsRuntime.artifact(downloadNamespace, volumeId) ?: return@success
                downloadsRuntime.rehomeCompletedArtifact(
                    namespace = downloadNamespace,
                    volumeId = volumeId,
                    targetWorkId = targetWorkId,
                    targetVersionId = artifact.descriptor.versionId,
                    targetVersionSourceKey = artifact.descriptor.versionSourceKey,
                    targetVersionSourceName = artifact.descriptor.versionSourceName,
                    targetWorkTitle = title,
                    targetWorkAuthor = author,
                    targetCoverApiPath = artifact.descriptor.coverApiPath,
                    targetVersionCompleted = artifact.descriptor.versionCompleted,
                )
            },
        )
    }

    fun transferVolume(volumeId: String, target: WorkTransferTarget) {
        mutate(
            completion = WorkManagementCompletion.VolumeTransferred,
            block = { repository.transferVolume(context, workId, volumeId, target.id) },
            onSuccess = success@{ outcome ->
                val targetWorkId = outcome.targetWorkId ?: target.id
                val artifact = downloadsRuntime.artifact(downloadNamespace, volumeId) ?: return@success
                downloadsRuntime.rehomeCompletedArtifact(
                    namespace = downloadNamespace,
                    volumeId = volumeId,
                    targetWorkId = targetWorkId,
                    targetVersionId = artifact.descriptor.versionId,
                    targetVersionSourceKey = artifact.descriptor.versionSourceKey,
                    targetVersionSourceName = artifact.descriptor.versionSourceName,
                    targetWorkTitle = target.title,
                    targetWorkAuthor = target.author,
                    targetCoverApiPath = null,
                    targetVersionCompleted = artifact.descriptor.versionCompleted,
                )
            },
        )
    }

    fun deleteVolume(volumeId: String) {
        mutate(
            completion = WorkManagementCompletion.VolumeDeleted,
            block = { repository.deleteVolume(context, workId, volumeId) },
            onSuccess = { downloadsRuntime.removeArtifact(downloadNamespace, volumeId) },
        )
    }

    fun searchTransferTargets(query: String) = query(
        prepare = { it.copy(transferTargets = emptyList()) },
        block = { repository.searchTransferTargets(context, workId, query) },
        onSuccess = { targets -> mutableUiState.update { it.copy(transferTargets = targets) } },
    )

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
            downloadsRuntime: DownloadsRuntime,
            downloadNamespace: DownloadNamespace,
            onUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer {
                WorkManagementViewModel(
                    repository, context, workId, downloadsRuntime, downloadNamespace, onUnauthorized,
                )
            }
        }
    }
}
