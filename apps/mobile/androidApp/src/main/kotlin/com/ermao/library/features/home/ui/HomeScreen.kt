package com.ermao.library.features.home.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.ContinueReadingCard
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.ui.CoverRole
import com.ermao.library.features.content.ui.ReadingProgress
import com.ermao.library.features.content.ui.WorkCover
import com.ermao.library.features.content.ui.WorkGridItem
import com.ermao.library.features.home.application.HomeUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.components.WarmPageContentMessage
import com.ermao.library.ui.components.WarmPageContentMessageKind
import com.ermao.library.ui.components.WarmPagePrimaryAction
import com.ermao.library.ui.components.WarmPageSectionHeader
import com.ermao.library.ui.components.WarmPageStatusBanner
import com.ermao.library.ui.components.WarmPageStatusBannerKind
import com.ermao.library.ui.theme.WarmPageThemeValues

private val ContinueCoverWidth = 104.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    state: HomeUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenWork: (String) -> Unit,
    onOpenLibrary: () -> Unit,
    onRetry: () -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Scaffold(
        modifier = modifier.testTag("tab-home"),
        containerColor = theme.colors.canvas,
        topBar = {
            LargeTopAppBar(
                title = { Text(stringResource(R.string.tab_home)) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = theme.colors.canvas,
                    scrolledContainerColor = theme.colors.surface,
                ),
            )
        },
    ) { padding ->
        when {
            state.isLoading -> WarmPageContentMessage(
                kind = WarmPageContentMessageKind.Loading,
                title = stringResource(R.string.content_loading_title),
                message = stringResource(R.string.home_loading_message),
                modifier = Modifier.padding(padding),
            )
            state.content == null -> WarmPageContentMessage(
                kind = WarmPageContentMessageKind.Error,
                title = stringResource(R.string.content_error_title),
                message = stringResource(R.string.content_error_message),
                actionLabel = stringResource(R.string.retry_action),
                onAction = onRetry,
                modifier = Modifier.padding(padding),
            )
            else -> {
                val content = state.content
                PullToRefreshBox(
                    isRefreshing = state.isRefreshing,
                    onRefresh = onRefresh,
                    modifier = Modifier.fillMaxSize().padding(padding),
                ) {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(
                            start = theme.spacing.two,
                            end = theme.spacing.two,
                            bottom = theme.spacing.six,
                        ),
                        verticalArrangement = Arrangement.spacedBy(theme.spacing.three),
                    ) {
                        if (state.freshness != ContentFreshness.Fresh) {
                            item {
                                WarmPageStatusBanner(
                                    kind = if (state.freshness == ContentFreshness.Cached) {
                                        WarmPageStatusBannerKind.Offline
                                    } else {
                                        WarmPageStatusBannerKind.Stale
                                    },
                                    message = stringResource(
                                        if (state.freshness == ContentFreshness.Cached) {
                                            R.string.content_cached_banner
                                        } else {
                                            R.string.content_stale_banner
                                        },
                                    ),
                                )
                            }
                        }
                        content.continueReading?.let { continueReading ->
                            item {
                                ContinueReadingTask(
                                    item = continueReading,
                                    repository = repository,
                                    context = context,
                                    onOpenWork = onOpenWork,
                                )
                            }
                        }
                        if (
                            content.continueReading == null &&
                            content.recentReading.isEmpty() &&
                            content.recentAdded.isEmpty()
                        ) {
                            item {
                                WarmPageContentMessage(
                                    kind = WarmPageContentMessageKind.Empty,
                                    title = stringResource(R.string.home_empty_title),
                                    message = stringResource(R.string.home_empty_message),
                                    actionLabel = stringResource(R.string.home_browse_library),
                                    onAction = onOpenLibrary,
                                )
                            }
                        } else {
                            if (content.recentReading.isNotEmpty()) {
                                item {
                                    HomeShelf(
                                        title = stringResource(R.string.home_recent_reading),
                                        works = content.recentReading,
                                        repository = repository,
                                        context = context,
                                        onOpenWork = onOpenWork,
                                    )
                                }
                            }
                            if (content.recentAdded.isNotEmpty()) {
                                item {
                                    HomeShelf(
                                        title = stringResource(R.string.home_recent_added),
                                        works = content.recentAdded,
                                        repository = repository,
                                        context = context,
                                        onOpenWork = onOpenWork,
                                    )
                                }
                            }
                        }
                        state.errorCode?.let {
                            item {
                                WarmPageContentMessage(
                                    kind = WarmPageContentMessageKind.Error,
                                    title = stringResource(R.string.home_partial_error_title),
                                    message = stringResource(R.string.home_partial_error_message),
                                    actionLabel = stringResource(R.string.retry_action),
                                    onAction = onRetry,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ContinueReadingTask(
    item: ContinueReadingCard,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenWork: (String) -> Unit,
) {
    val theme = WarmPageThemeValues
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
        WarmPageSectionHeader(title = stringResource(R.string.home_continue_title))
        Surface(
            color = theme.colors.surface,
            shape = RoundedCornerShape(theme.radii.task),
            border = BorderStroke(Dp.Hairline, theme.colors.divider),
            modifier = Modifier.fillMaxWidth().testTag("home-continue"),
        ) {
            Column(
                modifier = Modifier.padding(theme.spacing.oneAndHalf),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onOpenWork(item.work.id) },
                    horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    WorkCover(
                        work = item.work,
                        repository = repository,
                        context = context,
                        role = CoverRole.Compact,
                        modifier = Modifier.width(ContinueCoverWidth),
                    )
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
                    ) {
                        Text(
                            text = item.work.title,
                            style = theme.typography.sectionTitle,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            text = item.work.author,
                            style = theme.typography.callout,
                            color = theme.colors.textSecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        (item.positionLabel ?: item.volumeTitle)?.let { position ->
                            Text(
                                text = position,
                                style = theme.typography.label,
                                color = theme.colors.textSecondary,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        item.work.progressPercent?.let { progress ->
                            Text(
                                text = stringResource(R.string.progress_percent, progress),
                                style = theme.typography.caption,
                                color = theme.colors.textSecondary,
                            )
                            ReadingProgress(
                                progressPercent = progress,
                                stateDescription = stringResource(R.string.progress_percent, progress),
                            )
                        }
                        item.lastReadLabel?.let { lastRead ->
                            Text(
                                text = lastRead,
                                style = theme.typography.caption,
                                color = theme.colors.textTertiary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
                WarmPagePrimaryAction(
                    label = stringResource(R.string.home_view_detail_action),
                    onClick = { onOpenWork(item.work.id) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@Composable
private fun HomeShelf(
    title: String,
    works: List<WorkCard>,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenWork: (String) -> Unit,
) {
    val theme = WarmPageThemeValues
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
        WarmPageSectionHeader(title = title)
        BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
            val itemWidth = (maxWidth - (theme.spacing.two * 2)) / 3
            LazyRow(horizontalArrangement = Arrangement.spacedBy(theme.spacing.two)) {
                items(works, key = WorkCard::id) { work ->
                    WorkGridItem(
                        work = work,
                        repository = repository,
                        context = context,
                        modifier = Modifier
                            .width(itemWidth)
                            .clickable { onOpenWork(work.id) },
                    )
                }
            }
        }
    }
}
