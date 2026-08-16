package com.ermao.library.features.library.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ermao.library.R
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.ui.WorkGridItem
import com.ermao.library.features.content.ui.WorkListItem
import com.ermao.library.features.content.ui.responsiveCoverColumnCount
import com.ermao.library.features.library.application.FacetUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.components.WarmPageEmptyState
import com.ermao.library.ui.components.WarmPageErrorState
import com.ermao.library.ui.components.WarmPageLoadingState
import com.ermao.library.ui.components.WarmPageNavigationAction
import com.ermao.library.ui.components.WarmPagePaginationError
import com.ermao.library.ui.components.WarmPagePaginationLoading
import com.ermao.library.ui.components.WarmPageScaffold
import com.ermao.library.ui.components.WarmPageStaleStatus
import com.ermao.library.ui.components.WarmPageTextAction
import com.ermao.library.ui.components.WarmPageTopBarRole
import com.ermao.library.ui.theme.WarmPageThemeValues

@Composable
fun FacetScreen(
    kind: LibraryScope,
    state: FacetUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onBack: () -> Unit,
    onOpenWork: (String) -> Unit,
    onRetry: () -> Unit,
    onLoadNextPage: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    WarmPageScaffold(
        role = WarmPageTopBarRole.Detail,
        title = stringResource(if (kind == LibraryScope.Series) R.string.facet_series_title else R.string.facet_author_title),
        modifier = modifier.testTag("facet-screen"),
        navigation = WarmPageNavigationAction(
            icon = Icons.AutoMirrored.Filled.ArrowBack,
            label = stringResource(R.string.navigate_back),
            onClick = onBack,
        ),
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = theme.components.page.compactGutter,
                        vertical = theme.spacing.two,
                    ),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
            ) {
                Text(
                    state.facetName ?: stringResource(if (kind == LibraryScope.Series) R.string.facet_series_title else R.string.facet_author_title),
                    style = theme.typography.display,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    pluralStringResource(R.plurals.library_result_count, state.total, state.total),
                    style = theme.typography.callout,
                    color = theme.colors.textSecondary,
                )
                Text(
                    text = stringResource(
                        if (kind == LibraryScope.Series) {
                            R.string.facet_series_sort_summary
                        } else {
                            R.string.facet_author_sort_summary
                        },
                    ),
                    style = theme.typography.caption,
                    color = theme.colors.textSecondary,
                )
            }
            when (state.freshness) {
                ContentFreshness.Stale -> WarmPageStaleStatus(
                    message = stringResource(R.string.content_stale_banner),
                    modifier = Modifier.padding(horizontal = theme.components.page.compactGutter),
                )
                ContentFreshness.Fresh -> Unit
            }
            when {
                state.isLoading -> WarmPageLoadingState(
                    title = stringResource(R.string.content_loading_title),
                    message = stringResource(R.string.facet_loading_message),
                )
                state.errorCode != null && state.works.isEmpty() -> if (state.errorCode == "CONTENT_NOT_ACCESSIBLE") {
                    WarmPageErrorState(
                        title = stringResource(R.string.work_unavailable_title),
                        message = stringResource(R.string.work_unavailable_message),
                    )
                } else {
                    WarmPageErrorState(
                        title = stringResource(R.string.content_error_title),
                        message = stringResource(R.string.content_error_message),
                        retryLabel = stringResource(R.string.retry_action),
                        onRetry = onRetry,
                    )
                }
                state.works.isEmpty() -> WarmPageEmptyState(
                    title = stringResource(R.string.facet_empty_title),
                    message = stringResource(R.string.facet_empty_message),
                )
                kind == LibraryScope.Series -> LazyColumn(
                    contentPadding = PaddingValues(
                        horizontal = theme.components.page.compactGutter,
                        vertical = theme.spacing.one,
                    ),
                ) {
                    items(state.works, key = WorkCard::id) { work ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { onOpenWork(work.id) }
                                .heightIn(min = theme.components.controls.minimumTouchTarget)
                                .padding(vertical = theme.spacing.one),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            WorkListItem(
                                work = work,
                                repository = repository,
                                context = context,
                                modifier = Modifier.weight(1f),
                            )
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                                contentDescription = null,
                                tint = theme.colors.textTertiary,
                            )
                        }
                        HorizontalDivider(
                            thickness = theme.components.dividerThickness,
                            color = theme.colors.divider,
                        )
                    }
                    item { FacetPagination(state, onLoadNextPage) }
                }
                else -> BoxWithConstraints {
                    val columns = responsiveCoverColumnCount(maxWidth, LocalDensity.current.fontScale)
                    LazyVerticalGrid(
                        columns = GridCells.Fixed(columns),
                        contentPadding = PaddingValues(
                            horizontal = theme.components.page.compactGutter,
                            vertical = theme.spacing.one,
                        ),
                        horizontalArrangement = Arrangement.spacedBy(theme.components.grid.horizontalGap),
                        verticalArrangement = Arrangement.spacedBy(theme.components.grid.verticalGap),
                    ) {
                        items(state.works, key = WorkCard::id) { work ->
                            WorkGridItem(work, repository, context, Modifier.clickable { onOpenWork(work.id) })
                        }
                        item(span = { androidx.compose.foundation.lazy.grid.GridItemSpan(maxLineSpan) }) {
                            FacetPagination(state, onLoadNextPage)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FacetPagination(state: FacetUiState, onLoadNextPage: () -> Unit) {
    when {
        state.isLoadingMore -> WarmPagePaginationLoading(
            message = stringResource(R.string.library_loading_more),
        )
        state.paginationErrorCode != null -> WarmPagePaginationError(
            message = stringResource(R.string.library_pagination_error_title),
            retryLabel = stringResource(R.string.retry_action),
            onRetry = onLoadNextPage,
        )
        state.page < state.totalPages -> WarmPageTextAction(
            label = stringResource(R.string.load_more_action),
            onClick = onLoadNextPage,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}
