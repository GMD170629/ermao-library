package com.ermao.library.features.downloads.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.downloads.model.DownloadedWorkGroup
import com.ermao.library.features.downloads.model.groupReadableDownloads
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class DownloadCenterUiState(
    val query: String = "",
    val isLoading: Boolean = true,
    val active: List<AndroidDownloadRecord> = emptyList(),
    val completedWorks: List<DownloadedWorkGroup> = emptyList(),
    val failed: List<AndroidDownloadRecord> = emptyList(),
    val totalCompletedBytes: Long = 0,
    val errorCode: String? = null,
)

class DownloadCenterViewModel(
    private val catalog: AndroidDownloadCatalog,
    private val namespace: AndroidDownloadNamespace,
    private val localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(DownloadCenterUiState())
    val uiState: StateFlow<DownloadCenterUiState> = mutableUiState.asStateFlow()
    private var records: List<AndroidDownloadRecord> = emptyList()
    private var observation: Job? = null

    init { observe() }

    fun updateQuery(query: String) {
        mutableUiState.update { it.copy(query = query) }
        project()
    }

    fun clearQuery() = updateQuery("")

    fun retry() = observe()

    fun remove(taskId: String, removeLocalReference: (String) -> Unit) {
        viewModelScope.launch {
            try {
                catalog.remove(namespace, taskId)?.localReference?.let(removeLocalReference)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update { it.copy(errorCode = "DOWNLOAD_REMOVE_FAILED") }
            }
        }
    }

    private fun observe() {
        observation?.cancel()
        mutableUiState.update { it.copy(isLoading = true, errorCode = null) }
        observation = viewModelScope.launch {
            try {
                catalog.observe(namespace).collectLatest {
                    records = it
                    project()
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update { it.copy(isLoading = false, errorCode = "DOWNLOAD_CATALOG_UNAVAILABLE") }
            }
        }
    }

    private fun project() {
        val query = mutableUiState.value.query
        val completed = groupReadableDownloads(records, query, localArtifactIsValid)
        mutableUiState.update { current ->
            current.copy(
                isLoading = false,
                active = records.filter { it.status in ACTIVE_STATUSES }.sortedBy(AndroidDownloadRecord::createdAtEpochMillis),
                completedWorks = completed,
                failed = records.filter { it.status in FAILED_STATUSES }.sortedByDescending(AndroidDownloadRecord::updatedAtEpochMillis),
                totalCompletedBytes = completed.sumOf(DownloadedWorkGroup::totalBytes),
                errorCode = null,
            )
        }
    }

    companion object {
        private val ACTIVE_STATUSES = setOf(
            AndroidDownloadStatus.Queued,
            AndroidDownloadStatus.Downloading,
            AndroidDownloadStatus.Paused,
            AndroidDownloadStatus.Verifying,
        )
        private val FAILED_STATUSES = setOf(AndroidDownloadStatus.FailedRetryable, AndroidDownloadStatus.FailedTerminal)

        fun factory(
            catalog: AndroidDownloadCatalog,
            namespace: AndroidDownloadNamespace,
            localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { DownloadCenterViewModel(catalog, namespace, localArtifactIsValid) }
        }
    }
}

data class DownloadedWorkUiState(
    val isLoading: Boolean = true,
    val work: DownloadedWorkGroup? = null,
    val errorCode: String? = null,
)

class DownloadedWorkViewModel(
    private val catalog: AndroidDownloadCatalog,
    private val namespace: AndroidDownloadNamespace,
    private val workId: String,
    private val localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(DownloadedWorkUiState())
    val uiState: StateFlow<DownloadedWorkUiState> = mutableUiState.asStateFlow()

    init {
        viewModelScope.launch {
            try {
                catalog.observe(namespace).collectLatest { records ->
                    val work = groupReadableDownloads(records, "", localArtifactIsValid).firstOrNull { it.workId == workId }
                    mutableUiState.value = DownloadedWorkUiState(isLoading = false, work = work)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.value = DownloadedWorkUiState(isLoading = false, errorCode = "DOWNLOAD_CATALOG_UNAVAILABLE")
            }
        }
    }

    companion object {
        fun factory(
            catalog: AndroidDownloadCatalog,
            namespace: AndroidDownloadNamespace,
            workId: String,
            localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { DownloadedWorkViewModel(catalog, namespace, workId, localArtifactIsValid) }
        }
    }
}
