package com.ermao.library.features.library.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.ui.CoverSize
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.ui.ContentAreaMessage
import com.ermao.library.features.content.ui.ContentStatusBanner
import com.ermao.library.features.content.ui.WorkGridItem
import com.ermao.library.features.library.application.FacetUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.theme.WarmPageThemeValues

@OptIn(ExperimentalMaterial3Api::class)
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
    Scaffold(
        modifier = modifier.testTag("facet-screen"),
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(if (kind == LibraryScope.Series) R.string.facet_series_title else R.string.facet_author_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.navigate_back))
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = theme.colors.canvas),
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            Column(Modifier.fillMaxWidth().padding(horizontal = theme.spacing.three, vertical = theme.spacing.two)) {
                Text(
                    state.facetName ?: stringResource(if (kind == LibraryScope.Series) R.string.facet_series_title else R.string.facet_author_title),
                    style = theme.typography.title,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    pluralStringResource(R.plurals.library_result_count, state.total, state.total),
                    style = theme.typography.callout,
                    color = theme.colors.textSecondary,
                )
            }
            if (state.freshness != com.ermao.library.features.content.model.ContentFreshness.Fresh) {
                ContentStatusBanner(state.freshness, Modifier.padding(horizontal = theme.spacing.three))
            }
            when {
                state.isLoading -> ContentAreaMessage(
                    stringResource(R.string.content_loading_title),
                    stringResource(R.string.facet_loading_message),
                    loading = true,
                )
                state.errorCode != null && state.works.isEmpty() -> ContentAreaMessage(
                    stringResource(R.string.content_error_title),
                    stringResource(R.string.content_error_message),
                    actionLabel = stringResource(R.string.retry_action),
                    onAction = onRetry,
                )
                state.works.isEmpty() -> ContentAreaMessage(
                    stringResource(R.string.facet_empty_title),
                    stringResource(R.string.facet_empty_message),
                )
                kind == LibraryScope.Series -> LazyColumn(
                    contentPadding = PaddingValues(horizontal = theme.spacing.three, vertical = theme.spacing.one),
                ) {
                    items(state.works, key = WorkCard::id) { work ->
                        WorkListRowForFacet(work, repository, context, Modifier.clickable { onOpenWork(work.id) })
                        HorizontalDivider()
                    }
                    item { FacetPagination(state, onLoadNextPage) }
                }
                else -> BoxWithConstraints {
                    val columns = if (maxWidth >= 360.dp && LocalDensity.current.fontScale <= 1.15f) 3 else 2
                    LazyVerticalGrid(
                        columns = GridCells.Fixed(columns),
                        contentPadding = PaddingValues(horizontal = theme.spacing.three, vertical = theme.spacing.one),
                        horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
                        verticalArrangement = Arrangement.spacedBy(theme.spacing.three),
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
private fun WorkListRowForFacet(
    work: WorkCard,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    androidx.compose.foundation.layout.Row(
        modifier.fillMaxWidth().padding(vertical = theme.spacing.two),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
    ) {
        com.ermao.library.features.content.ui.WorkCover(
            work,
            repository,
            context,
            CoverSize.Small,
            Modifier.fillMaxWidth(0.2f),
        )
        Column(Modifier.weight(1f)) {
            Text(work.title, style = theme.typography.headline, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(work.author, style = theme.typography.callout, color = theme.colors.textSecondary)
            work.progressPercent?.let { Text(stringResource(R.string.progress_percent, it), style = theme.typography.caption) }
        }
    }
}

@Composable
private fun FacetPagination(state: FacetUiState, onLoadNextPage: () -> Unit) {
    when {
        state.isLoadingMore -> ContentAreaMessage(
            stringResource(R.string.library_loading_more),
            stringResource(R.string.library_loading_more_message),
            loading = true,
        )
        state.paginationErrorCode != null -> ContentAreaMessage(
            stringResource(R.string.library_pagination_error_title),
            stringResource(R.string.library_pagination_error_message),
            actionLabel = stringResource(R.string.retry_action),
            onAction = onLoadNextPage,
        )
        state.page < state.totalPages -> androidx.compose.material3.TextButton(
            onClick = onLoadNextPage,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(stringResource(R.string.load_more_action)) }
    }
}
