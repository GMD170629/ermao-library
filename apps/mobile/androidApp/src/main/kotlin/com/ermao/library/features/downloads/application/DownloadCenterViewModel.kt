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
import com.ermao.library.features.downloads.model.DownloadedBookGroup
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
    val completedBooks: List<DownloadedBookGroup> = emptyList(),
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
                completedBooks = completed,
                failed = records.filter { it.status in FAILED_STATUSES }.sortedByDescending(AndroidDownloadRecord::updatedAtEpochMillis),
                totalCompletedBytes = completed.sumOf(DownloadedBookGroup::totalBytes),
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

data class DownloadedBookUiState(
    val isLoading: Boolean = true,
    val book: DownloadedBookGroup? = null,
    val errorCode: String? = null,
)

class DownloadedBookViewModel(
    private val catalog: AndroidDownloadCatalog,
    private val namespace: AndroidDownloadNamespace,
    private val bookId: String,
    private val localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(DownloadedBookUiState())
    val uiState: StateFlow<DownloadedBookUiState> = mutableUiState.asStateFlow()

    init {
        viewModelScope.launch {
            try {
                catalog.observe(namespace).collectLatest { records ->
                    val book = groupReadableDownloads(records, "", localArtifactIsValid).firstOrNull { it.bookId == bookId }
                    mutableUiState.value = DownloadedBookUiState(isLoading = false, book = book)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.value = DownloadedBookUiState(isLoading = false, errorCode = "DOWNLOAD_CATALOG_UNAVAILABLE")
            }
        }
    }

    companion object {
        fun factory(
            catalog: AndroidDownloadCatalog,
            namespace: AndroidDownloadNamespace,
            bookId: String,
            localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { DownloadedBookViewModel(catalog, namespace, bookId, localArtifactIsValid) }
        }
    }
}
