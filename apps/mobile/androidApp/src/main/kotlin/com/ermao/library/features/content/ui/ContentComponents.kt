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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.progressSemantics
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.platform.persistence.AndroidCoverCache
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.components.WarmPageContentMessage
import com.ermao.library.ui.components.WarmPageContentMessageKind
import com.ermao.library.ui.components.rememberForwardProgress
import com.ermao.library.ui.theme.WarmPageThemeValues
import java.text.NumberFormat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

enum class CoverRole {
    Compact,
    Hero,
}

/** Compatibility surface for screens that have not migrated to [CoverRole] yet. */
enum class CoverSize {
    Small,
    Medium,
    Large,
}

internal fun compactCoverGridColumnCount(
    compactColumns: Int,
    largeTextColumns: Int,
    fontScale: Float,
): Int = if (fontScale >= COMPACT_COVER_LARGE_TEXT_SCALE) {
    minOf(largeTextColumns, compactColumns)
} else {
    compactColumns
}

internal fun compactCoverGridItemWidth(
    availableWidth: Dp,
    horizontalGap: Dp,
    columns: Int,
): Dp {
    require(columns > 0)
    return ((availableWidth - horizontalGap * (columns - 1)) / columns).coerceAtLeast(0.dp)
}

private const val COMPACT_COVER_LARGE_TEXT_SCALE = 1.3f

@Composable
fun BookCover(
    book: BookCard,
    repository: ContentRepository,
    context: ContentRequestContext,
    role: CoverRole,
    modifier: Modifier = Modifier,
    cacheRevision: Int = 0,
    managementEnabled: Boolean = true,
) {
    val cover: @Composable () -> Unit = { ContentCover(
        contentId = book.id,
        title = book.title,
        coverUrl = book.coverUrl,
        repository = repository,
        context = context,
        role = role,
        modifier = if (managementEnabled) Modifier else modifier,
        cacheRevision = cacheRevision,
    ) }
    if (managementEnabled) com.ermao.library.features.workmanagement.ManageableBookCover(book.id, book.title, modifier, completed = book.completed, content = cover) else cover()
}

@Composable
fun BookCover(
    book: BookCard,
    repository: ContentRepository,
    context: ContentRequestContext,
    size: CoverSize,
    modifier: Modifier = Modifier,
    cacheRevision: Int = 0,
) {
    BookCover(
        book = book,
        repository = repository,
        context = context,
        role = size.toCoverRole(),
        modifier = modifier,
        cacheRevision = cacheRevision,
    )
}

@Composable
fun ContentCover(
    contentId: String,
    title: String,
    coverUrl: String,
    repository: ContentRepository,
    context: ContentRequestContext,
    role: CoverRole,
    modifier: Modifier = Modifier,
    cacheRevision: Int = 0,
) {
    val theme = WarmPageThemeValues
    Box(
        modifier = modifier
            .aspectRatio(
                if (role == CoverRole.Hero) {
                    theme.components.covers.heroAspectRatio
                } else {
                    theme.metrics.coverAspectRatio
                },
            )
            .clip(
                RoundedCornerShape(
                    if (role == CoverRole.Hero) theme.radii.coverHero else theme.radii.coverCompact,
                ),
        ),
        contentAlignment = Alignment.Center,
    ) {
        AuthenticatedCoverArtwork(
            contentId = contentId,
            title = title,
            coverUrl = coverUrl,
            repository = repository,
            context = context,
            modifier = Modifier.fillMaxSize(),
            cacheRevision = cacheRevision,
        )
    }
}

/** Authenticated cover bytes without prescribing the consumer's aspect ratio or surface. */
@Composable
internal fun AuthenticatedCoverArtwork(
    contentId: String,
    title: String,
    coverUrl: String,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
    cacheRevision: Int = 0,
) {
    val theme = WarmPageThemeValues
    val appContext = LocalContext.current.applicationContext
    val managementRevision = com.ermao.library.features.workmanagement.managementRevision()
    val image by produceState<ImageBitmap?>(
        null,
        contentId,
        coverUrl,
        context.namespace,
        cacheRevision,
        managementRevision,
    ) {
        value = coverUrl.takeIf(String::isNotBlank)?.let { authenticatedPath ->
            AndroidCoverCache.load(appContext, context, authenticatedPath, repository)
        }?.let { bytes ->
            withContext(Dispatchers.Default) {
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
            }
        }
    }
    Box(modifier = modifier, contentAlignment = Alignment.Center) {
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
                modifier = Modifier.size(theme.spacing.four),
            )
        }
    }
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
    ContentCover(
        contentId = contentId,
        title = title,
        coverUrl = coverUrl,
        repository = repository,
        context = context,
        role = size.toCoverRole(),
        modifier = modifier,
    )
}

@Composable
fun BookGridItem(
    book: BookCard,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Column(modifier = modifier.testTag("book-${book.id}")) {
        BookCover(
            book = book,
            repository = repository,
            context = context,
            role = CoverRole.Compact,
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            text = book.title,
            style = theme.typography.callout,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = theme.spacing.one),
        )
        Text(
            text = book.author,
            color = theme.colors.textSecondary,
            style = theme.typography.caption,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        book.progressPercent?.takeIf { it in 1..100 }?.let { progress ->
            CoverProgress(
                progressPercent = progress,
                modifier = Modifier.padding(top = theme.spacing.one),
            )
        }
    }
}

@Composable
fun BookListItem(
    book: BookCard,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier.testTag("book-${book.id}"),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.two),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BookCover(
            book = book,
            repository = repository,
            context = context,
            role = CoverRole.Compact,
            modifier = Modifier.width(theme.spacing.eight),
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
        ) {
            Text(
                text = book.title,
                style = theme.typography.headline,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = book.author,
                color = theme.colors.textSecondary,
                style = theme.typography.callout,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            book.progressPercent?.takeIf { it in 1..100 }?.let { progress ->
                ReadingProgress(progressPercent = progress)
            }
        }
    }
}

@Composable
fun CoverProgress(
    progressPercent: Int,
    modifier: Modifier = Modifier,
    stateDescription: String? = null,
) {
    val theme = WarmPageThemeValues
    val progress = normalizedProgress(progressPercent)
    val animatedProgress = rememberForwardProgress(progress)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .progressSemantics(progress)
            .withOptionalStateDescription(stateDescription)
            .padding(horizontal = theme.metrics.coverProgressHorizontalInset)
            .height(theme.spacing.two),
        contentAlignment = Alignment.CenterEnd,
    ) {
        if (progressPercent.coerceIn(0, 100) == 100) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = null,
                tint = theme.colors.brandAccent,
                modifier = Modifier.size(theme.spacing.two),
            )
        } else {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(theme.metrics.coverProgressHeight)
                    .clip(CircleShape)
                    .background(theme.colors.divider),
            ) {
                if (animatedProgress > 0f) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth(animatedProgress)
                            .height(theme.metrics.coverProgressHeight)
                            .clip(CircleShape)
                            .background(theme.colors.brandAccent),
                    )
                }
            }
        }
    }
}

@Composable
fun ReadingProgress(
    progressPercent: Int,
    modifier: Modifier = Modifier,
    stateDescription: String? = null,
) {
    val theme = WarmPageThemeValues
    val progress = normalizedProgress(progressPercent)
    val locale = LocalConfiguration.current.locales[0]
    val percentLabel = remember(locale, progressPercent) {
        NumberFormat.getPercentInstance(locale).apply {
            maximumFractionDigits = 0
        }.format(progress)
    }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .progressSemantics(progress)
            .withOptionalStateDescription(stateDescription),
        verticalArrangement = Arrangement.spacedBy(theme.spacing.half),
    ) {
        ReadingProgressTrack(progressPercent)
        Text(
            text = percentLabel,
            color = theme.colors.textSecondary,
            style = theme.typography.caption.copy(fontFamily = FontFamily.Monospace),
            modifier = Modifier.align(Alignment.End),
        )
    }
}

@Composable
fun ReadingProgressTrack(
    progressPercent: Int,
    modifier: Modifier = Modifier,
    stateDescription: String? = null,
) {
    val theme = WarmPageThemeValues
    val progress = normalizedProgress(progressPercent)
    val animatedProgress = rememberForwardProgress(progress)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(theme.metrics.readingProgressHeight)
            .clip(CircleShape)
            .background(theme.colors.divider)
            .progressSemantics(progress)
            .withOptionalStateDescription(stateDescription),
    ) {
        if (animatedProgress > 0f) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(animatedProgress)
                    .height(theme.metrics.readingProgressHeight)
                    .clip(CircleShape)
                    .background(theme.colors.brandAccent),
            )
        }
    }
}

internal fun responsiveCoverColumnCount(availableWidth: Dp, fontScale: Float): Int =
    if (availableWidth >= 360.dp && fontScale <= 1.15f) 3 else 2

@Composable
fun ContentAreaMessage(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
    loading: Boolean = false,
) {
    WarmPageContentMessage(
        kind = if (loading) WarmPageContentMessageKind.Loading else WarmPageContentMessageKind.Error,
        title = title,
        message = message,
        modifier = modifier,
        actionLabel = actionLabel,
        onAction = onAction,
    )
}

internal fun normalizedProgress(progressPercent: Int): Float = progressPercent.coerceIn(0, 100) / 100f

private fun CoverSize.toCoverRole(): CoverRole = when (this) {
    CoverSize.Small,
    CoverSize.Medium,
    -> CoverRole.Compact

    CoverSize.Large -> CoverRole.Hero
}

private fun Modifier.withOptionalStateDescription(description: String?): Modifier = if (description == null) {
    this
} else {
    semantics { stateDescription = description }
}
