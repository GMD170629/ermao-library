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
import com.ermao.library.features.downloads.model.groupDownloads
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
    val books: List<DownloadedBookGroup> = emptyList(),
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
        val projected = records.map { it.withLocalValidity(localArtifactIsValid) }
        mutableUiState.update { current ->
            current.copy(
                isLoading = false,
                books = groupDownloads(projected, query),
                totalCompletedBytes = projected.filter(AndroidDownloadRecord::isReadable).sumOf(AndroidDownloadRecord::expectedBytes),
                errorCode = null,
            )
        }
    }

    companion object {
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

    private var observation: Job? = null

    init { retry() }

    fun retry() {
        observation?.cancel()
        mutableUiState.value = DownloadedBookUiState()
        observation = viewModelScope.launch {
            try {
                catalog.observe(namespace).collectLatest { records ->
                    val book = groupDownloads(records.filter { it.bookId == bookId }
                        .map { it.withLocalValidity(localArtifactIsValid) }, "").firstOrNull()
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

private fun AndroidDownloadRecord.withLocalValidity(validate: (AndroidDownloadRecord) -> Boolean): AndroidDownloadRecord =
    if (isReadable && !validate(this)) copy(verified = false, errorCode = "DOWNLOAD_LOCAL_FILE_INVALID") else this
