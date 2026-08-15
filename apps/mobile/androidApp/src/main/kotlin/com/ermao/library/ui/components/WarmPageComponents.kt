package com.ermao.library.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import com.ermao.library.ui.theme.WarmPageThemeValues

enum class WarmPageContentMessageKind {
    Loading,
    Empty,
    Error,
}

enum class WarmPageStatusBannerKind {
    Offline,
    Stale,
}

@Composable
fun WarmPagePrimaryAction(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    loading: Boolean = false,
) {
    val theme = WarmPageThemeValues
    Button(
        onClick = onClick,
        enabled = enabled && !loading,
        shape = RoundedCornerShape(theme.radii.control),
        colors = ButtonDefaults.buttonColors(
            containerColor = theme.colors.actionAccent,
            contentColor = theme.colors.onAction,
        ),
        modifier = modifier
            .heightIn(min = theme.metrics.androidMinimumTouchTarget)
            .then(
                if (loading) Modifier.semantics { contentDescription = label } else Modifier,
            ),
    ) {
        if (loading) {
            CircularProgressIndicator(
                color = theme.colors.onAction,
                strokeWidth = theme.metrics.coverProgressHeight,
                modifier = Modifier.size(theme.spacing.three),
            )
        } else {
            Text(text = label, style = theme.typography.button)
        }
    }
}

@Composable
fun WarmPageContentMessage(
    kind: WarmPageContentMessageKind,
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = theme.spacing.six, horizontal = theme.spacing.three),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
    ) {
        when (kind) {
            WarmPageContentMessageKind.Loading -> CircularProgressIndicator(
                strokeWidth = theme.metrics.coverProgressHeight,
                modifier = Modifier.size(theme.spacing.four),
            )

            WarmPageContentMessageKind.Empty -> Icon(
                imageVector = Icons.Outlined.Book,
                contentDescription = null,
                tint = theme.colors.textSecondary,
                modifier = Modifier.size(theme.spacing.three),
            )

            WarmPageContentMessageKind.Error -> Icon(
                imageVector = Icons.Outlined.ErrorOutline,
                contentDescription = null,
                tint = theme.colors.textSecondary,
                modifier = Modifier.size(theme.spacing.three),
            )
        }
        Text(
            text = title,
            style = theme.typography.headline,
            color = theme.colors.textPrimary,
        )
        Text(
            text = message,
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
        )
        if (actionLabel != null && onAction != null) {
            TextButton(
                onClick = onAction,
                modifier = Modifier.heightIn(min = theme.metrics.androidMinimumTouchTarget),
            ) {
                Text(text = actionLabel, style = theme.typography.button)
            }
        }
    }
}

@Composable
fun WarmPageStatusBanner(
    kind: WarmPageStatusBannerKind,
    message: String,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(theme.colors.accentSoft, RoundedCornerShape(theme.radii.control))
            .padding(theme.spacing.two),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = when (kind) {
                WarmPageStatusBannerKind.Offline -> Icons.Outlined.CloudOff
                WarmPageStatusBannerKind.Stale -> Icons.Outlined.Sync
            },
            contentDescription = null,
            tint = theme.colors.textSecondary,
            modifier = Modifier.size(theme.spacing.three),
        )
        Text(
            text = message,
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
        )
    }
}

@Composable
fun WarmPageSectionHeader(
    title: String,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = title,
            style = theme.typography.sectionTitle,
            color = theme.colors.textPrimary,
            modifier = Modifier.weight(1f),
        )
        if (actionLabel != null && onAction != null) {
            TextButton(
                onClick = onAction,
                modifier = Modifier.heightIn(min = theme.metrics.androidMinimumTouchTarget),
            ) {
                Text(text = actionLabel, style = theme.typography.label)
            }
        }
    }
}
