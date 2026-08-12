package com.ermao.library.features.home.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
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
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.ui.CoverSize
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.ui.ContentAreaMessage
import com.ermao.library.features.content.ui.ContentStatusBanner
import com.ermao.library.features.content.ui.WorkCover
import com.ermao.library.features.home.application.HomeUiState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.theme.WarmPageThemeValues

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
                title = { Text(stringResource(R.string.tab_home), style = theme.typography.display) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = theme.colors.canvas,
                    scrolledContainerColor = theme.colors.surface,
                ),
            )
        },
    ) { padding ->
        when {
            state.isLoading -> ContentAreaMessage(
                title = stringResource(R.string.content_loading_title),
                message = stringResource(R.string.home_loading_message),
                loading = true,
                modifier = Modifier.padding(padding),
            )
            state.content == null -> ContentAreaMessage(
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
                        start = theme.spacing.three,
                        end = theme.spacing.three,
                        bottom = theme.spacing.six,
                    ),
                    verticalArrangement = Arrangement.spacedBy(theme.spacing.four),
                ) {
                    if (state.freshness != com.ermao.library.features.content.model.ContentFreshness.Fresh) {
                        item { ContentStatusBanner(state.freshness) }
                    }
                    content.continueReading?.let { item ->
                        item {
                            Surface(
                                color = theme.colors.surfaceRaised,
                                shape = RoundedCornerShape(theme.radii.task),
                                modifier = Modifier.fillMaxWidth().testTag("home-continue"),
                            ) {
                                Row(
                                    modifier = Modifier.padding(theme.spacing.three),
                                    horizontalArrangement = Arrangement.spacedBy(theme.spacing.three),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    WorkCover(
                                        item.work,
                                        repository,
                                        context,
                                        CoverSize.Medium,
                                        Modifier.width(92.dp),
                                    )
                                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
                                        Text(stringResource(R.string.home_continue_title), style = theme.typography.label, color = theme.colors.textSecondary)
                                        Text(item.work.title, style = theme.typography.sectionTitle, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                        item.volumeTitle?.let { Text(it, style = theme.typography.callout, color = theme.colors.textSecondary) }
                                        item.work.progressPercent?.let { Text(stringResource(R.string.progress_percent, it), style = theme.typography.caption, color = theme.colors.textSecondary) }
                                        Button(
                                            onClick = { onOpenWork(item.work.id) },
                                            colors = ButtonDefaults.buttonColors(containerColor = theme.colors.actionAccent),
                                            modifier = Modifier.fillMaxWidth().padding(top = theme.spacing.one),
                                        ) {
                                            Text(stringResource(R.string.home_view_detail_action))
                                            Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null, Modifier.padding(start = theme.spacing.one))
                                        }
                                    }
                                }
                            }
                        }
                    }
                    if (content.continueReading == null && content.recentReading.isEmpty() && content.recentAdded.isEmpty()) {
                        item {
                            ContentAreaMessage(
                                title = stringResource(R.string.home_empty_title),
                                message = stringResource(R.string.home_empty_message),
                                actionLabel = stringResource(R.string.home_browse_library),
                                onAction = onOpenLibrary,
                            )
                        }
                    } else {
                        if (content.recentReading.isNotEmpty()) {
                            item { HomeShelf(stringResource(R.string.home_recent_reading), content.recentReading, repository, context, onOpenWork) }
                        }
                        if (content.recentAdded.isNotEmpty()) {
                            item { HomeShelf(stringResource(R.string.home_recent_added), content.recentAdded, repository, context, onOpenWork) }
                        }
                    }
                    state.errorCode?.let {
                        item {
                            ContentAreaMessage(
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
private fun HomeShelf(
    title: String,
    works: List<WorkCard>,
    repository: ContentRepository,
    context: ContentRequestContext,
    onOpenWork: (String) -> Unit,
) {
    val theme = WarmPageThemeValues
    Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.two)) {
        Text(title, style = theme.typography.sectionTitle)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(theme.spacing.two)) {
            items(works, key = WorkCard::id) { work ->
                Column(
                    modifier = Modifier.width(104.dp).clickable { onOpenWork(work.id) },
                    verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
                ) {
                    WorkCover(work, repository, context, CoverSize.Small, Modifier.fillMaxWidth())
                    Text(work.title, style = theme.typography.callout, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(work.author, style = theme.typography.caption, color = theme.colors.textSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}
