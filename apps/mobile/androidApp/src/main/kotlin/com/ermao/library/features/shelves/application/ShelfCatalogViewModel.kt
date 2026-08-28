package com.ermao.library.features.shelves.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ermao.library.shared.modules.shelf.CreateShelfInput
import com.ermao.library.shared.modules.shelf.ShelfCatalogEntry
import com.ermao.library.shared.modules.shelf.ShelfCatalogPage
import com.ermao.library.shared.modules.shelf.ShelfCatalogRepository
import com.ermao.library.shared.modules.shelf.ShelfCatalogScope
import com.ermao.library.shared.modules.shelf.ShelfError
import com.ermao.library.shared.modules.shelf.ShelfErrorKind
import com.ermao.library.shared.modules.shelf.ShelfKind
import com.ermao.library.shared.modules.shelf.catalogEntries
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

sealed interface ShelfLoadState {
    data object Loading : ShelfLoadState
    data class Failed(val error: ShelfError) : ShelfLoadState
    data class Ready(val catalog: List<ShelfCatalogEntry>, val detail: ShelfCatalogPage?) : ShelfLoadState
}

sealed interface ShelfSaveState {
    data object Idle : ShelfSaveState
    data object Saving : ShelfSaveState
    data class Failed(val error: ShelfError) : ShelfSaveState
}

data class ShelfCatalogUiState(
    val content: ShelfLoadState = ShelfLoadState.Loading,
    val scope: ShelfCatalogScope = ShelfCatalogScope.All,
    val queries: Map<ShelfCatalogScope, String> = emptyMap(),
    val loadingMore: Boolean = false,
    val paginationError: ShelfError? = null,
    val saveState: ShelfSaveState = ShelfSaveState.Idle,
) {
    val query: String get() = queries[scope].orEmpty()
    val visibleShelves: List<ShelfCatalogEntry> get() {
        val ready = content as? ShelfLoadState.Ready ?: return emptyList()
        return catalogEntries(ready.catalog, scope, query, ready.detail?.shelf?.id)
    }
}

class ShelfCatalogViewModel(
    private val repository: ShelfCatalogRepository,
    private val context: ShelfRequestContext,
    private val shelfId: String?,
    private val onUnauthorized: () -> Unit,
) : ViewModel() {
    private val mutableState = MutableStateFlow(ShelfCatalogUiState())
    val state = mutableState.asStateFlow()
    private var loadJob: Job? = null
    private var generation = 0

    init { refresh() }

    fun selectScope(scope: ShelfCatalogScope) = mutableState.update { it.copy(scope = scope) }
    fun search(query: String) = mutableState.update { it.copy(queries = it.queries + (it.scope to query)) }

    fun refresh() {
        loadJob?.cancel()
        val requestGeneration = ++generation
        val previous = mutableState.value.content as? ShelfLoadState.Ready
        mutableState.update { it.copy(loadingMore = true, paginationError = null) }
        loadJob = viewModelScope.launch {
            val catalog = when (val result = repository.loadCatalog(context)) {
                is ShelfResult.Content -> result.value
                is ShelfResult.Failure -> { fail(result.error, requestGeneration); return@launch }
            }
            var detail = if (shelfId == null) null else when (val result = repository.loadPage(context, shelfId, 1)) {
                is ShelfResult.Content -> result.value
                is ShelfResult.Failure -> { fail(result.error, requestGeneration); return@launch }
            }
            val lastPage = previous?.detail?.page ?: 1
            for (page in 2..lastPage) {
                val current = detail ?: break
                if (page > current.totalPages) break
                when (val result = repository.loadPage(context, current.shelf.id, page)) {
                    is ShelfResult.Content -> detail = result.value.copy(shelf = result.value.shelf.copy(
                        books = (current.shelf.books + result.value.shelf.books).distinctBy { it.id }))
                    is ShelfResult.Failure -> { fail(result.error, requestGeneration); return@launch }
                }
            }
            if (generation == requestGeneration) mutableState.update { it.copy(content = ShelfLoadState.Ready(catalog, detail), loadingMore = false) }
        }
    }

    fun loadMore() {
        val current = mutableState.value
        val ready = current.content as? ShelfLoadState.Ready ?: return
        val detail = ready.detail ?: return
        if (detail.shelf.kind == ShelfKind.Collection || current.loadingMore || detail.page >= detail.totalPages) return
        val requestGeneration = generation
        mutableState.update { it.copy(loadingMore = true, paginationError = null) }
        loadJob = viewModelScope.launch {
            val result = repository.loadPage(context, detail.shelf.id, detail.page + 1)
            if (requestGeneration != generation) return@launch
            when (result) {
                is ShelfResult.Content -> mutableState.update {
                    val next = result.value
                    it.copy(content = ready.copy(detail = next.copy(shelf = next.shelf.copy(
                        books = (detail.shelf.books + next.shelf.books).distinctBy { book -> book.id },
                    ))), loadingMore = false)
                }
                is ShelfResult.Failure -> {
                    if (result.error.kind in setOf(ShelfErrorKind.Unauthorized, ShelfErrorKind.Inaccessible)) {
                        fail(result.error, requestGeneration)
                    } else mutableState.update { it.copy(loadingMore = false, paginationError = result.error) }
                }
            }
        }
    }

    fun create(input: CreateShelfInput, onCreated: (String) -> Unit) {
        if (mutableState.value.saveState == ShelfSaveState.Saving) return
        mutableState.update { it.copy(saveState = ShelfSaveState.Saving) }
        viewModelScope.launch {
            when (val result = repository.createShelf(context, input)) {
                is ShelfResult.Content -> {
                    mutableState.update { it.copy(saveState = ShelfSaveState.Idle) }
                    refresh()
                    onCreated(result.value)
                }
                is ShelfResult.Failure -> {
                    mutableState.update { it.copy(saveState = ShelfSaveState.Failed(result.error)) }
                    if (result.error.kind == ShelfErrorKind.Unauthorized) onUnauthorized()
                }
            }
        }
    }

    fun clearSaveError() = mutableState.update { if (it.saveState == ShelfSaveState.Saving) it else it.copy(saveState = ShelfSaveState.Idle) }

    private fun fail(error: ShelfError, requestGeneration: Int) {
        if (generation != requestGeneration) return
        mutableState.update { it.copy(content = ShelfLoadState.Failed(error), loadingMore = false) }
        if (error.kind == ShelfErrorKind.Unauthorized) onUnauthorized()
    }
}
