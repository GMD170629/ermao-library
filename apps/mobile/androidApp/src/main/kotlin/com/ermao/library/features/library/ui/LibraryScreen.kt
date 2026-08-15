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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.Sort
import androidx.compose.material.icons.automirrored.outlined.ViewList
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.outlined.FilterList
import androidx.compose.material.icons.outlined.GridView
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.InputChip
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.zIndex
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.ui.CoverSize
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.ContentSort
import com.ermao.library.features.content.model.ContentViewMode
import com.ermao.library.features.content.model.GroupingCard
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.MediaFilter
import com.ermao.library.features.content.model.ReadingFilter
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.model.WorksFilters
import com.ermao.library.features.content.ui.ContentAreaMessage
import com.ermao.library.features.content.ui.ContentStatusBanner
import com.ermao.library.features.content.ui.WorkCover
import com.ermao.library.features.content.ui.WorkGridItem
import com.ermao.library.features.content.ui.WorkListItem
import com.ermao.library.features.content.ui.responsiveCoverColumnCount
import com.ermao.library.features.library.application.LibraryUiState
import com.ermao.library.features.library.application.ScrollAnchor
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.OfflineFilterAvailability
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.flow.distinctUntilChanged

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
    var overflowOpen by rememberSaveable { mutableStateOf(false) }
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
    Scaffold(
        modifier = modifier.testTag("tab-library"),
        containerColor = theme.colors.canvas,
        topBar = {
            LargeTopAppBar(
                title = { Text(stringResource(R.string.tab_library)) },
                actions = {
                    if (state.selectedScope == LibraryScope.Works) {
                        Box {
                            IconButton(onClick = { overflowOpen = true }) {
                                Icon(Icons.Outlined.MoreVert, contentDescription = stringResource(R.string.library_more_actions))
                            }
                            LibraryOverflowMenu(
                                expanded = overflowOpen,
                                state = state,
                                onDismiss = { overflowOpen = false },
                                onSelectSort = { overflowOpen = false; onSelectSort(it) },
                                onSelectViewMode = { overflowOpen = false; onSelectViewMode(it) },
                            )
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = theme.colors.canvas,
                    scrolledContainerColor = theme.colors.surface,
                ),
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            OutlinedTextField(
                value = state.current.query,
                onValueChange = onQueryChanged,
                modifier = Modifier.fillMaxWidth().padding(horizontal = theme.spacing.two).testTag("library-search"),
                label = { Text(stringResource(R.string.library_search_label)) },
                leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null) },
                trailingIcon = if (state.current.query.isNotEmpty()) {
                    { TextButton(onClick = onClearQuery) { Text(stringResource(R.string.clear_action)) } }
                } else null,
                singleLine = true,
            )
            SingleChoiceSegmentedButtonRow(
                modifier = Modifier.fillMaxWidth().padding(horizontal = theme.spacing.two, vertical = theme.spacing.two),
            ) {
                LibraryScope.entries.forEachIndexed { index, scope ->
                    SegmentedButton(
                        selected = state.selectedScope == scope,
                        onClick = { onSelectScope(scope) },
                        shape = SegmentedButtonDefaults.itemShape(index, LibraryScope.entries.size),
                        label = { Text(stringResource(scope.labelResource)) },
                        icon = {},
                    )
                }
            }
            LibraryContextRow(
                state,
                onOpenFilter,
                onRemoveMediaFilter,
                onRemoveReadingFilter,
                filterFocusRequester,
            )
            if (state.current.freshness != ContentFreshness.Fresh) {
                ContentStatusBanner(
                    state.current.freshness,
                    Modifier.padding(horizontal = theme.spacing.two, vertical = theme.spacing.one),
                )
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
            onChange = onUpdateFilterDraft,
            offlineAvailability = state.offlineFilterAvailability,
            onClear = onClearFilters,
            onApply = onApplyFilter,
            onDismiss = onDismissFilter,
        )
    }
}

@Composable
private fun LibraryContextRow(
    state: LibraryUiState,
    onOpenFilter: () -> Unit,
    onRemoveMediaFilter: (MediaFilter) -> Unit,
    onRemoveReadingFilter: (ReadingFilter) -> Unit,
    filterFocusRequester: FocusRequester,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = theme.spacing.two, vertical = theme.spacing.one),
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
            if (state.selectedScope == LibraryScope.Works) {
                TextButton(
                    onClick = onOpenFilter,
                    modifier = Modifier.focusRequester(filterFocusRequester).testTag("library-filter"),
                ) {
                    Icon(Icons.Outlined.FilterList, contentDescription = null)
                    Text(
                        if (state.current.filters.count == 0) stringResource(R.string.library_filter_action)
                        else stringResource(R.string.library_filter_count, state.current.filters.count),
                        modifier = Modifier.padding(start = theme.spacing.one),
                    )
                }
            }
        }
        if (state.selectedScope == LibraryScope.Works && state.current.filters.count > 0) {
            LazyRow(
                contentPadding = PaddingValues(horizontal = theme.spacing.two),
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
    InputChip(
        selected = true,
        onClick = onRemove,
        label = { Text(label) },
        trailingIcon = {
            Icon(
                imageVector = Icons.Default.Close,
                contentDescription = stringResource(R.string.library_remove_filter),
            )
        },
        modifier = Modifier.heightIn(min = WarmPageThemeValues.metrics.androidMinimumTouchTarget),
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
        current.isLoading -> ContentAreaMessage(
            stringResource(R.string.content_loading_title),
            stringResource(R.string.library_loading_message),
            loading = true,
        )
        current.errorCode != null && current.works.isEmpty() && current.groups.isEmpty() -> when (current.errorCode) {
            "PERMISSION_REVALIDATING" -> ContentAreaMessage(
                stringResource(R.string.library_permission_revalidating_title),
                stringResource(R.string.library_permission_revalidating_message),
                loading = true,
            )
            "CONTENT_NOT_ACCESSIBLE" -> ContentAreaMessage(
                stringResource(R.string.work_unavailable_title),
                stringResource(R.string.work_unavailable_message),
            )
            else -> ContentAreaMessage(
                stringResource(R.string.content_error_title),
                stringResource(R.string.content_error_message),
                actionLabel = stringResource(R.string.retry_action),
                onAction = onRetry,
            )
        }
        current.works.isEmpty() && current.groups.isEmpty() -> ContentAreaMessage(
            title = stringResource(
                when (state.selectedScope) {
                    LibraryScope.Works -> R.string.library_empty_works_title
                    LibraryScope.Series -> R.string.library_empty_series_title
                    LibraryScope.Authors -> R.string.library_empty_authors_title
                },
            ),
            message = stringResource(R.string.library_empty_message),
            actionLabel = stringResource(R.string.clear_search_action).takeIf { current.query.isNotBlank() },
            onAction = onClearQuery.takeIf { current.query.isNotBlank() },
        )
        state.selectedScope == LibraryScope.Works -> WorksResults(
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
    works: List<WorkCard>,
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
        LazyColumn(state = listState, contentPadding = PaddingValues(bottom = 96.dp)) {
            items(works, key = WorkCard::id) { work ->
                WorkListItem(
                    work = work,
                    repository = repository,
                    context = context,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onOpenWork(work.id) }
                        .padding(horizontal = WarmPageThemeValues.spacing.two, vertical = WarmPageThemeValues.spacing.two),
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
                contentPadding = PaddingValues(
                    start = WarmPageThemeValues.spacing.two,
                    end = WarmPageThemeValues.spacing.two,
                    bottom = 96.dp,
                ),
                horizontalArrangement = Arrangement.spacedBy(WarmPageThemeValues.spacing.two),
                verticalArrangement = Arrangement.spacedBy(WarmPageThemeValues.spacing.three),
            ) {
                items(works, key = WorkCard::id) { work ->
                    WorkGridItem(
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
        contentPadding = PaddingValues(horizontal = WarmPageThemeValues.spacing.two, vertical = WarmPageThemeValues.spacing.one),
    ) {
        items(groups, key = GroupingCard::id) { group ->
            GroupingRow(group, scope, repository, context, Modifier.clickable { onOpenFacet(scope, group.id) })
            HorizontalDivider()
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
        modifier.fillMaxWidth().padding(vertical = theme.spacing.two),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
    ) {
        GroupingCoverStack(group.representativeWorks, repository, context)
        Column(Modifier.weight(1f)) {
            Text(group.name, style = theme.typography.headline, maxLines = 2, overflow = TextOverflow.Ellipsis)
            val representativeAuthor = group.representativeWorks.firstOrNull()?.author?.trim().orEmpty()
            val summary = if (scope == LibraryScope.Series && representativeAuthor.isNotEmpty()) {
                pluralStringResource(
                    R.plurals.library_group_summary,
                    group.workCount,
                    representativeAuthor,
                    group.workCount,
                )
            } else {
                pluralStringResource(R.plurals.library_group_work_count, group.workCount, group.workCount)
            }
            Text(summary, style = theme.typography.callout, color = theme.colors.textSecondary, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = theme.colors.textTertiary)
    }
}

@Composable
private fun GroupingCoverStack(
    works: List<WorkCard>,
    repository: ContentRepository,
    context: ContentRequestContext,
) {
    Box(modifier = Modifier.size(width = 104.dp, height = 78.dp)) {
        works.take(3).forEachIndexed { index, work ->
            WorkCover(
                work,
                repository,
                context,
                CoverSize.Small,
                Modifier
                    .size(width = 52.dp, height = 78.dp)
                    .offset(x = (index * 24).dp)
                    .zIndex((3 - index).toFloat()),
            )
        }
    }
}

@Composable
private fun ObserveListState(
    state: LazyListState,
    works: List<WorkCard>,
    onScrollAnchorChanged: (String?, Int) -> Unit,
    onLoadNextPage: () -> Unit,
) = ObserveListState(state, works, onScrollAnchorChanged, onLoadNextPage, WorkCard::id)

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
    works: List<WorkCard>,
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
    ContentAreaMessage(
        title = stringResource(if (loading) R.string.library_loading_more else R.string.library_pagination_error_title),
        message = stringResource(if (loading) R.string.library_loading_more_message else R.string.library_pagination_error_message),
        actionLabel = stringResource(R.string.retry_action).takeIf { error != null },
        onAction = onRetry.takeIf { error != null },
        loading = loading,
        modifier = Modifier.testTag("library-pagination"),
    )
}

@Composable
private fun LibraryOverflowMenu(
    expanded: Boolean,
    state: LibraryUiState,
    onDismiss: () -> Unit,
    onSelectSort: (ContentSort) -> Unit,
    onSelectViewMode: (ContentViewMode) -> Unit,
) {
    DropdownMenu(expanded = expanded, onDismissRequest = onDismiss) {
        Text(stringResource(R.string.library_sort_heading), modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp))
        ContentSort.entries.forEach { sort ->
            DropdownMenuItem(
                text = { Text(stringResource(sort.labelResource)) },
                onClick = { onSelectSort(sort) },
                leadingIcon = { Icon(if (state.current.sort == sort) Icons.Filled.Check else Icons.AutoMirrored.Outlined.Sort, contentDescription = null) },
            )
        }
        HorizontalDivider()
        ContentViewMode.entries.forEach { mode ->
            DropdownMenuItem(
                text = { Text(stringResource(mode.labelResource)) },
                onClick = { onSelectViewMode(mode) },
                leadingIcon = {
                    Icon(
                        if (state.current.viewMode == mode) Icons.Filled.Check else if (mode == ContentViewMode.Grid) Icons.Outlined.GridView else Icons.AutoMirrored.Outlined.ViewList,
                        contentDescription = null,
                    )
                },
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FilterSheet(
    filters: WorksFilters,
    onChange: (WorksFilters) -> Unit,
    offlineAvailability: OfflineFilterAvailability,
    onClear: () -> Unit,
    onApply: () -> Unit,
    onDismiss: () -> Unit,
) {
    val theme = WarmPageThemeValues
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = theme.spacing.three, vertical = theme.spacing.two),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
        ) {
            Text(stringResource(R.string.library_filter_title), style = theme.typography.title)
            Text(stringResource(R.string.library_filter_media), style = theme.typography.headline, modifier = Modifier.padding(top = theme.spacing.two))
            MediaFilter.entries.forEach { value ->
                FilterRow(stringResource(value.labelResource), value in filters.media) { checked ->
                    onChange(filters.copy(media = filters.media.toggle(value, checked)))
                }
            }
            Text(stringResource(R.string.library_filter_reading), style = theme.typography.headline, modifier = Modifier.padding(top = theme.spacing.two))
            ReadingFilter.entries.forEach { value ->
                FilterRow(stringResource(value.labelResource), value in filters.reading) { checked ->
                    onChange(filters.copy(reading = filters.reading.toggle(value, checked)))
                }
            }
            if (offlineAvailability is OfflineFilterAvailability.Available) {
                Text(stringResource(R.string.library_filter_offline), style = theme.typography.headline, modifier = Modifier.padding(top = theme.spacing.two))
                FilterRow(
                    stringResource(R.string.library_filter_downloaded),
                    filters.downloadedOnly,
                ) { checked -> onChange(filters.copy(downloadedOnly = checked)) }
            }
            Row(
                modifier = Modifier.fillMaxWidth().padding(vertical = theme.spacing.three),
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
            ) {
                TextButton(onClick = onDismiss, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.cancel_action)) }
                OutlinedButton(onClick = onClear, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.clear_all_action)) }
                Button(onClick = onApply, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.apply_action)) }
            }
        }
    }
}

@Composable
private fun FilterRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    val theme = WarmPageThemeValues
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = theme.metrics.androidMinimumTouchTarget)
            .clickable { onCheckedChange(!checked) }
            .padding(vertical = theme.spacing.half),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(checked = checked, onCheckedChange = onCheckedChange)
        Text(label, modifier = Modifier.padding(start = theme.spacing.one))
    }
}

private fun <T> Set<T>.toggle(value: T, enabled: Boolean): Set<T> = if (enabled) this + value else this - value

private val LibraryScope.labelResource: Int
    get() = when (this) {
        LibraryScope.Works -> R.string.library_scope_works
        LibraryScope.Series -> R.string.library_scope_series
        LibraryScope.Authors -> R.string.library_scope_authors
    }

private val LibraryScope.resultCountResource: Int
    get() = when (this) {
        LibraryScope.Works -> R.plurals.library_result_count_works
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
