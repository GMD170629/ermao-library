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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ermao.library.R
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.ContinueReadingCard
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.ui.CoverRole
import com.ermao.library.features.content.ui.ReadingProgressTrack
import com.ermao.library.features.content.ui.WorkCover
import com.ermao.library.features.content.ui.WorkGridItem
import com.ermao.library.features.home.application.HomeUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.components.WarmPageEmptyState
import com.ermao.library.ui.components.WarmPageErrorState
import com.ermao.library.ui.components.WarmPageLoadingState
import com.ermao.library.ui.components.WarmPagePrimaryAction
import com.ermao.library.ui.components.WarmPageScaffold
import com.ermao.library.ui.components.WarmPageSectionHeader
import com.ermao.library.ui.components.WarmPageStaleStatus
import com.ermao.library.ui.components.WarmPageTopBarRole
import com.ermao.library.ui.theme.WarmPageThemeValues
import java.text.NumberFormat
import java.time.Clock
import java.time.ZoneId
import java.util.Date
import java.util.TimeZone

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    state: HomeUiState,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenWork: (String) -> Unit,
    onContinueReading: (ContinueReadingCard) -> Unit,
    onOpenLibrary: () -> Unit,
    onRetry: () -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    lastReadClock: Clock = Clock.systemDefaultZone(),
) {
    val theme = WarmPageThemeValues
    WarmPageScaffold(
        role = WarmPageTopBarRole.Root,
        title = stringResource(R.string.tab_home),
        modifier = modifier.testTag("tab-home"),
    ) { padding ->
        when {
            state.isLoading -> WarmPageLoadingState(
                title = stringResource(R.string.content_loading_title),
                message = stringResource(R.string.home_loading_message),
                modifier = Modifier.padding(padding),
            )
            state.content == null -> WarmPageErrorState(
                title = stringResource(R.string.content_error_title),
                message = stringResource(R.string.content_error_message),
                retryLabel = stringResource(R.string.retry_action),
                onRetry = onRetry,
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
                            start = theme.components.page.compactGutter,
                            end = theme.components.page.compactGutter,
                            bottom = theme.components.page.contentBottomInset,
                        ),
                        verticalArrangement = Arrangement.spacedBy(theme.components.page.sectionGap),
                    ) {
                        if (state.freshness == ContentFreshness.Stale) {
                            item {
                                WarmPageStaleStatus(
                                    message = stringResource(R.string.content_stale_banner),
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
                                    onContinueReading = onContinueReading,
                                    lastReadClock = lastReadClock,
                                )
                            }
                        }
                        if (
                            content.continueReading == null &&
                            content.recentReading.isEmpty() &&
                            content.recentAdded.isEmpty()
                        ) {
                            item {
                                WarmPageEmptyState(
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
                                        listTag = "home-recent-reading-list",
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
                                        listTag = "home-recent-added-list",
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
                                WarmPageErrorState(
                                    title = stringResource(R.string.home_partial_error_title),
                                    message = stringResource(R.string.home_partial_error_message),
                                    retryLabel = stringResource(R.string.retry_action),
                                    onRetry = onRetry,
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
    onContinueReading: (ContinueReadingCard) -> Unit,
    lastReadClock: Clock,
) {
    val theme = WarmPageThemeValues
    val locale = LocalConfiguration.current.locales[0]
    val positionLabel = selectContinuePositionLabel(
        workTitle = item.work.title,
        positionLabel = item.positionLabel,
        volumeTitle = item.volumeTitle,
    )
    val lastReadLabel = homeLastReadPresentation(
        lastReadAtEpochMillis = item.lastReadAtEpochMillis,
        now = lastReadClock.instant(),
        zoneId = lastReadClock.zone,
    )?.localizedLabel(lastReadClock.zone)
    val progress = item.work.progressPercent?.coerceIn(0, 100)
    val progressLabel = progress?.let {
        NumberFormat.getPercentInstance(locale).apply {
            maximumFractionDigits = 0
        }.format(it / 100.0)
    }
    val progressAndTimeLabel = when {
        progressLabel != null && lastReadLabel != null -> stringResource(
            R.string.home_progress_last_read,
            progressLabel,
            lastReadLabel,
        )
        progressLabel != null -> progressLabel
        else -> lastReadLabel
    }
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
        WarmPageSectionHeader(title = stringResource(R.string.home_continue_title))
        Surface(
            color = theme.colors.surface,
            shape = RoundedCornerShape(theme.radii.task),
            border = BorderStroke(theme.components.dividerThickness, theme.colors.divider),
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
                        modifier = Modifier.width(theme.components.covers.continueWidth),
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
                        positionLabel?.let { position ->
                            Text(
                                text = position,
                                style = theme.typography.label,
                                color = theme.colors.textSecondary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.testTag("home-continue-position"),
                            )
                        }
                        progressAndTimeLabel?.let { summary ->
                            Text(
                                text = summary,
                                style = theme.typography.caption,
                                color = theme.colors.textTertiary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.testTag("home-continue-progress-summary"),
                            )
                        }
                        progress?.let {
                            ReadingProgressTrack(
                                progressPercent = it,
                                stateDescription = stringResource(R.string.progress_percent, it),
                            )
                        }
                    }
                }
                WarmPagePrimaryAction(
                    label = stringResource(R.string.home_view_detail_action),
                    onClick = { onContinueReading(item) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("home-continue-action"),
                )
            }
        }
    }
}

@Composable
private fun HomeLastReadPresentation.localizedLabel(zoneId: ZoneId): String {
    val context = LocalContext.current
    val timeZone = TimeZone.getTimeZone(zoneId)
    val date = Date.from(instant)
    val timeLabel = android.text.format.DateFormat.getTimeFormat(context).apply {
        this.timeZone = timeZone
    }.format(date)
    return when (this) {
        is HomeLastReadPresentation.Today -> stringResource(R.string.home_last_read_today, timeLabel)
        is HomeLastReadPresentation.Yesterday -> stringResource(R.string.home_last_read_yesterday, timeLabel)
        is HomeLastReadPresentation.Absolute -> {
            val dateLabel = android.text.format.DateFormat.getDateFormat(context).apply {
                this.timeZone = timeZone
            }.format(date)
            stringResource(R.string.home_last_read_absolute, dateLabel, timeLabel)
        }
    }
}

@Composable
private fun HomeShelf(
    title: String,
    listTag: String,
    works: List<WorkCard>,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenWork: (String) -> Unit,
) {
    val theme = WarmPageThemeValues
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf)) {
        WarmPageSectionHeader(title = title)
        BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
            val columns = homeShelfColumnCount(
                compactColumns = theme.components.grid.compactColumns,
                fontScale = LocalDensity.current.fontScale,
            )
            val totalGap = theme.components.grid.horizontalGap * (columns - 1)
            val itemWidth = (maxWidth - totalGap) / columns
            LazyRow(
                modifier = Modifier.testTag(listTag),
                horizontalArrangement = Arrangement.spacedBy(theme.components.grid.horizontalGap),
            ) {
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

internal fun homeShelfColumnCount(compactColumns: Int, fontScale: Float): Int =
    if (fontScale >= HOME_SHELF_LARGE_TEXT_SCALE) minOf(2, compactColumns) else compactColumns

private const val HOME_SHELF_LARGE_TEXT_SCALE = 1.3f
