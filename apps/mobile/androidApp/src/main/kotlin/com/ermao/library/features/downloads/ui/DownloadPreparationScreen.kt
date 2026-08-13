package com.ermao.library.features.downloads.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.downloads.application.DownloadPreparationUiState
import com.ermao.library.ui.theme.WarmPageThemeValues

@Composable
fun DownloadPreparationScreen(
    title: String,
    author: String,
    coverBytes: ByteArray?,
    state: DownloadPreparationUiState,
    onRetry: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(theme.colors.canvas)
            .padding(horizontal = theme.spacing.four, vertical = theme.spacing.three)
            .testTag("download-preparation"),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.weight(0.35f))
        Box(
            Modifier
                .width(180.dp)
                .aspectRatio(2f / 3f)
                .clip(RoundedCornerShape(theme.radii.coverHero))
                .background(theme.colors.surface),
            contentAlignment = Alignment.Center,
        ) {
            val bitmap = coverBytes?.let { BitmapFactory.decodeByteArray(it, 0, it.size) }
            if (bitmap != null) {
                Image(
                    bitmap = bitmap.asImageBitmap(),
                    contentDescription = stringResource(R.string.cover_content_description, title),
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                Icon(Icons.Outlined.Book, null, tint = theme.colors.textTertiary, modifier = Modifier.size(52.dp))
            }
        }
        Spacer(Modifier.weight(0.18f))
        Text(title, style = theme.typography.title, maxLines = 2, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center)
        if (author.isNotBlank()) {
            Text(author, style = theme.typography.callout, color = theme.colors.textSecondary, maxLines = 1)
        }
        Spacer(Modifier.weight(0.12f))
        when (state) {
            DownloadPreparationUiState.CheckingExisting,
            DownloadPreparationUiState.CreatingTask,
            -> {
                CircularProgressIndicator()
                Text(
                    stringResource(
                        if (state == DownloadPreparationUiState.CreatingTask) {
                            R.string.download_preparing_task
                        } else {
                            R.string.download_checking_local
                        },
                    ),
                    modifier = Modifier.padding(top = theme.spacing.two),
                    color = theme.colors.textSecondary,
                )
            }
            is DownloadPreparationUiState.Downloading -> {
                val progress = (state.transferredBytes.toFloat() / state.totalBytes).coerceIn(0f, 1f)
                LinearProgressIndicator(
                    progress = { progress },
                    modifier = Modifier.fillMaxWidth().testTag("download-preparation-progress"),
                    color = theme.colors.brandAccent,
                    trackColor = theme.colors.divider,
                )
                Text(
                    stringResource(
                        R.string.download_progress_detail,
                        formatPreparationBytes(state.transferredBytes),
                        formatPreparationBytes(state.totalBytes),
                        (progress * 100).toInt(),
                    ),
                    modifier = Modifier.padding(top = theme.spacing.one),
                    color = theme.colors.textSecondary,
                )
                Text(
                    stringResource(R.string.download_first_open_explanation),
                    modifier = Modifier.padding(top = theme.spacing.two),
                    color = theme.colors.textSecondary,
                    textAlign = TextAlign.Center,
                )
            }
            is DownloadPreparationUiState.Failed -> {
                Text(stringResource(R.string.download_preparation_failed), color = androidx.compose.material3.MaterialTheme.colorScheme.error)
                Button(onClick = onRetry, modifier = Modifier.padding(top = theme.spacing.two)) {
                    Text(stringResource(R.string.retry_action))
                }
            }
            DownloadPreparationUiState.Completed -> Text(stringResource(R.string.download_opening_reader))
        }
        Spacer(Modifier.weight(0.15f))
        TextButton(onClick = onCancel) { Text(stringResource(R.string.download_cancel_and_return)) }
    }
}

private fun formatPreparationBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
    else -> "%.1f KB".format(bytes / 1024.0)
}
