package com.ermao.library.features.content.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.theme.WarmPageThemeValues
import com.ermao.library.platform.persistence.AndroidCoverCache
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun WorkCover(
    work: WorkCard,
    repository: ContentRepository,
    context: ContentRequestContext,
    size: CoverSize,
    modifier: Modifier = Modifier,
) {
    ContentCover(
        contentId = work.id,
        title = work.title,
        coverUrl = work.coverUrl,
        repository = repository,
        context = context,
        size = size,
        modifier = modifier,
    )
}

@Composable
fun ContentCover(
    contentId: String,
    title: String,
    coverUrl: String,
    repository: ContentRepository,
    context: ContentRequestContext,
    size: CoverSize,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val appContext = LocalContext.current.applicationContext
    val image by produceState<ImageBitmap?>(null, contentId, coverUrl, size, context.namespace) {
        value = AndroidCoverCache.load(appContext, context, coverUrl, repository)?.let { bytes ->
            withContext(Dispatchers.Default) {
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
            }
        }
    }
    Box(
        modifier = modifier
            .aspectRatio(2f / 3f)
            .clip(RoundedCornerShape(if (size == CoverSize.Large) theme.radii.coverHero else theme.radii.coverCompact)),
        contentAlignment = Alignment.Center,
    ) {
        if (image != null) {
            Image(
                bitmap = image!!,
                contentDescription = stringResource(R.string.cover_content_description, title),
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Icon(
                imageVector = Icons.Outlined.Book,
                contentDescription = stringResource(R.string.cover_content_description, title),
                tint = theme.colors.textTertiary,
                modifier = Modifier.size(32.dp),
            )
        }
    }
}

@Composable
fun WorkGridItem(
    work: WorkCard,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Column(modifier = modifier.testTag("work-${work.id}")) {
        WorkCover(work, repository, context, CoverSize.Small, Modifier.fillMaxWidth())
        Text(
            text = work.title,
            style = theme.typography.callout,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = theme.spacing.one),
        )
        Text(
            text = work.author,
            color = theme.colors.textSecondary,
            style = theme.typography.caption,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        work.progressPercent?.takeIf { it in 1..99 }?.let { progress ->
            LinearProgressIndicator(
                progress = { progress / 100f },
                color = theme.colors.actionAccent,
                trackColor = theme.colors.divider,
                modifier = Modifier.fillMaxWidth().padding(top = theme.spacing.one).height(4.dp),
            )
        }
    }
}

enum class CoverSize { Small, Medium, Large }

@Composable
fun ContentStatusBanner(freshness: ContentFreshness, modifier: Modifier = Modifier) {
    if (freshness == ContentFreshness.Fresh) return
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(theme.colors.accentSoft, RoundedCornerShape(theme.radii.control))
            .padding(theme.spacing.two),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.CloudOff, contentDescription = null, tint = theme.colors.textSecondary)
        Text(
            text = stringResource(
                if (freshness == ContentFreshness.Cached) R.string.content_cached_banner else R.string.content_stale_banner,
            ),
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
        )
    }
}

@Composable
fun ContentAreaMessage(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
    loading: Boolean = false,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier.fillMaxWidth().padding(vertical = theme.spacing.six, horizontal = theme.spacing.three),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
    ) {
        if (loading) {
            CircularProgressIndicator(modifier = Modifier.size(28.dp), strokeWidth = 2.dp)
        } else {
            Icon(Icons.Outlined.ErrorOutline, contentDescription = null, tint = theme.colors.textSecondary)
        }
        Text(title, style = theme.typography.headline)
        Text(message, style = theme.typography.callout, color = theme.colors.textSecondary)
        if (actionLabel != null && onAction != null) Button(onClick = onAction) { Text(actionLabel) }
    }
}
