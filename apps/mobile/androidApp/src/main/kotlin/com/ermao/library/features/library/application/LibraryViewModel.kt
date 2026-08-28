package com.ermao.library.features.library.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.features.content.model.ContentSort
import com.ermao.library.features.content.model.ContentViewMode
import com.ermao.library.features.content.model.GroupingCard
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.ReadingFilter
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.WorksFilters
import com.ermao.library.features.content.model.toCard
import com.ermao.library.features.content.model.toFacetKind
import com.ermao.library.features.content.model.toShared
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.GroupingQuery
import com.ermao.library.shared.modules.library.LibraryFilters
import com.ermao.library.shared.modules.library.LibraryPage
import com.ermao.library.shared.modules.library.ReadingStatus
import com.ermao.library.shared.modules.library.BooksQuery
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.library.application.LibraryDiscoveryRuntime
import com.ermao.library.shared.modules.library.application.LibraryScrollAnchor
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ScrollAnchor(val itemId: String? = null, val offset: Int = 0)

data class LibrarySourceOption(val id: String, val name: String)

data class ScopeUiState(
    val query: String = "",
    val sort: ContentSort = ContentSort.RecentAdded,
    val viewMode: ContentViewMode = ContentViewMode.Grid,
    val filters: WorksFilters = WorksFilters(),
    val works: List<BookCard> = emptyList(),
    val groups: List<GroupingCard> = emptyList(),
    val total: Int = 0,
    val loadedPage: Int = 0,
    val totalPages: Int = 1,
    val isLoading: Boolean = true,
    val isLoadingMore: Boolean = false,
    val errorCode: String? = null,
    val paginationErrorCode: String? = null,
    val scrollAnchor: ScrollAnchor = ScrollAnchor(),
)

data class LibraryUiState(
    val selectedScope: LibraryScope = LibraryScope.Books,
    val libraryOptions: List<LibrarySourceOption> = emptyList(),
    val selectedLibraryId: String? = null,
    val scopes: Map<LibraryScope, ScopeUiState> = LibraryScope.entries.associateWith { ScopeUiState() },
    val filterDraft: WorksFilters? = null,
    val selectedBookId: String? = null,
) {
    val current: ScopeUiState get() = scopes.getValue(selectedScope)
}

class LibraryViewModel(
    private val repository: ContentRepository,
    private val context: ContentRequestContext,
    private val onSessionUnauthorized: () -> Unit,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(LibraryUiState())
    val uiState: StateFlow<LibraryUiState> = mutableUiState.asStateFlow()
    private var searchJob: Job? = null
    private val discoveryRuntime = LibraryDiscoveryRuntime()

    init {
        loadLibraryOptions()
        loadScope(LibraryScope.Books, reset = true)
    }

    fun selectLibrary(libraryId: String?) {
        if (libraryId == mutableUiState.value.selectedLibraryId) return
        mutableUiState.update { it.copy(selectedLibraryId = libraryId) }
        loadScope(LibraryScope.Books, reset = true)
    }

    fun selectScope(scope: LibraryScope) {
        if (scope == mutableUiState.value.selectedScope) return
        discoveryRuntime.selectScope(scope.toDiscoveryScope())
        mutableUiState.update { state ->
            val target = state.scopes.getValue(scope)
            state.copy(
                selectedScope = scope,
                scopes = state.scopes + (
                    scope to if (target.loadedPage == 0) {
                        target.copy(
                            isLoading = true,
                            errorCode = null,
                            paginationErrorCode = null,
                        )
                    } else target
                ),
            )
        }
        loadScope(scope, reset = true)
    }

    fun updateQuery(value: String) {
        val scope = mutableUiState.value.selectedScope
        discoveryRuntime.updateQuery(scope.toDiscoveryScope(), value)
        updateCurrent { it.copy(query = value) }
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(SEARCH_DEBOUNCE_MILLIS)
            loadScope(scope, reset = true)
        }
    }

    fun clearQuery() {
        searchJob?.cancel()
        discoveryRuntime.updateQuery(mutableUiState.value.selectedScope.toDiscoveryScope(), "")
        updateCurrent { it.copy(query = "") }
        loadScope(mutableUiState.value.selectedScope, reset = true)
    }

    fun selectSort(sort: ContentSort) {
        if (mutableUiState.value.selectedScope != LibraryScope.Books) return
        discoveryRuntime.updateSort(
            com.ermao.library.shared.modules.library.LibraryScope.Books,
            sort.toShared(),
        )
        updateCurrent { it.copy(sort = sort) }
        loadScope(mutableUiState.value.selectedScope, reset = true)
    }

    fun selectViewMode(viewMode: ContentViewMode) {
        discoveryRuntime.updateViewMode(
            com.ermao.library.shared.modules.library.LibraryScope.Books,
            when (viewMode) {
                ContentViewMode.Grid -> com.ermao.library.shared.modules.library.LibraryViewMode.Grid
                ContentViewMode.List -> com.ermao.library.shared.modules.library.LibraryViewMode.List
            },
        )
        updateCurrent {
            it.copy(
                viewMode = viewMode,
                isLoadingMore = false,
                paginationErrorCode = null,
            )
        }
    }

    fun openFilter() = mutableUiState.update { it.copy(filterDraft = it.scopes.getValue(LibraryScope.Books).filters) }

    fun updateFilterDraft(filters: WorksFilters) = mutableUiState.update { it.copy(filterDraft = filters) }

    fun dismissFilter() = mutableUiState.update { it.copy(filterDraft = null) }

    fun applyFilter() {
        val draft = mutableUiState.value.filterDraft ?: return
        discoveryRuntime.applyFilters(draft.toSharedFilters())
        updateScope(LibraryScope.Books) { it.copy(filters = draft) }
        mutableUiState.update { it.copy(filterDraft = null) }
        if (mutableUiState.value.selectedScope == LibraryScope.Books) loadScope(LibraryScope.Books, reset = true)
    }

    fun clearFilters() = updateFilterDraft(WorksFilters())

    fun removeReadingFilter(readingFilter: ReadingFilter) {
        val filters = mutableUiState.value.scopes.getValue(LibraryScope.Books).filters.let {
            it.copy(reading = if (it.reading == readingFilter) null else it.reading)
        }
        discoveryRuntime.applyFilters(filters.toSharedFilters())
        updateScope(LibraryScope.Books) { state ->
            state.copy(filters = filters)
        }
        if (mutableUiState.value.selectedScope == LibraryScope.Books) loadScope(LibraryScope.Books, reset = true)
    }

    fun retry() = loadScope(mutableUiState.value.selectedScope, reset = true)

    fun refreshAfterManagement() {
        mutableUiState.value.scopes.filterValues { it.loadedPage > 0 }.forEach { (scope, snapshot) ->
            val token = discoveryRuntime.beginInitialRequest(scope.toDiscoveryScope())
            val libraryId = mutableUiState.value.selectedLibraryId
            updateScope(scope) { it.copy(isLoadingMore = true) }
            viewModelScope.launch {
                val pages = mutableListOf<LibraryPage<*>>()
                for (page in 1..snapshot.loadedPage) {
                    val result = if (scope == LibraryScope.Books) repository.loadBooks(context, snapshot.toBooksQuery(page, libraryId))
                        else repository.loadGroupings(context, snapshot.toGroupingQuery(scope, page))
                    when (result) {
                        is ContentResult.Content -> {
                            pages += result.value
                            if (page >= result.value.totalPages) break
                        }
                        is ContentResult.Failure -> {
                            if (discoveryRuntime.fail(token, result.error.code)) {
                                updateScope(scope) { it.copy(isLoadingMore = false, paginationErrorCode = result.error.code) }
                                if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                            }
                            return@launch
                        }
                    }
                }
                if (discoveryRuntime.acceptPage(token, pages.all { it.items.isEmpty() })) {
                    pages.forEachIndexed { index, page -> applyPage(scope, page, reset = index == 0) }
                }
            }
        }
    }

    fun loadNextPage() {
        val scope = mutableUiState.value.selectedScope
        val current = mutableUiState.value.current
        if (current.isLoading || current.isLoadingMore || current.loadedPage >= current.totalPages) return
        loadScope(scope, reset = false)
    }

    fun updateScrollAnchor(itemId: String?, offset: Int) {
        discoveryRuntime.rememberScrollAnchor(
            mutableUiState.value.selectedScope.toDiscoveryScope(),
            itemId?.let { LibraryScrollAnchor(it, offset) },
        )
        updateCurrent { it.copy(scrollAnchor = ScrollAnchor(itemId, offset)) }
    }

    fun selectBook(bookId: String?) {
        discoveryRuntime.selectBook(mutableUiState.value.selectedScope.toDiscoveryScope(), bookId)
        mutableUiState.update { it.copy(selectedBookId = bookId) }
    }

    private fun loadScope(scope: LibraryScope, reset: Boolean) {
        val current = mutableUiState.value.scopes.getValue(scope)
        if (!reset && (current.isLoading || current.isLoadingMore)) return
        val page = if (reset) 1 else current.loadedPage + 1
        val sharedScope = scope.toDiscoveryScope()
        val requestToken = if (reset) {
            discoveryRuntime.beginInitialRequest(sharedScope)
        } else {
            discoveryRuntime.beginNextPage(sharedScope, page) ?: return
        }
        updateScope(scope) {
            if (reset) {
                it.copy(
                    works = emptyList(),
                    groups = emptyList(),
                    total = 0,
                    loadedPage = 0,
                    isLoading = true,
                    errorCode = null,
                    paginationErrorCode = null,
                )
            }
            else it.copy(isLoadingMore = true, paginationErrorCode = null)
        }
        viewModelScope.launch {
            try {
                val snapshot = mutableUiState.value.scopes.getValue(scope)
                val worksQuery = snapshot.toBooksQuery(page, mutableUiState.value.selectedLibraryId)
                val groupingQuery = snapshot.toGroupingQuery(scope, page)
                val result = if (scope == LibraryScope.Books) {
                    repository.loadBooks(context, worksQuery)
                } else {
                    repository.loadGroupings(context, groupingQuery)
                }
                when (result) {
                    is ContentResult.Content -> {
                        if (discoveryRuntime.acceptPage(requestToken, result.value.items.isEmpty())
                        ) {
                            applyPage(scope, result.value, reset)
                        }
                    }
                    is ContentResult.Failure -> {
                        if (result.error.kind == AppErrorKind.Unauthorized) {
                            discoveryRuntime.beginPermissionRevalidation()
                            updateScope(scope) {
                                it.copy(
                                    works = emptyList(),
                                    groups = emptyList(),
                                    isLoading = false,
                                    isLoadingMore = false,
                                    errorCode = "PERMISSION_REVALIDATING",
                                )
                            }
                            onSessionUnauthorized()
                        } else if (result.error.kind == AppErrorKind.Forbidden || result.error.kind == AppErrorKind.NotFoundOrUnavailable) {
                            discoveryRuntime.markInaccessible(sharedScope)
                            updateScope(scope) {
                                it.copy(
                                    works = emptyList(), groups = emptyList(), isLoading = false,
                                    isLoadingMore = false, errorCode = "CONTENT_NOT_ACCESSIBLE",
                                )
                            }
                        } else {
                            discoveryRuntime.fail(requestToken, result.error.code)
                            applyFailure(scope, result.error.code, reset)
                        }
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                discoveryRuntime.fail(requestToken, "CONTENT_LOAD_FAILED")
                applyFailure(scope, "CONTENT_LOAD_FAILED", reset)
            }
        }
    }

    private fun loadLibraryOptions() {
        viewModelScope.launch {
            when (val result = repository.loadLibraryOptions(context)) {
                is ContentResult.Content -> mutableUiState.update { state ->
                    state.copy(
                        libraryOptions = result.value.map { LibrarySourceOption(it.id, it.name) },
                        selectedLibraryId = state.selectedLibraryId?.takeIf { selected ->
                            result.value.any { it.id == selected }
                        },
                    )
                }
                is ContentResult.Failure -> if (result.error.kind == AppErrorKind.Unauthorized) {
                    onSessionUnauthorized()
                }
            }
        }
    }

    private fun applyPage(
        scope: LibraryScope,
        page: LibraryPage<*>,
        reset: Boolean,
    ) = updateScope(scope) { current ->
        if (scope == LibraryScope.Books) {
            val incoming = page.items.filterIsInstance<com.ermao.library.shared.modules.library.domain.BookSummary>().map { it.toCard() }
            current.copy(
                works = mergeById(if (reset) emptyList() else current.works, incoming) { it.id },
                groups = emptyList(),
                total = page.total,
                loadedPage = page.page,
                totalPages = page.totalPages,
                isLoading = false,
                isLoadingMore = false,
                errorCode = null,
                paginationErrorCode = null,
            )
        } else {
            val incoming = page.items.filterIsInstance<com.ermao.library.shared.modules.library.GroupingSummary>().map { group ->
                GroupingCard(group.id, group.name, group.bookCount, group.representativeBooks.map { it.toCard() })
            }
            current.copy(
                works = emptyList(),
                groups = mergeById(if (reset) emptyList() else current.groups, incoming) { it.id },
                total = page.total,
                loadedPage = page.page,
                totalPages = page.totalPages,
                isLoading = false,
                isLoadingMore = false,
                errorCode = null,
                paginationErrorCode = null,
            )
        }
    }

    private fun applyFailure(scope: LibraryScope, code: String, reset: Boolean) = updateScope(scope) {
        if (reset) {
            it.copy(
                works = emptyList(),
                groups = emptyList(),
                total = 0,
                loadedPage = 0,
                isLoading = false,
                isLoadingMore = false,
                errorCode = code,
            )
        }
        else it.copy(isLoadingMore = false, paginationErrorCode = code)
    }

    private fun updateCurrent(transform: (ScopeUiState) -> ScopeUiState) =
        updateScope(mutableUiState.value.selectedScope, transform)

    private fun updateScope(scope: LibraryScope, transform: (ScopeUiState) -> ScopeUiState) {
        mutableUiState.update { state -> state.copy(scopes = state.scopes + (scope to transform(state.scopes.getValue(scope)))) }
    }

    companion object {
        private const val SEARCH_DEBOUNCE_MILLIS = 300L

        fun factory(
            repository: ContentRepository,
            context: ContentRequestContext,
            onSessionUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { LibraryViewModel(repository, context, onSessionUnauthorized) }
        }
    }
}

private fun ScopeUiState.toBooksQuery(page: Int, libraryId: String?): BooksQuery = BooksQuery(
    query = query.trim(),
    libraryId = libraryId,
    sort = sort.toShared(),
    filters = filters.toSharedFilters(),
    page = page,
)

private fun WorksFilters.toSharedFilters(): LibraryFilters = LibraryFilters(
        readingStatus = reading?.let {
            when (it) {
                ReadingFilter.Unread -> ReadingStatus.Unread
                ReadingFilter.Reading -> ReadingStatus.Reading
                ReadingFilter.Finished -> ReadingStatus.Finished
            }
        },
)

private fun LibraryScope.toDiscoveryScope(): com.ermao.library.shared.modules.library.LibraryScope = when (this) {
    LibraryScope.Books -> com.ermao.library.shared.modules.library.LibraryScope.Books
    LibraryScope.Series -> com.ermao.library.shared.modules.library.LibraryScope.Series
    LibraryScope.Authors -> com.ermao.library.shared.modules.library.LibraryScope.Authors
}

private fun ScopeUiState.toGroupingQuery(scope: LibraryScope, page: Int): GroupingQuery =
    GroupingQuery(scope.toFacetKind(), query.trim(), page)

private fun <T> mergeById(existing: List<T>, incoming: List<T>, id: (T) -> String): List<T> {
    val merged = LinkedHashMap<String, T>()
    existing.forEach { merged[id(it)] = it }
    incoming.forEach { merged[id(it)] = it }
    return merged.values.toList()
}
