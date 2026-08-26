package com.ermao.library.features.library.application

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.freshness
import com.ermao.library.features.content.model.toCard
import com.ermao.library.features.content.model.toFacetKind
import com.ermao.library.features.content.model.toUiContent
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.library.BookDetailQuery
import com.ermao.library.shared.modules.library.BookContentSort
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.BookContentsQuery
import com.ermao.library.shared.modules.library.BookDetailPresentation
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.FacetQuery
import com.ermao.library.shared.modules.library.FacetSort
import com.ermao.library.shared.modules.library.ResourceReadingUnitsPage
import com.ermao.library.shared.modules.library.ResourceReadingUnitsQuery
import com.ermao.library.shared.modules.library.selectBookDetailPresentation
import com.ermao.library.shared.modules.reader.ReaderChapterState
import com.ermao.library.shared.modules.reader.ReaderChapterUnit
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.resolveReaderChapterStatesFromLocation
import com.ermao.library.shared.modules.shelf.application.ShelfRepository
import com.ermao.library.shared.modules.shelf.domain.ShelfErrorKind
import com.ermao.library.shared.modules.shelf.domain.ShelfMembership
import com.ermao.library.shared.modules.shelf.domain.ShelfMembershipChange
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import com.ermao.library.shared.modules.shelf.domain.ShelfSummary
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class FacetUiState(
    val facetName: String? = null,
    val books: List<BookCard> = emptyList(),
    val total: Int = 0,
    val page: Int = 0,
    val totalPages: Int = 1,
    val isLoading: Boolean = true,
    val isLoadingMore: Boolean = false,
    val errorCode: String? = null,
    val paginationErrorCode: String? = null,
    val freshness: ContentFreshness = ContentFreshness.Fresh,
) {
}

class FacetViewModel(
    private val repository: ContentRepository,
    private val context: ContentRequestContext,
    private val kind: LibraryScope,
    private val facetId: String,
    private val onSessionUnauthorized: () -> Unit,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(FacetUiState())
    val uiState: StateFlow<FacetUiState> = mutableUiState.asStateFlow()

    init { load(reset = true) }

    fun retry() = load(reset = true)
    fun loadNextPage() = load(reset = false)

    private fun load(reset: Boolean) {
        val current = mutableUiState.value
        if (current.isLoadingMore || (!reset && (current.isLoading || current.page >= current.totalPages))) return
        val nextPage = if (reset) 1 else current.page + 1
        mutableUiState.update {
            if (reset) it.copy(isLoading = true, errorCode = null)
            else it.copy(isLoadingMore = true, paginationErrorCode = null)
        }
        viewModelScope.launch {
            try {
                val facetSort = if (kind == LibraryScope.Series) FacetSort.SeriesIndex else FacetSort.RecentlyRead
                val query = FacetQuery(kind.toFacetKind(), facetId, facetSort, nextPage)
                when (val result = repository.loadFacet(context, query)) {
                    is ContentResult.Content -> {
                        val books = result.value.books.items.map { it.toCard() }
                        mutableUiState.update { state ->
                            state.copy(
                                facetName = result.value.facet.name,
                                books = mergeBooks(if (reset) emptyList() else state.books, books),
                                total = result.value.books.total,
                                page = result.value.books.page,
                                totalPages = result.value.books.totalPages,
                                isLoading = false,
                                isLoadingMore = false,
                                errorCode = null,
                                paginationErrorCode = null,
                                freshness = result.freshness(),
                            )
                        }
                    }
                    is ContentResult.Failure -> mutableUiState.update {
                        if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                        if (result.error.kind == AppErrorKind.Forbidden || result.error.kind == AppErrorKind.NotFoundOrUnavailable) {
                            it.copy(books = emptyList(), isLoading = false, isLoadingMore = false, errorCode = "CONTENT_NOT_ACCESSIBLE")
                        } else if (reset && it.books.isEmpty()) it.copy(isLoading = false, errorCode = result.error.code)
                        else if (reset) it.copy(isLoading = false, freshness = ContentFreshness.Stale)
                        else it.copy(isLoadingMore = false, paginationErrorCode = result.error.code)
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update {
                    if (reset && it.books.isEmpty()) it.copy(isLoading = false, errorCode = "CONTENT_LOAD_FAILED")
                    else if (reset) it.copy(isLoading = false, freshness = ContentFreshness.Stale)
                    else it.copy(isLoadingMore = false, paginationErrorCode = "CONTENT_LOAD_FAILED")
                }
            }
        }
    }

    companion object {
        fun factory(
            repository: ContentRepository,
            context: ContentRequestContext,
            kind: LibraryScope,
            facetId: String,
            onSessionUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { FacetViewModel(repository, context, kind, facetId, onSessionUnauthorized) }
        }
    }
}

data class WorkDetailUiState(
    val isLoading: Boolean = true,
    val content: BookDetailContent? = null,
    val selectedResourceId: String? = null,
    val presentation: BookDetailPresentation = BookDetailPresentation.ContentBrowser,
    val contents: BookContentsPage? = null,
    val contentsSort: BookContentSort = BookContentSort.NameAscending,
    val readingUnits: ResourceReadingUnitsPage? = null,
    val isSurfaceLoading: Boolean = false,
    val surfaceErrorCode: String? = null,
    val errorCode: String? = null,
    val shelves: List<ShelfSummary> = emptyList(),
    val selectedShelfIds: Set<String> = emptySet(),
    val isShelfPickerVisible: Boolean = false,
    val isLoadingShelves: Boolean = false,
    val isSavingShelves: Boolean = false,
    val shelfErrorCode: String? = null,
    val shelfSaveCompleted: Boolean = false,
) {
}

class WorkDetailViewModel(
    private val repository: ContentRepository,
    private val shelfRepository: ShelfRepository,
    private val context: ContentRequestContext,
    private val appContext: Context,
    private val bookId: String,
    private val onSessionUnauthorized: () -> Unit,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(WorkDetailUiState())
    val uiState: StateFlow<WorkDetailUiState> = mutableUiState.asStateFlow()
    private var loadGeneration = 0
    private var surfaceGeneration = 0
    private val latestProgressUpdatesByResourceId = mutableMapOf<String, ReaderProgressPresentationUpdate>()

    init {
        viewModelScope.launch {
            (appContext as ErmaoLibraryApplication).readerProgressPresentationCenter.updates.collect { update ->
                if (update.namespaceKey == context.presentationKey() && update.bookId == bookId) {
                    latestProgressUpdatesByResourceId[update.resourceId] = update
                    mutableUiState.update { state ->
                        val content = state.content?.applying(update, state.selectedResourceId) ?: return@update state
                        if (content === state.content) return@update state
                        state.copy(content = content)
                    }
                }
            }
        }
        load()
    }

    fun retry() = load(resourceId = mutableUiState.value.selectedResourceId)

    fun refresh() = load(resourceId = mutableUiState.value.selectedResourceId, showBlockingLoading = false)

    fun selectResource(resourceId: String) = loadReadingUnits(resourceId, page = 1)

    fun showContentBrowser() {
        val state = mutableUiState.value
        mutableUiState.update {
            it.copy(
                presentation = BookDetailPresentation.ContentBrowser,
                selectedResourceId = null,
                readingUnits = null,
            )
        }
        loadContents(state.contents?.currentSourceNodeId, page = state.contents?.page ?: 1, sort = state.contentsSort)
    }

    fun openSourceNode(sourceNodeId: String?) =
        loadContents(sourceNodeId, page = 1, sort = mutableUiState.value.contentsSort)

    fun selectContentsSort(sort: BookContentSort) =
        loadContents(mutableUiState.value.contents?.currentSourceNodeId, page = 1, sort = sort)

    fun selectContentsPage(page: Int) =
        loadContents(mutableUiState.value.contents?.currentSourceNodeId, page = page, sort = mutableUiState.value.contentsSort)

    fun selectReadingUnitsPage(page: Int) {
        val resourceId = mutableUiState.value.selectedResourceId ?: return
        loadReadingUnits(resourceId, page)
    }

    fun retrySurface() {
        val state = mutableUiState.value
        if (state.presentation == BookDetailPresentation.ResourceDetail) {
            state.selectedResourceId?.let { loadReadingUnits(it, state.readingUnits?.page ?: 1) }
        } else {
            loadContents(state.contents?.currentSourceNodeId, state.contents?.page ?: 1, state.contentsSort)
        }
    }

    fun openShelfPicker() {
        mutableUiState.update { it.copy(isShelfPickerVisible = true, isLoadingShelves = true, shelfErrorCode = null, shelfSaveCompleted = false) }
        viewModelScope.launch {
            when (val result = shelfRepository.loadShelves(ShelfRequestContext(context.profile, context.namespace), bookId)) {
                is ShelfResult.Content -> mutableUiState.update { it.copy(
                    shelves = result.value,
                    selectedShelfIds = result.value.filter(ShelfSummary::containsBook).map(ShelfSummary::id).toSet(),
                    isLoadingShelves = false,
                ) }
                is ShelfResult.Failure -> mutableUiState.update {
                    if (result.error.kind == ShelfErrorKind.Unauthorized) onSessionUnauthorized()
                    it.copy(isLoadingShelves = false, shelfErrorCode = result.error.code)
                }
            }
        }
    }

    fun dismissShelfPicker() = mutableUiState.update { it.copy(isShelfPickerVisible = false, shelfErrorCode = null, shelfSaveCompleted = false) }
    fun consumeShelfSaveCompleted() = mutableUiState.update { it.copy(shelfSaveCompleted = false) }
    fun toggleShelf(shelfId: String) = mutableUiState.update { state ->
        val shelf = state.shelves.firstOrNull { it.id == shelfId }
        if (state.isSavingShelves || shelf?.kind != com.ermao.library.shared.modules.shelf.domain.ShelfKind.Static) state
        else state.copy(selectedShelfIds = state.selectedShelfIds.toMutableSet().apply { if (!add(shelfId)) remove(shelfId) })
    }

    fun saveShelves() {
        val state = mutableUiState.value
        if (state.isSavingShelves || state.isLoadingShelves) return
        val original = state.shelves.filter(ShelfSummary::containsBook).map(ShelfSummary::id).toSet()
        val additions = state.selectedShelfIds - original
        val removals = original - state.selectedShelfIds
        if (additions.isEmpty() && removals.isEmpty()) {
            mutableUiState.update { it.copy(isShelfPickerVisible = false, shelfSaveCompleted = true) }
            return
        }
        mutableUiState.update { it.copy(isSavingShelves = true, shelfErrorCode = null) }
        viewModelScope.launch {
            val shelfContext = ShelfRequestContext(context.profile, context.namespace)
            val staticShelves = state.shelves.associateBy(ShelfSummary::id)
            val changes = additions.mapNotNull { id -> staticShelves[id]?.let { ShelfMembershipChange(bookId, id, it.kind, ShelfMembership.Add) } } +
                removals.mapNotNull { id -> staticShelves[id]?.let { ShelfMembershipChange(bookId, id, it.kind, ShelfMembership.Remove) } }
            var failure: ShelfResult.Failure? = null
            for (change in changes) {
                when (val result = shelfRepository.updateMembership(shelfContext, change)) {
                    is ShelfResult.Content -> Unit
                    is ShelfResult.Failure -> { failure = result; break }
                }
            }
            mutableUiState.update { current ->
                if (failure == null) current.copy(
                    shelves = current.shelves.map { it.copy(containsBook = it.id in current.selectedShelfIds) },
                    isShelfPickerVisible = false,
                    isSavingShelves = false,
                    shelfSaveCompleted = true,
                ) else {
                    if (failure.error.kind == ShelfErrorKind.Unauthorized) onSessionUnauthorized()
                    current.copy(isSavingShelves = false, shelfErrorCode = failure.error.code)
                }
            }
        }
    }

    private fun load(resourceId: String? = null, showBlockingLoading: Boolean = true) {
        val generation = ++loadGeneration
        mutableUiState.update { it.copy(isLoading = showBlockingLoading, errorCode = null) }
        viewModelScope.launch {
            try {
                when (val result = repository.loadBookDetail(context, BookDetailQuery(bookId, resourceId))) {
                    is ContentResult.Content -> {
                        if (generation != loadGeneration) return@launch
                        val baseContent = result.value.toUiContent()
                        val detailSelection = selectBookDetailPresentation(result.value.resources, resourceId)
                        val selectedResourceId = detailSelection.resourceId
                        val uiContent = selectedResourceId?.let(latestProgressUpdatesByResourceId::get)
                            ?.let { baseContent.applying(it, selectedResourceId) } ?: baseContent
                        val shelfState = mutableUiState.value
                        mutableUiState.value = WorkDetailUiState(
                            isLoading = false,
                            content = uiContent,
                            selectedResourceId = selectedResourceId,
                            presentation = detailSelection.presentation,
                            shelves = shelfState.shelves,
                            selectedShelfIds = shelfState.selectedShelfIds,
                            isShelfPickerVisible = shelfState.isShelfPickerVisible,
                            isLoadingShelves = shelfState.isLoadingShelves,
                            isSavingShelves = shelfState.isSavingShelves,
                            shelfErrorCode = shelfState.shelfErrorCode,
                            shelfSaveCompleted = shelfState.shelfSaveCompleted,
                        )
                        if (detailSelection.presentation == BookDetailPresentation.ResourceDetail) {
                            selectedResourceId?.let { loadReadingUnits(it, page = 1) }
                        } else {
                            loadContents(sourceNodeId = null, page = 1, sort = shelfState.contentsSort)
                        }
                    }
                    is ContentResult.Failure -> mutableUiState.update {
                        if (generation != loadGeneration) return@update it
                        if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                        if (it.content == null) it.copy(isLoading = false, errorCode = result.error.code) else it.copy(isLoading = false)
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (generation != loadGeneration) return@launch
                mutableUiState.update { if (it.content == null) it.copy(isLoading = false, errorCode = "CONTENT_LOAD_FAILED") else it.copy(isLoading = false) }
            }
        }
    }

    private fun loadContents(sourceNodeId: String?, page: Int, sort: BookContentSort) {
        val generation = ++surfaceGeneration
        mutableUiState.update {
            it.copy(
                presentation = BookDetailPresentation.ContentBrowser,
                selectedResourceId = null,
                contentsSort = sort,
                isSurfaceLoading = true,
                surfaceErrorCode = null,
            )
        }
        viewModelScope.launch {
            try {
                when (val result = repository.loadBookContents(
                    context,
                    BookContentsQuery(bookId, sourceNodeId, sort, page),
                )) {
                    is ContentResult.Content -> mutableUiState.update {
                        if (generation != surfaceGeneration) it else it.copy(
                            contents = result.value,
                            isSurfaceLoading = false,
                            surfaceErrorCode = null,
                        )
                    }
                    is ContentResult.Failure -> mutableUiState.update {
                        if (generation != surfaceGeneration) it else {
                            if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                            it.copy(isSurfaceLoading = false, surfaceErrorCode = result.error.code)
                        }
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update {
                    if (generation != surfaceGeneration) it else {
                        it.copy(isSurfaceLoading = false, surfaceErrorCode = "BOOK_CONTENTS_LOAD_FAILED")
                    }
                }
            }
        }
    }

    private fun loadReadingUnits(resourceId: String, page: Int) {
        val generation = ++surfaceGeneration
        mutableUiState.update {
            it.copy(
                presentation = BookDetailPresentation.ResourceDetail,
                selectedResourceId = resourceId,
                readingUnits = null,
                isSurfaceLoading = true,
                surfaceErrorCode = null,
            )
        }
        viewModelScope.launch {
            try {
                when (val result = repository.loadResourceReadingUnits(
                    context,
                    ResourceReadingUnitsQuery(bookId, resourceId, page, readingUnitPageSize(resourceId)),
                )) {
                    is ContentResult.Content -> mutableUiState.update { state ->
                        if (generation != surfaceGeneration) state else state.copy(
                            readingUnits = result.value,
                            isSurfaceLoading = false,
                            surfaceErrorCode = null,
                        )
                    }
                    is ContentResult.Failure -> mutableUiState.update {
                        if (generation != surfaceGeneration) it else {
                            if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                            it.copy(isSurfaceLoading = false, surfaceErrorCode = result.error.code)
                        }
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update {
                    if (generation != surfaceGeneration) it else {
                        it.copy(isSurfaceLoading = false, surfaceErrorCode = "RESOURCE_DETAIL_LOAD_FAILED")
                    }
                }
            }
        }
    }

    private fun readingUnitPageSize(resourceId: String): Int =
        when (mutableUiState.value.content?.resources?.firstOrNull { it.id == resourceId }?.readerType?.lowercase()) {
            "comic", "pdf" -> 24
            "audio" -> 100
            else -> 50
        }

    companion object {
        fun factory(
            repository: ContentRepository,
            shelfRepository: ShelfRepository,
            context: ContentRequestContext,
            appContext: Context,
            bookId: String,
            onSessionUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { WorkDetailViewModel(repository, shelfRepository, context, appContext.applicationContext, bookId, onSessionUnauthorized) }
        }
    }
}

private fun ContentRequestContext.presentationKey(): String =
    "${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}"

internal fun BookDetailContent.applying(update: ReaderProgressPresentationUpdate, selectedResourceId: String?): BookDetailContent {
    if (book.id != update.bookId || selectedResourceId != update.resourceId) return this
    val units = readingUnits.map { ReaderChapterUnit(href = it.href, sortOrder = it.sortOrder, readingOrderPosition = it.readingOrderPosition) }
    val states = resolveReaderChapterStatesFromLocation(units, update.location, update.percent)
    val progress = update.percent.toInt().coerceIn(0, 100)
    return copy(
        book = book.copy(progressPercent = progress),
        completed = update.percent >= 100.0,
        resources = resources.map { resource -> if (resource.id == update.resourceId) resource.copy(progressPercent = progress) else resource },
        readingUnits = readingUnits.mapIndexed { index, unit ->
            unit.copy(
                progressPercent = progress.takeIf { states.getOrNull(index) == ReaderChapterState.Current },
                readingState = when (states.getOrNull(index)) {
                    ReaderChapterState.Current -> ChapterReadingState.Current
                    ReaderChapterState.Read -> ChapterReadingState.Read
                    else -> ChapterReadingState.Unread
                },
            )
        },
    )
}

private fun mergeBooks(existing: List<BookCard>, incoming: List<BookCard>): List<BookCard> =
    (existing + incoming).associateBy(BookCard::id).values.toList()
