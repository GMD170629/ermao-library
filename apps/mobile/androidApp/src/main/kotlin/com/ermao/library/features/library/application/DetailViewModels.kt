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
    val selectedContentTab: WorkDetailContentTab = WorkDetailContentTab.Description,
    val errorCode: String? = null,
)

enum class WorkDetailContentTab { Description, MediaVersions }

class WorkDetailViewModel(
    private val repository: ContentRepository,
    private val context: ContentRequestContext,
    private val appContext: Context,
    private val workId: String,
    private val onSessionUnauthorized: () -> Unit,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(WorkDetailUiState())
    val uiState: StateFlow<WorkDetailUiState> = mutableUiState.asStateFlow()
    private var loadGeneration: Int = 0

    init { load() }

    fun retry() = load(
        mediaKind = mutableUiState.value.selectedMediaKind,
        volumeId = mutableUiState.value.selectedVolumeId,
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

    fun selectContentTab(tab: WorkDetailContentTab) = mutableUiState.update { it.copy(selectedContentTab = tab) }

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
                        val uiContent = result.value.toUiContent()
                        AndroidContentSnapshotCache.saveDetail(appContext, context, workId, uiContent)
                        val selectedKind = mediaKind ?: uiContent.selectedMediaKind ?: uiContent.media.firstOrNull()?.kind
                        val selectedVolume = uiContent.media.firstOrNull { it.kind == selectedKind }
                            ?.volumes?.firstOrNull { it.id == volumeId }
                            ?: uiContent.media.firstOrNull { it.kind == selectedKind }?.volumes?.firstOrNull { it.selected }
                            ?: uiContent.media.firstOrNull { it.kind == selectedKind }
                            ?.volumes?.firstOrNull()
                        val previousTab = mutableUiState.value.selectedContentTab
                        mutableUiState.value = WorkDetailUiState(
                            isLoading = false,
                            content = uiContent,
                            selectedMediaKind = selectedKind,
                            selectedVolumeId = selectedVolume?.id,
                            selectedContentTab = previousTab,
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
            context: ContentRequestContext,
            appContext: Context,
            workId: String,
            onSessionUnauthorized: () -> Unit,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer {
                WorkDetailViewModel(repository, context, appContext.applicationContext, workId, onSessionUnauthorized)
            }
        }
    }
}

private fun mergeWorks(existing: List<WorkCard>, incoming: List<WorkCard>): List<WorkCard> =
    (existing + incoming).associateBy(WorkCard::id).values.toList()
