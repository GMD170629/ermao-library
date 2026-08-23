package com.ermao.library.features.library.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.Sort
import androidx.compose.material.icons.automirrored.outlined.ViewList
import androidx.compose.material.icons.outlined.FilterList
import androidx.compose.material.icons.outlined.GridView
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.key
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.ContentSort
import com.ermao.library.features.content.model.ContentViewMode
import com.ermao.library.features.content.model.GroupingCard
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.MediaFilter
import com.ermao.library.features.content.model.ReadingFilter
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.WorksFilters
import com.ermao.library.features.content.ui.CoverRole
import com.ermao.library.features.content.ui.BookCover
import com.ermao.library.features.content.ui.BookGridItem
import com.ermao.library.features.content.ui.BookListItem
import com.ermao.library.features.content.ui.responsiveCoverColumnCount
import com.ermao.library.features.library.application.LibraryUiState
import com.ermao.library.features.library.application.ScrollAnchor
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.ui.components.WarmPageModalBottomSheet
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.OfflineFilterAvailability
import com.ermao.library.ui.components.WarmPageActionMenu
import com.ermao.library.ui.components.WarmPageChoice
import com.ermao.library.ui.components.WarmPageEmptyState
import com.ermao.library.ui.components.WarmPageErrorState
import com.ermao.library.ui.components.WarmPageIconAction
import com.ermao.library.ui.components.WarmPageInlineFilter
import com.ermao.library.ui.components.WarmPageLoadingState
import com.ermao.library.ui.components.WarmPageMenuAction
import com.ermao.library.ui.components.WarmPageMenuOption
import com.ermao.library.ui.components.WarmPagePaginationError
import com.ermao.library.ui.components.WarmPagePaginationLoading
import com.ermao.library.ui.components.WarmPagePermissionGate
import com.ermao.library.ui.components.WarmPagePrimaryAction
import com.ermao.library.ui.components.WarmPageScaffold
import com.ermao.library.ui.components.WarmPageSearchField
import com.ermao.library.ui.components.WarmPageSegmentedControl
import com.ermao.library.ui.components.WarmPageSingleChoiceMenu
import com.ermao.library.ui.components.WarmPageStaleStatus
import com.ermao.library.ui.components.WarmPageTextAction
import com.ermao.library.ui.components.WarmPageTopBarRole
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.flow.distinctUntilChanged

private enum class LibraryMenuState {
    Root,
    Sort,
    View,
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(
    state: LibraryUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onSelectScope: (LibraryScope) -> Unit,
    onQueryChanged: (String) -> Unit,
    onClearQuery: () -> Unit,
    onSelectSort: (ContentSort) -> Unit,
    onSelectViewMode: (ContentViewMode) -> Unit,
    onOpenFilter: () -> Unit,
    onUpdateFilterDraft: (WorksFilters) -> Unit,
    onRemoveMediaFilter: (MediaFilter) -> Unit,
    onRemoveReadingFilter: (ReadingFilter) -> Unit,
    onClearFilters: () -> Unit,
    onApplyFilter: () -> Unit,
    onDismissFilter: () -> Unit,
    onOpenWork: (String) -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    onRetry: () -> Unit,
    onLoadNextPage: () -> Unit,
    onScrollAnchorChanged: (String?, Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val filterSheetCopy = resolveLibraryFilterSheetCopy()
    var menuState by rememberSaveable { mutableStateOf<LibraryMenuState?>(null) }
    val filterFocusRequester = remember { FocusRequester() }
    var filterWasPresented by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(state.filterDraft) {
        if (state.filterDraft != null) {
            filterWasPresented = true
        } else if (filterWasPresented) {
            filterWasPresented = false
            filterFocusRequester.requestFocus()
        }
    }
    val interactionsEnabled = state.current.errorCode != "PERMISSION_REVALIDATING"
    WarmPageScaffold(
        role = WarmPageTopBarRole.Root,
        title = stringResource(R.string.tab_library),
        modifier = modifier.testTag("tab-library"),
        actionContent = {
            if (state.selectedScope == LibraryScope.Books) {
                Box {
                    WarmPageIconAction(
                        icon = Icons.Outlined.MoreVert,
                        label = stringResource(R.string.library_more_actions),
                        enabled = interactionsEnabled,
                        onClick = { menuState = LibraryMenuState.Root },
                    )
                    LibraryOverflowMenus(
                        menuState = menuState,
                        state = state,
                        onDismiss = { menuState = null },
                        onOpenMenu = { menuState = it },
                        onSelectSort = {
                            menuState = null
                            onSelectSort(it)
                        },
                        onSelectViewMode = {
                            menuState = null
                            onSelectViewMode(it)
                        },
                    )
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            WarmPageSearchField(
                value = state.current.query,
                onValueChange = onQueryChanged,
                onClear = onClearQuery,
                clearLabel = stringResource(R.string.clear_action),
                placeholder = stringResource(state.selectedScope.searchPlaceholderResource),
                enabled = interactionsEnabled,
                modifier = Modifier
                    .padding(horizontal = theme.components.page.compactGutter)
                    .testTag("library-search"),
            )
            WarmPageSegmentedControl(
                options = LibraryScope.entries.map { scope ->
                    WarmPageChoice(scope, stringResource(scope.labelResource))
                },
                selected = state.selectedScope,
                onSelect = onSelectScope,
                enabled = interactionsEnabled,
                modifier = Modifier.padding(
                    horizontal = theme.components.page.compactGutter,
                    vertical = theme.spacing.one,
                ),
            )
            LibraryContextRow(
                state,
                onOpenFilter,
                onRemoveMediaFilter,
                onRemoveReadingFilter,
                filterFocusRequester,
                interactionsEnabled,
            )
            when (state.current.freshness) {
                ContentFreshness.Stale -> WarmPageStaleStatus(
                    message = stringResource(R.string.content_stale_banner),
                    modifier = Modifier.padding(horizontal = theme.components.page.compactGutter),
                )
                ContentFreshness.Fresh -> Unit
            }
            Box(Modifier.fillMaxSize()) {
                key(state.selectedScope) {
                    LibraryResults(
                        state = state,
                        repository = repository,
                        context = context,
                        onOpenWork = onOpenWork,
                        onOpenFacet = onOpenFacet,
                        onClearQuery = onClearQuery,
                        onRetry = onRetry,
                        onLoadNextPage = onLoadNextPage,
                        onScrollAnchorChanged = onScrollAnchorChanged,
                    )
                }
            }
        }
    }
    state.filterDraft?.let { draft ->
        FilterSheet(
            filters = draft,
            copy = filterSheetCopy,
            onChange = onUpdateFilterDraft,
            offlineAvailability = state.offlineFilterAvailability,
            onClear = onClearFilters,
            onApply = onApplyFilter,
            onDismiss = onDismissFilter,
        )
    }
}

internal data class LibraryFilterSheetCopy(
    val title: String,
    val description: String,
    val cancelAction: String,
    val clearAction: String,
    val mediaHeading: String,
    val ebook: String,
    val comic: String,
    val audiobook: String,
    val readingHeading: String,
    val unread: String,
    val reading: String,
    val finished: String,
    val offlineHeading: String,
    val downloaded: String,
    val applyAction: String,
) {
    fun mediaLabel(value: MediaFilter): String = when (value) {
        MediaFilter.Ebook -> ebook
        MediaFilter.Comic -> comic
        MediaFilter.Audiobook -> audiobook
    }

    fun readingLabel(value: ReadingFilter): String = when (value) {
        ReadingFilter.Unread -> unread
        ReadingFilter.Reading -> reading
        ReadingFilter.Finished -> finished
    }
}

@Composable
internal fun resolveLibraryFilterSheetCopy(): LibraryFilterSheetCopy = LibraryFilterSheetCopy(
    title = stringResource(R.string.library_filter_title),
    description = stringResource(R.string.library_filter_draft_description),
    cancelAction = stringResource(R.string.cancel_action),
    clearAction = stringResource(R.string.clear_all_action),
    mediaHeading = stringResource(R.string.library_filter_media),
    ebook = stringResource(R.string.media_ebook),
    comic = stringResource(R.string.media_comic),
    audiobook = stringResource(R.string.media_audiobook),
    readingHeading = stringResource(R.string.library_filter_reading),
    unread = stringResource(R.string.reading_unread),
    reading = stringResource(R.string.reading_reading),
    finished = stringResource(R.string.reading_finished),
    offlineHeading = stringResource(R.string.library_filter_offline),
    downloaded = stringResource(R.string.library_filter_downloaded),
    applyAction = stringResource(R.string.apply_action),
)

@Composable
private fun LibraryContextRow(
    state: LibraryUiState,
    onOpenFilter: () -> Unit,
    onRemoveMediaFilter: (MediaFilter) -> Unit,
    onRemoveReadingFilter: (ReadingFilter) -> Unit,
    filterFocusRequester: FocusRequester,
    enabled: Boolean,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = theme.components.page.compactGutter),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                pluralStringResource(
                    state.selectedScope.resultCountResource,
                    state.current.total,
                    state.current.total,
                ),
                style = theme.typography.callout,
                color = theme.colors.textSecondary,
            )
            if (state.selectedScope == LibraryScope.Books) {
                WarmPageTextAction(
                    label = if (state.current.filters.count == 0) {
                        stringResource(R.string.library_filter_action)
                    } else {
                        stringResource(R.string.library_filter_count, state.current.filters.count)
                    },
                    onClick = onOpenFilter,
                    enabled = enabled,
                    leadingIcon = Icons.Outlined.FilterList,
                    modifier = Modifier
                        .focusRequester(filterFocusRequester)
                        .testTag("library-filter"),
                )
            }
        }
        if (state.selectedScope == LibraryScope.Books && state.current.filters.count > 0) {
            LazyRow(
                contentPadding = PaddingValues(horizontal = theme.components.page.compactGutter),
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                items(state.current.filters.media.toList(), key = MediaFilter::name) { filter ->
                    AppliedFilterChip(stringResource(filter.labelResource)) { onRemoveMediaFilter(filter) }
                }
                items(state.current.filters.reading.toList(), key = ReadingFilter::name) { filter ->
                    AppliedFilterChip(stringResource(filter.labelResource)) { onRemoveReadingFilter(filter) }
                }
            }
        }
    }
}

@Composable
private fun AppliedFilterChip(label: String, onRemove: () -> Unit) {
    WarmPageInlineFilter(
        label = label,
        removeLabel = stringResource(R.string.library_remove_filter),
        onRemove = onRemove,
    )
}

@Composable
private fun LibraryResults(
    state: LibraryUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenWork: (String) -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    onClearQuery: () -> Unit,
    onRetry: () -> Unit,
    onLoadNextPage: () -> Unit,
    onScrollAnchorChanged: (String?, Int) -> Unit,
) {
    val current = state.current
    when {
        current.isLoading -> WarmPageLoadingState(
            title = stringResource(R.string.content_loading_title),
            message = stringResource(R.string.library_loading_message),
        )
        current.errorCode != null && current.works.isEmpty() && current.groups.isEmpty() -> when (current.errorCode) {
            "PERMISSION_REVALIDATING" -> WarmPagePermissionGate(
                title = stringResource(R.string.library_permission_revalidating_title),
                message = stringResource(R.string.library_permission_revalidating_message),
            )
            "CONTENT_NOT_ACCESSIBLE" -> WarmPageErrorState(
                title = stringResource(R.string.work_unavailable_title),
                message = stringResource(R.string.work_unavailable_message),
            )
            else -> WarmPageErrorState(
                title = stringResource(R.string.content_error_title),
                message = stringResource(R.string.content_error_message),
                retryLabel = stringResource(R.string.retry_action),
                onRetry = onRetry,
            )
        }
        current.works.isEmpty() && current.groups.isEmpty() -> WarmPageEmptyState(
            title = stringResource(
                when (state.selectedScope) {
                    LibraryScope.Books -> R.string.library_empty_works_title
                    LibraryScope.Series -> R.string.library_empty_series_title
                    LibraryScope.Authors -> R.string.library_empty_authors_title
                },
            ),
            message = stringResource(R.string.library_empty_message),
            actionLabel = stringResource(R.string.clear_search_action).takeIf { current.query.isNotBlank() },
            onAction = onClearQuery.takeIf { current.query.isNotBlank() },
        )
        state.selectedScope == LibraryScope.Books -> WorksResults(
            current.works,
            current.viewMode,
            repository,
            context,
            onOpenWork,
            current.isLoadingMore,
            current.paginationErrorCode,
            current.scrollAnchor,
            onLoadNextPage,
            onScrollAnchorChanged,
        )
        else -> GroupingResults(
            current.groups,
            state.selectedScope,
            repository,
            context,
            onOpenFacet,
            current.isLoadingMore,
            current.paginationErrorCode,
            current.scrollAnchor,
            onLoadNextPage,
            onScrollAnchorChanged,
        )
    }
}

@Composable
private fun WorksResults(
    works: List<BookCard>,
    viewMode: ContentViewMode,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenWork: (String) -> Unit,
    isLoadingMore: Boolean,
    paginationError: String?,
    scrollAnchor: ScrollAnchor,
    onLoadNextPage: () -> Unit,
    onScrollAnchorChanged: (String?, Int) -> Unit,
) {
    if (viewMode == ContentViewMode.List) {
        val initialIndex = works.indexOfFirst { it.id == scrollAnchor.itemId }.coerceAtLeast(0)
        val listState = rememberLazyListState(initialIndex, scrollAnchor.offset)
        ObserveListState(listState, works, onScrollAnchorChanged, onLoadNextPage)
        LazyColumn(
            state = listState,
            modifier = Modifier.testTag("library-works-list"),
            contentPadding = PaddingValues(bottom = WarmPageThemeValues.components.page.contentBottomInset),
        ) {
            items(works, key = BookCard::id) { work ->
                BookListItem(
                    book = work,
                    repository = repository,
                    context = context,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onOpenWork(work.id) }
                        .padding(
                            horizontal = WarmPageThemeValues.components.page.compactGutter,
                            vertical = WarmPageThemeValues.spacing.one,
                        ),
                )
            }
            paginationFooter(isLoadingMore, paginationError, onLoadNextPage)
        }
    } else {
        BoxWithConstraints {
            val fontScale = LocalDensity.current.fontScale
            val columns = responsiveCoverColumnCount(maxWidth, fontScale)
            val initialIndex = works.indexOfFirst { it.id == scrollAnchor.itemId }.coerceAtLeast(0)
            val gridState = rememberLazyGridState(initialIndex, scrollAnchor.offset)
            ObserveGridState(gridState, works, onScrollAnchorChanged, onLoadNextPage)
            LazyVerticalGrid(
                columns = GridCells.Fixed(columns),
                state = gridState,
                modifier = Modifier.testTag("library-works-grid"),
                contentPadding = PaddingValues(
                    start = WarmPageThemeValues.components.page.compactGutter,
                    end = WarmPageThemeValues.components.page.compactGutter,
                    bottom = WarmPageThemeValues.components.page.contentBottomInset,
                ),
                horizontalArrangement = Arrangement.spacedBy(WarmPageThemeValues.components.grid.horizontalGap),
                verticalArrangement = Arrangement.spacedBy(WarmPageThemeValues.components.grid.verticalGap),
            ) {
                items(works, key = BookCard::id) { work ->
                    BookGridItem(
                        work,
                        repository,
                        context,
                        Modifier.clickable { onOpenWork(work.id) },
                    )
                }
                item(span = { androidx.compose.foundation.lazy.grid.GridItemSpan(maxLineSpan) }) {
                    PaginationFooter(isLoadingMore, paginationError, onLoadNextPage)
                }
            }
        }
    }
}

@Composable
private fun GroupingResults(
    groups: List<GroupingCard>,
    scope: LibraryScope,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenFacet: (LibraryScope, String) -> Unit,
    isLoadingMore: Boolean,
    paginationError: String?,
    scrollAnchor: ScrollAnchor,
    onLoadNextPage: () -> Unit,
    onScrollAnchorChanged: (String?, Int) -> Unit,
) {
    val initialIndex = groups.indexOfFirst { it.id == scrollAnchor.itemId }.coerceAtLeast(0)
    val listState = rememberLazyListState(initialIndex, scrollAnchor.offset)
    ObserveListState(listState, groups, onScrollAnchorChanged, onLoadNextPage) { it.id }
    LazyColumn(
        state = listState,
        contentPadding = PaddingValues(
            horizontal = WarmPageThemeValues.components.page.compactGutter,
            vertical = WarmPageThemeValues.spacing.one,
        ),
    ) {
        items(groups, key = GroupingCard::id) { group ->
            GroupingRow(group, scope, repository, context, Modifier.clickable { onOpenFacet(scope, group.id) })
            HorizontalDivider(
                thickness = WarmPageThemeValues.components.dividerThickness,
                color = WarmPageThemeValues.colors.divider,
            )
        }
        paginationFooter(isLoadingMore, paginationError, onLoadNextPage)
    }
}

@Composable
private fun GroupingRow(
    group: GroupingCard,
    scope: LibraryScope,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.controls.minimumTouchTarget)
            .padding(vertical = theme.spacing.oneAndHalf),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
    ) {
        GroupingCoverStack(group.representativeBooks, repository, context)
        Column(Modifier.weight(1f)) {
            Text(group.name, style = theme.typography.headline, maxLines = 2, overflow = TextOverflow.Ellipsis)
            val representativeAuthor = group.representativeBooks.firstOrNull()?.author?.trim().orEmpty()
            val summary = if (scope == LibraryScope.Series && representativeAuthor.isNotEmpty()) {
                pluralStringResource(
                    R.plurals.library_group_summary,
                    group.bookCount,
                    representativeAuthor,
                    group.bookCount,
                )
            } else {
                pluralStringResource(R.plurals.library_group_work_count, group.bookCount, group.bookCount)
            }
            Text(summary, style = theme.typography.callout, color = theme.colors.textSecondary, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = theme.colors.textTertiary)
    }
}

@Composable
private fun GroupingCoverStack(
    works: List<BookCard>,
    repository: ContentRepository,
    context: ContentRequestContext,
) {
    val theme = WarmPageThemeValues
    Row(horizontalArrangement = Arrangement.spacedBy(theme.spacing.half)) {
        works.take(3).forEach { work ->
            BookCover(
                work,
                repository,
                context,
                CoverRole.Compact,
                Modifier.width(theme.components.covers.groupingCoverWidth),
            )
        }
    }
}

@Composable
private fun ObserveListState(
    state: LazyListState,
    works: List<BookCard>,
    onScrollAnchorChanged: (String?, Int) -> Unit,
    onLoadNextPage: () -> Unit,
) = ObserveListState(state, works, onScrollAnchorChanged, onLoadNextPage, BookCard::id)

@Composable
private fun <T> ObserveListState(
    state: LazyListState,
    items: List<T>,
    onScrollAnchorChanged: (String?, Int) -> Unit,
    onLoadNextPage: () -> Unit,
    id: (T) -> String,
) {
    LaunchedEffect(state, items) {
        snapshotFlow { state.firstVisibleItemIndex to state.firstVisibleItemScrollOffset }
            .distinctUntilChanged()
            .collect { (index, offset) -> onScrollAnchorChanged(items.getOrNull(index)?.let(id), offset) }
    }
    LaunchedEffect(state, items.size) {
        snapshotFlow { state.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0 }
            .distinctUntilChanged()
            .collect { if (items.isNotEmpty() && it >= items.lastIndex - 3) onLoadNextPage() }
    }
}

@Composable
private fun ObserveGridState(
    state: LazyGridState,
    works: List<BookCard>,
    onScrollAnchorChanged: (String?, Int) -> Unit,
    onLoadNextPage: () -> Unit,
) {
    LaunchedEffect(state, works) {
        snapshotFlow { state.firstVisibleItemIndex to state.firstVisibleItemScrollOffset }
            .distinctUntilChanged()
            .collect { (index, offset) -> onScrollAnchorChanged(works.getOrNull(index)?.id, offset) }
    }
    LaunchedEffect(state, works.size) {
        snapshotFlow { state.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0 }
            .distinctUntilChanged()
            .collect { if (works.isNotEmpty() && it >= works.lastIndex - 4) onLoadNextPage() }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.paginationFooter(
    loading: Boolean,
    error: String?,
    onRetry: () -> Unit,
) = item { PaginationFooter(loading, error, onRetry) }

@Composable
private fun PaginationFooter(loading: Boolean, error: String?, onRetry: () -> Unit) {
    if (!loading && error == null) return
    if (loading) {
        WarmPagePaginationLoading(
            message = stringResource(R.string.library_loading_more),
            modifier = Modifier.testTag("library-pagination"),
        )
    } else {
        WarmPagePaginationError(
            message = stringResource(R.string.library_pagination_error_title),
            retryLabel = stringResource(R.string.retry_action),
            onRetry = onRetry,
            modifier = Modifier.testTag("library-pagination"),
        )
    }
}

@Composable
private fun LibraryOverflowMenus(
    menuState: LibraryMenuState?,
    state: LibraryUiState,
    onDismiss: () -> Unit,
    onOpenMenu: (LibraryMenuState) -> Unit,
    onSelectSort: (ContentSort) -> Unit,
    onSelectViewMode: (ContentViewMode) -> Unit,
) {
    WarmPageActionMenu(
        title = stringResource(R.string.library_more_actions),
        expanded = menuState == LibraryMenuState.Root,
        actions = listOf(
            WarmPageMenuAction(
                LibraryMenuState.Sort,
                stringResource(R.string.library_sort_action),
                Icons.AutoMirrored.Outlined.Sort,
            ),
            WarmPageMenuAction(
                LibraryMenuState.View,
                stringResource(R.string.library_view_action),
                if (state.current.viewMode == ContentViewMode.Grid) {
                    Icons.Outlined.GridView
                } else {
                    Icons.AutoMirrored.Outlined.ViewList
                },
            ),
        ),
        onSelect = onOpenMenu,
        onDismiss = onDismiss,
    )
    WarmPageSingleChoiceMenu(
        title = stringResource(R.string.library_sort_heading),
        expanded = menuState == LibraryMenuState.Sort,
        options = ContentSort.entries.map { sort ->
            WarmPageMenuOption(sort, stringResource(sort.labelResource))
        },
        selected = state.current.sort,
        onSelect = onSelectSort,
        onDismiss = onDismiss,
        dismissLabel = stringResource(R.string.close_action),
    )
    WarmPageSingleChoiceMenu(
        title = stringResource(R.string.library_view_heading),
        expanded = menuState == LibraryMenuState.View,
        options = ContentViewMode.entries.map { mode ->
            WarmPageMenuOption(
                mode,
                stringResource(mode.labelResource),
                if (mode == ContentViewMode.Grid) Icons.Outlined.GridView else Icons.AutoMirrored.Outlined.ViewList,
            )
        },
        selected = state.current.viewMode,
        onSelect = onSelectViewMode,
        onDismiss = onDismiss,
        dismissLabel = stringResource(R.string.close_action),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun FilterSheet(
    filters: WorksFilters,
    copy: LibraryFilterSheetCopy,
    onChange: (WorksFilters) -> Unit,
    offlineAvailability: OfflineFilterAvailability,
    onClear: () -> Unit,
    onApply: () -> Unit,
    onDismiss: () -> Unit,
) {
    WarmPageModalBottomSheet(
        onDismissRequest = onDismiss,
        modifier = Modifier.testTag("library-filter-sheet"),
        skipPartiallyExpanded = true,
    ) {
        LibraryFilterSheetContent(
            filters = filters,
            copy = copy,
            onChange = onChange,
            offlineAvailability = offlineAvailability,
            onClear = onClear,
            onApply = onApply,
            onDismiss = onDismiss,
        )
    }
}

@Composable
internal fun LibraryFilterSheetContent(
    filters: WorksFilters,
    copy: LibraryFilterSheetCopy,
    onChange: (WorksFilters) -> Unit,
    offlineAvailability: OfflineFilterAvailability,
    onClear: () -> Unit,
    onApply: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(max = 640.dp),
    ) {
        LibraryFilterSheetHeader(
            title = copy.title,
            cancelLabel = copy.cancelAction,
            clearLabel = copy.clearAction,
            onCancel = onDismiss,
            onClear = onClear,
            modifier = Modifier.padding(horizontal = theme.components.page.compactGutter),
        )
        Text(
            text = copy.description,
            style = theme.typography.body,
            color = theme.colors.textSecondary,
            modifier = Modifier
                .padding(
                    horizontal = theme.components.page.compactGutter,
                    vertical = theme.spacing.one,
                ),
        )
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = theme.components.page.compactGutter)
                .testTag("library-filter-scroll"),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
        ) {
            Text(
                text = copy.mediaHeading,
                style = theme.typography.headline,
                modifier = Modifier.padding(top = theme.spacing.one),
            )
            MediaFilter.entries.forEach { value ->
                FilterRow(copy.mediaLabel(value), value in filters.media) { checked ->
                    onChange(filters.copy(media = filters.media.toggle(value, checked)))
                }
            }
            Text(
                text = copy.readingHeading,
                style = theme.typography.headline,
                modifier = Modifier.padding(top = theme.spacing.two),
            )
            ReadingFilter.entries.forEach { value ->
                FilterRow(copy.readingLabel(value), value in filters.reading) { checked ->
                    onChange(filters.copy(reading = filters.reading.toggle(value, checked)))
                }
            }
            if (offlineAvailability is OfflineFilterAvailability.Available) {
                Text(
                    text = copy.offlineHeading,
                    style = theme.typography.headline,
                    modifier = Modifier.padding(top = theme.spacing.two),
                )
                FilterRow(
                    label = copy.downloaded,
                    checked = filters.downloadedOnly,
                    onCheckedChange = { checked -> onChange(filters.copy(downloadedOnly = checked)) },
                    modifier = Modifier.testTag("library-filter-downloaded"),
                )
            }
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(
                    start = theme.components.page.compactGutter,
                    top = theme.spacing.one,
                    end = theme.components.page.compactGutter,
                    bottom = theme.spacing.two,
                ),
        ) {
            WarmPagePrimaryAction(
                label = copy.applyAction,
                onClick = onApply,
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("library-filter-apply"),
            )
        }
    }
}

@Composable
internal fun LibraryFilterSheetHeader(
    title: String,
    cancelLabel: String,
    clearLabel: String,
    onCancel: () -> Unit,
    onClear: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
    ) {
        Text(
            text = title,
            style = theme.typography.headline,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .fillMaxWidth()
                .semantics { heading() }
                .testTag("library-filter-title"),
        )
        Row(modifier = Modifier.fillMaxWidth()) {
            WarmPageTextAction(
                label = cancelLabel,
                onClick = onCancel,
                modifier = Modifier
                    .weight(1f)
                    .testTag("library-filter-cancel"),
            )
            WarmPageTextAction(
                label = clearLabel,
                onClick = onClear,
                modifier = Modifier
                    .weight(1f)
                    .testTag("library-filter-clear"),
            )
        }
    }
}

@Composable
private fun FilterRow(
    label: String,
    checked: Boolean,
    modifier: Modifier = Modifier,
    onCheckedChange: (Boolean) -> Unit,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = theme.metrics.androidMinimumTouchTarget)
            .toggleable(
                value = checked,
                role = Role.Checkbox,
                onValueChange = onCheckedChange,
            )
            .padding(vertical = theme.spacing.half),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(checked = checked, onCheckedChange = null)
        Text(
            text = label,
            style = theme.typography.body,
            modifier = Modifier.padding(start = theme.spacing.one),
        )
    }
}

private fun <T> Set<T>.toggle(value: T, enabled: Boolean): Set<T> = if (enabled) this + value else this - value

private val LibraryScope.labelResource: Int
    get() = when (this) {
        LibraryScope.Books -> R.string.library_scope_works
        LibraryScope.Series -> R.string.library_scope_series
        LibraryScope.Authors -> R.string.library_scope_authors
    }

private val LibraryScope.searchPlaceholderResource: Int
    get() = when (this) {
        LibraryScope.Books -> R.string.library_search_works_placeholder
        LibraryScope.Series -> R.string.library_search_series_placeholder
        LibraryScope.Authors -> R.string.library_search_authors_placeholder
    }

private val LibraryScope.resultCountResource: Int
    get() = when (this) {
        LibraryScope.Books -> R.plurals.library_result_count_works
        LibraryScope.Series -> R.plurals.library_result_count_series
        LibraryScope.Authors -> R.plurals.library_result_count_authors
    }

private val ContentSort.labelResource: Int
    get() = when (this) {
        ContentSort.RecentAdded -> R.string.library_sort_recent_added
        ContentSort.RecentReading -> R.string.library_sort_recent_reading
        ContentSort.Title -> R.string.library_sort_title
        ContentSort.Author -> R.string.library_sort_author
    }

private val ContentViewMode.labelResource: Int
    get() = if (this == ContentViewMode.Grid) R.string.library_view_grid else R.string.library_view_list

private val MediaFilter.labelResource: Int
    get() = when (this) {
        MediaFilter.Ebook -> R.string.media_ebook
        MediaFilter.Comic -> R.string.media_comic
        MediaFilter.Audiobook -> R.string.media_audiobook
    }

private val ReadingFilter.labelResource: Int
    get() = when (this) {
        ReadingFilter.Unread -> R.string.reading_unread
        ReadingFilter.Reading -> R.string.reading_reading
        ReadingFilter.Finished -> R.string.reading_finished
    }
