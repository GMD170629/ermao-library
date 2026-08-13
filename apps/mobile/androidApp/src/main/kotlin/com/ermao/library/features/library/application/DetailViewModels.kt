package com.ermao.library.features.library.application

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.model.WorkDetailContent
import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.freshness
import com.ermao.library.features.content.model.toCard
import com.ermao.library.features.content.model.toFacetKind
import com.ermao.library.features.content.model.toUiContent
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.FacetQuery
import com.ermao.library.shared.modules.library.FacetSort
import com.ermao.library.shared.modules.library.WorkDetailQuery
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.reader.ReaderChapterListMetadata
import com.ermao.library.shared.modules.reader.ReaderChapterState
import com.ermao.library.shared.modules.reader.ReaderChapterUnit
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.resolveReaderChapterStates
import com.ermao.library.shared.modules.shelf.application.ShelfRepository
import com.ermao.library.shared.modules.shelf.domain.ShelfMembership
import com.ermao.library.shared.modules.shelf.domain.ShelfMembershipChange
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import com.ermao.library.shared.modules.shelf.domain.ShelfSummary
import com.ermao.library.shared.modules.shelf.domain.ShelfErrorKind
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.platform.persistence.AndroidContentSnapshotCache
import com.ermao.library.shared.core.network.AppErrorKind
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class FacetUiState(
    val facetName: String? = null,
    val works: List<WorkCard> = emptyList(),
    val total: Int = 0,
    val page: Int = 0,
    val totalPages: Int = 1,
    val isLoading: Boolean = true,
    val isLoadingMore: Boolean = false,
    val errorCode: String? = null,
    val paginationErrorCode: String? = null,
    val freshness: ContentFreshness = ContentFreshness.Fresh,
)

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
                when (val restored = repository.restoreFacet(context, query)) {
                    is ContentResult.Content -> {
                        val cached = restored.value
                        val cachedWorks = cached.works.items.map { it.toCard() }
                        mutableUiState.update { state ->
                            state.copy(
                                works = mergeWorks(if (reset) emptyList() else state.works, cachedWorks),
                                facetName = cached.facet.name,
                                total = cached.works.total,
                                page = cached.works.page,
                                totalPages = cached.works.totalPages,
                                isLoading = false,
                                isLoadingMore = false,
                                freshness = restored.freshness(),
                            )
                        }
                    }
                    is ContentResult.Failure, null -> Unit
                }
                when (val result = repository.loadFacet(context, query)) {
                    is ContentResult.Content -> {
                        val works = result.value.works.items.map { it.toCard() }
                        mutableUiState.update { state -> state.copy(
                            facetName = result.value.facet.name,
                            works = mergeWorks(if (reset) emptyList() else state.works, works),
                            total = result.value.works.total,
                            page = result.value.works.page,
                            totalPages = result.value.works.totalPages,
                            isLoading = false,
                            isLoadingMore = false,
                            errorCode = null,
                            paginationErrorCode = null,
                            freshness = result.freshness(),
                        ) }
                    }
                    is ContentResult.Failure -> mutableUiState.update {
                        if (result.error.kind == AppErrorKind.Unauthorized) onSessionUnauthorized()
                        if (result.error.kind == AppErrorKind.Forbidden || result.error.kind == AppErrorKind.NotFoundOrUnavailable) {
                            it.copy(works = emptyList(), isLoading = false, isLoadingMore = false, errorCode = "CONTENT_NOT_ACCESSIBLE")
                        } else if (reset && it.works.isEmpty()) it.copy(isLoading = false, errorCode = result.error.code)
                        else if (reset) it.copy(isLoading = false, freshness = ContentFreshness.Stale)
                        else it.copy(isLoadingMore = false, paginationErrorCode = result.error.code)
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update {
                    if (reset && it.works.isEmpty()) it.copy(isLoading = false, errorCode = "CONTENT_LOAD_FAILED")
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
            initializer {
                FacetViewModel(repository, context, kind, facetId, onSessionUnauthorized)
            }
        }
    }
}

data class WorkDetailUiState(
    val isLoading: Boolean = true,
    val content: WorkDetailContent? = null,
    val selectedMediaKind: String? = null,
    val selectedVolumeId: String? = null,
    val errorCode: String? = null,
    val shelves: List<ShelfSummary> = emptyList(),
    val selectedShelfIds: Set<String> = emptySet(),
    val isShelfPickerVisible: Boolean = false,
    val isLoadingShelves: Boolean = false,
    val isSavingShelves: Boolean = false,
    val shelfErrorCode: String? = null,
    val shelfSaveCompleted: Boolean = false,
)

class WorkDetailViewModel(
    private val repository: ContentRepository,
    private val shelfRepository: ShelfRepository,
    private val context: ContentRequestContext,
    private val appContext: Context,
    private val workId: String,
    private val onSessionUnauthorized: () -> Unit,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(WorkDetailUiState())
    val uiState: StateFlow<WorkDetailUiState> = mutableUiState.asStateFlow()
    private var loadGeneration: Int = 0
    private var latestProgressUpdate: ReaderProgressPresentationUpdate? = null

    init {
        viewModelScope.launch {
            (appContext as ErmaoLibraryApplication).readerProgressPresentationCenter.updates.collect { update ->
                if (update.namespaceKey == context.presentationKey() && update.workId == workId) {
                    latestProgressUpdate = update
                    mutableUiState.update { state ->
                        val content = state.content?.applying(update) ?: return@update state
                        AndroidContentSnapshotCache.saveDetail(appContext, context, workId, content)
                        state.copy(content = content)
                    }
                }
            }
        }
        load()
    }

    fun retry() = load(
        mediaKind = mutableUiState.value.selectedMediaKind,
        volumeId = mutableUiState.value.selectedVolumeId,
    )

    fun refresh() = load(
        mediaKind = mutableUiState.value.selectedMediaKind,
        volumeId = mutableUiState.value.selectedVolumeId,
        showBlockingLoading = false,
    )

    fun selectMedia(kind: String) {
        val firstVolume = mutableUiState.value.content?.media
            ?.firstOrNull { it.kind == kind }?.volumes?.firstOrNull()
        mutableUiState.update { it.copy(selectedMediaKind = kind, selectedVolumeId = firstVolume?.id) }
        load(kind, firstVolume?.id, showBlockingLoading = false)
    }

    fun selectVolume(volumeId: String) {
        mutableUiState.update { it.copy(selectedVolumeId = volumeId) }
        load(mutableUiState.value.selectedMediaKind, volumeId, showBlockingLoading = false)
    }

    fun openShelfPicker() {
        mutableUiState.update {
            it.copy(
                isShelfPickerVisible = true,
                isLoadingShelves = true,
                shelfErrorCode = null,
                shelfSaveCompleted = false,
            )
        }
        viewModelScope.launch {
            when (val result = shelfRepository.loadShelves(
                ShelfRequestContext(context.profile, context.namespace),
                workId,
            )) {
                is ShelfResult.Content -> mutableUiState.update {
                    it.copy(
                        shelves = result.value,
                        selectedShelfIds = result.value.filter(ShelfSummary::containsWork).map(ShelfSummary::id).toSet(),
                        isLoadingShelves = false,
                    )
                }
                is ShelfResult.Failure -> mutableUiState.update {
                    if (result.error.kind == ShelfErrorKind.Unauthorized) onSessionUnauthorized()
                    it.copy(isLoadingShelves = false, shelfErrorCode = result.error.code)
                }
            }
        }
    }

    fun dismissShelfPicker() = mutableUiState.update {
        it.copy(isShelfPickerVisible = false, shelfErrorCode = null, shelfSaveCompleted = false)
    }

    fun toggleShelf(shelfId: String) = mutableUiState.update { state ->
        if (state.isSavingShelves) state else state.copy(
            selectedShelfIds = state.selectedShelfIds.toMutableSet().apply {
                if (!add(shelfId)) remove(shelfId)
            },
        )
    }

    fun saveShelves() {
        val state = mutableUiState.value
        if (state.isSavingShelves || state.isLoadingShelves) return
        val original = state.shelves.filter(ShelfSummary::containsWork).map(ShelfSummary::id).toSet()
        val additions = state.selectedShelfIds - original
        val removals = original - state.selectedShelfIds
        if (additions.isEmpty() && removals.isEmpty()) {
            mutableUiState.update { it.copy(isShelfPickerVisible = false, shelfSaveCompleted = true) }
            return
        }
        mutableUiState.update { it.copy(isSavingShelves = true, shelfErrorCode = null) }
        viewModelScope.launch {
            val shelfContext = ShelfRequestContext(context.profile, context.namespace)
            val changes = additions.map { ShelfMembershipChange(workId, it, ShelfMembership.Add) } +
                removals.map { ShelfMembershipChange(workId, it, ShelfMembership.Remove) }
            var failure: ShelfResult.Failure? = null
            for (change in changes) {
                when (val result = shelfRepository.updateMembership(shelfContext, change)) {
                    is ShelfResult.Content -> Unit
                    is ShelfResult.Failure -> { failure = result; break }
                }
            }
            mutableUiState.update { current ->
                if (failure == null) {
                    current.copy(
                        shelves = current.shelves.map { it.copy(containsWork = it.id in current.selectedShelfIds) },
                        isShelfPickerVisible = false,
                        isSavingShelves = false,
                        shelfSaveCompleted = true,
                    )
                } else {
                    if (failure.error.kind == ShelfErrorKind.Unauthorized) onSessionUnauthorized()
                    current.copy(isSavingShelves = false, shelfErrorCode = failure.error.code)
                }
            }
        }
    }

    private fun load(
        mediaKind: String? = null,
        volumeId: String? = null,
        showBlockingLoading: Boolean = true,
    ) {
        val generation = ++loadGeneration
        mutableUiState.update { it.copy(isLoading = showBlockingLoading, errorCode = null) }
        viewModelScope.launch {
            try {
                if (mediaKind == null && volumeId == null) AndroidContentSnapshotCache.loadDetail(appContext, context, workId)?.let { cached ->
                    mutableUiState.update {
                        it.copy(
                            isLoading = false,
                            content = cached.content,
                            selectedMediaKind = cached.content.selectedMediaKind ?: cached.content.media.firstOrNull()?.kind,
                        )
                    }
                }
                val requestedKind = mediaKind?.let(::MediaKind)
                when (val result = repository.loadWorkDetail(context, WorkDetailQuery(workId, requestedKind, volumeId))) {
                    is ContentResult.Content -> {
                        if (generation != loadGeneration) return@launch
                        val uiContent = latestProgressUpdate?.let { result.value.toUiContent().applying(it) }
                            ?: result.value.toUiContent()
                        AndroidContentSnapshotCache.saveDetail(appContext, context, workId, uiContent)
                        val selectedKind = mediaKind ?: uiContent.selectedMediaKind ?: uiContent.media.firstOrNull()?.kind
                        val selectedVolume = uiContent.media.firstOrNull { it.kind == selectedKind }
                            ?.volumes?.firstOrNull { it.id == volumeId }
                            ?: uiContent.media.firstOrNull { it.kind == selectedKind }?.volumes?.firstOrNull { it.selected }
                            ?: uiContent.media.firstOrNull { it.kind == selectedKind }
                            ?.volumes?.firstOrNull()
                        val shelfState = mutableUiState.value
                        mutableUiState.value = WorkDetailUiState(
                            isLoading = false,
                            content = uiContent,
                            selectedMediaKind = selectedKind,
                            selectedVolumeId = selectedVolume?.id,
                            shelves = shelfState.shelves,
                            selectedShelfIds = shelfState.selectedShelfIds,
                            isShelfPickerVisible = shelfState.isShelfPickerVisible,
                            isLoadingShelves = shelfState.isLoadingShelves,
                            isSavingShelves = shelfState.isSavingShelves,
                            shelfErrorCode = shelfState.shelfErrorCode,
                            shelfSaveCompleted = shelfState.shelfSaveCompleted,
                        )
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
                mutableUiState.update {
                    if (it.content == null) it.copy(isLoading = false, errorCode = "CONTENT_LOAD_FAILED")
                    else it.copy(isLoading = false)
                }
            }
        }
    }

    companion object {
        fun factory(
            repository: ContentRepository,
            shelfRepository: ShelfRepository,
            context: ContentRequestContext,
            appContext: Context,
            workId: String,
            onSessionUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer {
                WorkDetailViewModel(repository, shelfRepository, context, appContext.applicationContext, workId, onSessionUnauthorized)
            }
        }
    }
}

private fun ContentRequestContext.presentationKey(): String =
    "${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}"

private fun WorkDetailContent.applying(update: ReaderProgressPresentationUpdate): WorkDetailContent {
    if (work.id != update.workId) return this
    val units = readingUnits.map { ReaderChapterUnit(it.href, it.sortOrder) }
    val states = resolveReaderChapterStates(
        units = units,
        currentHref = update.currentHref,
        currentSortOrder = null,
        progressPercent = update.percent,
        metadata = ReaderChapterListMetadata(pageSize = maxOf(1, units.size)),
    )
    return copy(
        work = work.copy(progressPercent = update.percent.toInt().coerceIn(0, 100)),
        completed = update.percent >= 100.0,
        media = media.map { mediaVersion ->
            mediaVersion.copy(
                volumes = mediaVersion.volumes.map { volume ->
                    if (volume.id == update.volumeId) {
                        volume.copy(progressPercent = update.percent.toInt().coerceIn(0, 100))
                    } else {
                        volume
                    }
                },
            )
        },
        readingUnits = readingUnits.mapIndexed { index, unit ->
            unit.copy(
                progressPercent = update.percent.toInt().takeIf { states[index] == ReaderChapterState.Current },
                readingState = when (states[index]) {
                    ReaderChapterState.Current -> ChapterReadingState.Current
                    ReaderChapterState.Read -> ChapterReadingState.Read
                    ReaderChapterState.Unread -> ChapterReadingState.Unread
                },
            )
        },
    )
}

private fun mergeWorks(existing: List<WorkCard>, incoming: List<WorkCard>): List<WorkCard> =
    (existing + incoming).associateBy(WorkCard::id).values.toList()
