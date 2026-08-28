package com.ermao.library.features.library.application

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.toCard
import com.ermao.library.features.content.model.toFacetKind
import com.ermao.library.features.content.model.toUiContent
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.library.BookContentTarget
import com.ermao.library.shared.modules.library.loadBookContentPage
import com.ermao.library.shared.modules.library.BookContentSort
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.BookContentsQuery
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.shared.modules.library.BookResourcePageQuery
import com.ermao.library.shared.modules.library.BookDetailPresentation
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.FacetQuery
import com.ermao.library.shared.modules.library.FacetSort
import com.ermao.library.shared.modules.library.ResourceReadingUnitsPage
import com.ermao.library.shared.modules.library.ResourceReadingUnitsQuery
import com.ermao.library.shared.modules.library.domain.Resource
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

    private var facetGeneration = 0
    init { load(reset = true) }

    fun refreshAfterManagement() {
        val token = ++facetGeneration
        val lastPage = mutableUiState.value.page.coerceAtLeast(1)
        mutableUiState.update { it.copy(isLoadingMore = true) }
        viewModelScope.launch {
            val books = mutableListOf<com.ermao.library.features.content.model.BookCard>()
            for (page in 1..lastPage) {
                val sort = if (kind == LibraryScope.Series) FacetSort.SeriesIndex else FacetSort.RecentlyRead
                val result = repository.loadFacet(context, FacetQuery(kind.toFacetKind(), facetId, sort, page))
                if (token != facetGeneration) return@launch
                when (result) {
                    is ContentResult.Content -> {
                        books += result.value.books.items.map { it.toCard() }
                        if (page == lastPage || page >= result.value.books.totalPages) {
                            mutableUiState.update { it.copy(facetName = result.value.facet.name,
                                books = books.distinctBy { book -> book.id }, total = result.value.books.total,
                                page = result.value.books.page, totalPages = result.value.books.totalPages,
                                isLoading = false, isLoadingMore = false, errorCode = null, paginationErrorCode = null) }
                            break
                        }
                    }
                    is ContentResult.Failure -> {
                        if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                        mutableUiState.update { it.copy(isLoadingMore = false, paginationErrorCode = result.error.code) }
                        return@launch
                    }
                }
            }
        }
    }

    fun retry() = load(reset = true)
    fun loadNextPage() = load(reset = false)

    private fun load(reset: Boolean) {
        val current = mutableUiState.value
        if (current.isLoadingMore || (!reset && (current.isLoading || current.page >= current.totalPages))) return
        val token = if (reset) ++facetGeneration else facetGeneration
        val nextPage = if (reset) 1 else current.page + 1
        mutableUiState.update {
            if (reset) it.copy(books = emptyList(), isLoading = true, errorCode = null)
            else it.copy(isLoadingMore = true, paginationErrorCode = null)
        }
        viewModelScope.launch {
            try {
                val facetSort = if (kind == LibraryScope.Series) FacetSort.SeriesIndex else FacetSort.RecentlyRead
                val query = FacetQuery(kind.toFacetKind(), facetId, facetSort, nextPage)
                when (val result = repository.loadFacet(context, query)) {
                    is ContentResult.Content -> {
                        if (token != facetGeneration) return@launch
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
                            )
                        }
                    }
                    is ContentResult.Failure -> mutableUiState.update {
                        if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                        if (result.error.kind == AppErrorKind.Forbidden || result.error.kind == AppErrorKind.NotFoundOrUnavailable) {
                            it.copy(books = emptyList(), isLoading = false, isLoadingMore = false, errorCode = "CONTENT_NOT_ACCESSIBLE")
                        } else if (reset) it.copy(books = emptyList(), isLoading = false, errorCode = result.error.code)
                        else it.copy(isLoadingMore = false, paginationErrorCode = result.error.code)
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update {
                    if (reset) it.copy(books = emptyList(), isLoading = false, errorCode = "CONTENT_LOAD_FAILED")
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
    val isBookRoot: Boolean = true,
    val rootSourceNodeId: String? = null,
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
    val isMultiDownloadVisible: Boolean = false,
    val multiDownloadRootNodeId: String? = null,
    val multiDownloadChildrenByNodeId: Map<String, List<BookContentEntry>> = emptyMap(),
    val multiDownloadDescendantResourceIdsByNodeId: Map<String, Set<String>> = emptyMap(),
    val multiDownloadExpandedNodeIds: Set<String> = emptySet(),
    val multiDownloadLoadingNodeIds: Set<String> = emptySet(),
    val isMultiDownloadResourcesLoading: Boolean = false,
    val multiDownloadResources: List<ResourceContent> = emptyList(),
    val multiDownloadErrorCode: String? = null,
) {
}

class WorkDetailViewModel(
    private val repository: ContentRepository,
    private val shelfRepository: ShelfRepository,
    private val context: ContentRequestContext,
    private val appContext: Context,
    private val bookId: String,
    private val onSessionUnauthorized: () -> Unit,
    private val target: BookContentTarget = BookContentTarget.Root,
    private val savedState: SavedStateHandle,
) : ViewModel() {
    private var multiDownloadGeneration = 0L
    private val mutableUiState = MutableStateFlow(WorkDetailUiState())
    val uiState: StateFlow<WorkDetailUiState> = mutableUiState.asStateFlow()
    private var loadGeneration = 0
    private var surfaceGeneration = 0
    private val latestProgressUpdatesByResourceId = mutableMapOf<String, ReaderProgressPresentationUpdate>()

    init {
        viewModelScope.launch {
            (appContext as ErmaoLibraryApplication).readerProgressPresentationCenter.updates.collect { update ->
                if (update.namespaceKey == context.presentationKey() && update.bookId == bookId) {
                    val previous = latestProgressUpdatesByResourceId[update.resourceId]
                    if (previous != null && previous.capturedAtEpochMillis > update.capturedAtEpochMillis) return@collect
                    latestProgressUpdatesByResourceId[update.resourceId] = update
                    mutableUiState.update { state ->
                        val current = state.content ?: return@update state
                        val content = latestProgressUpdatesByResourceId.values.sortedBy { it.capturedAtEpochMillis }
                            .fold(current) { result, progress -> result.applying(progress, state.selectedResourceId) }
                        if (content === state.content) return@update state
                        state.copy(content = content)
                    }
                }
            }
        }
        load()
    }

    fun retry() = load()

    fun refresh() = load(showBlockingLoading = false)

    fun refreshAfterReadingStatusChange(resourceId: String) {
        latestProgressUpdatesByResourceId.remove(resourceId)
        load(showBlockingLoading = false)
    }

    fun refreshAfterBookReadingStatusChange() {
        latestProgressUpdatesByResourceId.clear()
        load(showBlockingLoading = false)
    }

    fun selectContentsSort(sort: BookContentSort) {
        mutableUiState.update { it.copy(contentsSort = sort) }
        savedState["contentSort"] = sort.name
        savedState["contentPage"] = 1
        load(showBlockingLoading = false)
    }

    fun selectContentsPage(page: Int) {
        savedState["contentPage"] = page
        load(showBlockingLoading = false)
    }

    fun selectReadingUnitsPage(page: Int) {
        savedState["readingUnitsPage"] = page
        val resourceId = mutableUiState.value.selectedResourceId ?: return
        loadReadingUnits(resourceId, page)
    }

    fun retrySurface() {
        val state = mutableUiState.value
        if (state.presentation == BookDetailPresentation.ResourceDetail) {
            state.selectedResourceId?.let { loadReadingUnits(it, state.readingUnits?.page ?: 1) }
        } else {
            load(showBlockingLoading = false)
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

    fun openMultiDownload() {
        val generation = ++multiDownloadGeneration
        val resources = mutableUiState.value.content?.resources.orEmpty()
        mutableUiState.update {
            it.copy(
                isMultiDownloadVisible = true,
                multiDownloadRootNodeId = null,
                multiDownloadChildrenByNodeId = emptyMap(),
                multiDownloadDescendantResourceIdsByNodeId = emptyMap(),
                multiDownloadExpandedNodeIds = emptySet(),
                multiDownloadLoadingNodeIds = emptySet(),
                isMultiDownloadResourcesLoading = true,
                multiDownloadResources = resources,
                multiDownloadErrorCode = null,
            )
        }
        loadMultiDownloadResources(generation)
        loadMultiDownloadFolder(sourceNodeId = mutableUiState.value.contents?.currentSourceNodeId, expand = true, generation = generation)
    }

    fun dismissMultiDownload() {
        multiDownloadGeneration += 1
        mutableUiState.update { it.copy(
            isMultiDownloadVisible = false,
            multiDownloadRootNodeId = null,
            multiDownloadChildrenByNodeId = emptyMap(),
            multiDownloadDescendantResourceIdsByNodeId = emptyMap(),
            multiDownloadExpandedNodeIds = emptySet(),
            multiDownloadLoadingNodeIds = emptySet(),
            isMultiDownloadResourcesLoading = false,
            multiDownloadResources = emptyList(),
            multiDownloadErrorCode = null,
        ) }
    }

    fun retryMultiDownload() {
        val generation = ++multiDownloadGeneration
        mutableUiState.update {
            it.copy(
                multiDownloadRootNodeId = null,
                multiDownloadChildrenByNodeId = emptyMap(),
                multiDownloadDescendantResourceIdsByNodeId = emptyMap(),
                multiDownloadExpandedNodeIds = emptySet(),
                multiDownloadLoadingNodeIds = emptySet(),
                isMultiDownloadResourcesLoading = true,
                multiDownloadErrorCode = null,
            )
        }
        loadMultiDownloadResources(generation)
        loadMultiDownloadFolder(sourceNodeId = mutableUiState.value.contents?.currentSourceNodeId, expand = true, generation = generation)
    }

    fun toggleMultiDownloadFolder(sourceNodeId: String) {
        val state = mutableUiState.value
        if (sourceNodeId in state.multiDownloadExpandedNodeIds) {
            mutableUiState.update {
                it.copy(multiDownloadExpandedNodeIds = it.multiDownloadExpandedNodeIds - sourceNodeId)
            }
            return
        }
        mutableUiState.update {
            it.copy(multiDownloadExpandedNodeIds = it.multiDownloadExpandedNodeIds + sourceNodeId)
        }
        if (state.multiDownloadChildrenByNodeId[sourceNodeId] == null) {
            loadMultiDownloadFolder(sourceNodeId, expand = true, generation = multiDownloadGeneration)
        }
    }

    fun ensureMultiDownloadFolderLoaded(sourceNodeId: String) {
        val state = mutableUiState.value
        if (state.multiDownloadChildrenByNodeId[sourceNodeId] == null &&
            sourceNodeId !in state.multiDownloadLoadingNodeIds
        ) {
            loadMultiDownloadFolder(sourceNodeId, expand = false, generation = multiDownloadGeneration)
        }
    }
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

    private fun load(showBlockingLoading: Boolean = true) {
        if (!showBlockingLoading && mutableUiState.value.isLoading) return
        val generation = ++loadGeneration
        surfaceGeneration += 1
        val sort = BookContentSort.entries.firstOrNull { it.name == savedState.get<String>("contentSort") }
            ?: mutableUiState.value.contentsSort
        val page = savedState.get<Int>("contentPage")?.coerceAtLeast(1) ?: 1
        mutableUiState.update {
            it.copy(isLoading = showBlockingLoading && it.content == null, isSurfaceLoading = true, errorCode = null)
        }
        viewModelScope.launch {
            when (val result = loadBookContentPage(repository, context, bookId, target, sort, page)) {
                is ContentResult.Content -> {
                    if (generation != loadGeneration) return@launch
                    val snapshot = result.value
                    val resourceId = (snapshot.target as? BookContentTarget.ResourceDetail)?.resourceId
                    val base = snapshot.book.toUiContent()
                    val content = latestProgressUpdatesByResourceId.values.sortedBy { it.capturedAtEpochMillis }.fold(base) { current, update ->
                        current.applying(update, resourceId)
                    }
                    mutableUiState.update { state ->
                        state.copy(
                            isLoading = false,
                            isSurfaceLoading = false,
                            content = content,
                            isBookRoot = target == BookContentTarget.Root,
                            rootSourceNodeId = snapshot.book.sourceNodeId,
                            selectedResourceId = resourceId,
                            presentation = if (resourceId == null) BookDetailPresentation.ContentBrowser else BookDetailPresentation.ResourceDetail,
                            contents = snapshot.contents ?: state.contents,
                            contentsSort = sort,
                            surfaceErrorCode = null,
                        )
                    }
                    if (resourceId != null) loadReadingUnits(
                        resourceId, savedState.get<Int>("readingUnitsPage")?.coerceAtLeast(1) ?: 1,
                    )
                }
                is ContentResult.Failure -> mutableUiState.update {
                    if (generation != loadGeneration) return@update it
                    if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                    val inaccessible = result.error.kind in setOf(
                        AppErrorKind.Forbidden, AppErrorKind.NotFoundOrUnavailable, AppErrorKind.Gone,
                    )
                    it.copy(
                        isLoading = false,
                        isSurfaceLoading = false,
                        content = if (inaccessible) null else it.content,
                        errorCode = result.error.code,
                        surfaceErrorCode = result.error.code,
                    )
                }
            }
        }
    }

    private fun loadMultiDownloadResources(generation: Long) {
        viewModelScope.launch {
            try {
                val resources = mutableListOf<Resource>()
                var pageNumber = 1
                while (true) {
                    when (val result = repository.loadBookResources(
                        context,
                        BookResourcePageQuery(
                            bookId = bookId,
                            page = pageNumber,
                            pageSize = 100,
                        ),
                    )) {
                        is ContentResult.Content -> {
                            resources += result.value.resources
                            if (pageNumber >= result.value.totalPages) break
                            pageNumber += 1
                        }
                        is ContentResult.Failure -> {
                            if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                            if (generation == multiDownloadGeneration) {
                                mutableUiState.update {
                                    it.copy(
                                        isMultiDownloadResourcesLoading = false,
                                        multiDownloadErrorCode = result.error.code,
                                    )
                                }
                            }
                            return@launch
                        }
                    }
                }
                if (generation != multiDownloadGeneration) return@launch
                mutableUiState.update { state ->
                    state.copy(
                        multiDownloadResources = resources.map { resource -> resource.toUiContent() },
                        isMultiDownloadResourcesLoading = false,
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (generation == multiDownloadGeneration) {
                    mutableUiState.update {
                        it.copy(
                            isMultiDownloadResourcesLoading = false,
                            multiDownloadErrorCode = "MULTI_DOWNLOAD_RESOURCES_FAILED",
                        )
                    }
                }
            }
        }
    }

    private fun loadMultiDownloadFolder(sourceNodeId: String?, expand: Boolean, generation: Long) {
        val loadingKey = sourceNodeId ?: "__root__"
        mutableUiState.update {
            it.copy(
                multiDownloadLoadingNodeIds = it.multiDownloadLoadingNodeIds + loadingKey,
                multiDownloadErrorCode = null,
            )
        }
        viewModelScope.launch {
            try {
                var firstPage: BookContentsPage? = null
                val entries = mutableListOf<BookContentEntry>()
                var pageNumber = 1
                while (true) {
                    when (val result = repository.loadBookContents(
                        context,
                        BookContentsQuery(
                            bookId = bookId,
                            sourceNodeId = sourceNodeId,
                            sort = BookContentSort.NameAscending,
                            page = pageNumber,
                            pageSize = 200,
                        ),
                    )) {
                        is ContentResult.Content -> {
                            if (firstPage == null) firstPage = result.value
                            entries += result.value.entries
                            if (pageNumber >= result.value.totalPages) break
                            pageNumber += 1
                        }
                        is ContentResult.Failure -> {
                            if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                            if (generation != multiDownloadGeneration) return@launch
                            mutableUiState.update {
                                it.copy(
                                    multiDownloadLoadingNodeIds = it.multiDownloadLoadingNodeIds - loadingKey,
                                    multiDownloadErrorCode = result.error.code,
                                )
                            }
                            return@launch
                        }
                    }
                }
                if (generation != multiDownloadGeneration) return@launch
                val page = requireNotNull(firstPage)
                val nodeId = page.currentNode.sourceNodeId
                mutableUiState.update { state ->
                    state.copy(
                        multiDownloadRootNodeId = state.multiDownloadRootNodeId ?: nodeId,
                        multiDownloadChildrenByNodeId = state.multiDownloadChildrenByNodeId + (nodeId to entries),
                        multiDownloadDescendantResourceIdsByNodeId =
                            state.multiDownloadDescendantResourceIdsByNodeId +
                                (nodeId to page.currentResourceIds.toSet()),
                        multiDownloadExpandedNodeIds = if (expand) {
                            state.multiDownloadExpandedNodeIds + nodeId
                        } else {
                            state.multiDownloadExpandedNodeIds
                        },
                        multiDownloadLoadingNodeIds = state.multiDownloadLoadingNodeIds - loadingKey - nodeId,
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (generation == multiDownloadGeneration) mutableUiState.update {
                    it.copy(
                        multiDownloadLoadingNodeIds = it.multiDownloadLoadingNodeIds - loadingKey,
                        multiDownloadErrorCode = "MULTI_DOWNLOAD_TREE_FAILED",
                    )
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
            target: BookContentTarget = BookContentTarget.Root,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { WorkDetailViewModel(repository, shelfRepository, context, appContext.applicationContext, bookId, onSessionUnauthorized, target, createSavedStateHandle()) }
        }
    }
}

private fun ContentRequestContext.presentationKey(): String =
    "${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}"

internal fun BookDetailContent.applying(update: ReaderProgressPresentationUpdate, selectedResourceId: String?): BookDetailContent {
    if (book.id != update.bookId) return this
    if (selectedResourceId != update.resourceId) return copy(
        continueResourceId = update.resourceId,
        resources = resources.map { resource ->
            if (resource.id == update.resourceId) resource.copy(progressPercent = update.percent.toInt().coerceIn(0, 100)) else resource
        },
    )
    val units = readingUnits.map { ReaderChapterUnit(href = it.href, sortOrder = it.sortOrder, readingOrderPosition = it.readingOrderPosition) }
    val states = resolveReaderChapterStatesFromLocation(units, update.location, update.percent)
    val progress = update.percent.toInt().coerceIn(0, 100)
    return copy(
        book = book.copy(progressPercent = progress),
        continueResourceId = update.resourceId,
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
