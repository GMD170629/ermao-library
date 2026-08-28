package com.ermao.library.features.home.application

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.features.content.model.HomeContent
import com.ermao.library.features.content.model.toUiContent
import com.ermao.library.features.content.model.hasSectionFailure
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class HomeUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val content: HomeContent? = null,
    val errorCode: String? = null,
)

class HomeViewModel(
    private val repository: ContentRepository,
    private val context: ContentRequestContext,
    private val appContext: Context,
    private val onSessionUnauthorized: () -> Unit,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(HomeUiState())
    val uiState: StateFlow<HomeUiState> = mutableUiState.asStateFlow()
    private val latestProgressUpdatesByResourceId = mutableMapOf<String, ReaderProgressPresentationUpdate>()

    init {
        viewModelScope.launch {
            (appContext as ErmaoLibraryApplication).readerProgressPresentationCenter.updates.collect { update ->
                if (update.namespaceKey == context.presentationKey()) {
                    latestProgressUpdatesByResourceId[update.resourceId] = update
                    mutableUiState.update { state ->
                        val content = state.content?.applying(update) ?: return@update state
                        if (content === state.content) state else state.copy(content = content)
                    }
                }
            }
        }
        load()
    }

    fun refresh() = load(isRefresh = true)
    fun refreshAfterManagement(bookId: String, readingStatusChanged: Boolean) {
        if (readingStatusChanged) latestProgressUpdatesByResourceId.entries.removeAll { it.value.bookId == bookId }
        load(isRefresh = true)
    }

    fun retry() = load()

    private var loadJob: kotlinx.coroutines.Job? = null
    private fun load(isRefresh: Boolean = false) {
        loadJob?.cancel()
        mutableUiState.update {
            it.copy(
                isLoading = !isRefresh || it.content == null,
                isRefreshing = isRefresh,
                content = if (isRefresh) it.content else null,
                errorCode = null,
            )
        }
        loadJob = viewModelScope.launch {
            try {
                when (val result = repository.loadHome(context)) {
                    is ContentResult.Content -> {
                        val content = latestProgressUpdatesByResourceId.values.fold(result.value.toUiContent()) {
                            current, update -> current.applying(update)
                        }
                        mutableUiState.update { it.copy(
                            isLoading = false,
                            isRefreshing = false,
                            content = content,
                            errorCode = "HOME_PARTIAL_FAILURE".takeIf { result.value.hasSectionFailure() },
                        ) }
                    }
                    is ContentResult.Failure -> mutableUiState.update {
                        if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                        it.copy(isLoading = false, isRefreshing = false, errorCode = result.error.code)
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update {
                    it.copy(isLoading = false, isRefreshing = false, errorCode = "CONTENT_LOAD_FAILED")
                }
            }
        }
    }

    companion object {
        fun factory(
            repository: ContentRepository,
            context: ContentRequestContext,
            appContext: Context,
            onSessionUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { HomeViewModel(repository, context, appContext.applicationContext, onSessionUnauthorized) }
        }
    }
}

internal fun HomeContent.applying(update: ReaderProgressPresentationUpdate): HomeContent {
    val current = continueReading ?: return this
    if (current.book.id != update.bookId || current.resumeResourceId != update.resourceId) return this
    val progress = update.percent.toInt().coerceIn(0, 100).takeIf { it > 0 }
    return copy(
        continueReading = current.copy(book = current.book.copy(progressPercent = progress)),
        recentReading = recentReading.map { book ->
            if (book.id == update.bookId) book.copy(progressPercent = progress) else book
        },
        recentAdded = recentAdded.map { book ->
            if (book.id == update.bookId) book.copy(progressPercent = progress) else book
        },
    )
}

private fun ContentRequestContext.presentationKey(): String =
    "${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}"
