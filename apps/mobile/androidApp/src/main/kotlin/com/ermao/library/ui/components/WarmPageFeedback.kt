package com.ermao.library.ui.components

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Security
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.InputChip
import androidx.compose.material3.InputChipDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.ermao.library.ui.theme.WarmPageThemeValues

@Composable
fun WarmPageLoadingState(
    modifier: Modifier = Modifier,
    title: String? = null,
    message: String? = null,
) {
    val theme = WarmPageThemeValues
    WarmPageCenteredState(modifier) {
        CircularProgressIndicator(
            color = theme.colors.brandAccent,
            strokeWidth = theme.metrics.coverProgressHeight,
            modifier = Modifier.size(theme.components.controls.loadingIndicatorSize),
        )
        title?.let { WarmPageStateTitle(it) }
        message?.let { WarmPageStateMessage(it) }
    }
}

@Composable
fun WarmPageEmptyState(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    val theme = WarmPageThemeValues
    WarmPageCenteredState(modifier) {
        Icon(
            imageVector = Icons.Outlined.Book,
            contentDescription = null,
            tint = theme.colors.textSecondary,
            modifier = Modifier.size(theme.components.controls.iconSize),
        )
        WarmPageStateTitle(title)
        WarmPageStateMessage(message)
        if (actionLabel != null && onAction != null) WarmPageTextAction(actionLabel, onAction)
    }
}

@Composable
fun WarmPageErrorState(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    retryLabel: String? = null,
    onRetry: (() -> Unit)? = null,
) {
    val theme = WarmPageThemeValues
    WarmPageCenteredState(modifier) {
        Icon(
            imageVector = Icons.Outlined.ErrorOutline,
            contentDescription = null,
            tint = theme.colors.textSecondary,
            modifier = Modifier.size(theme.components.controls.iconSize),
        )
        WarmPageStateTitle(title)
        WarmPageStateMessage(message)
        if (retryLabel != null && onRetry != null) WarmPageTextAction(retryLabel, onRetry)
    }
}

@Composable
fun WarmPagePermissionGate(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    WarmPageCenteredState(modifier) {
        CircularProgressIndicator(
            color = theme.colors.brandAccent,
            strokeWidth = theme.metrics.coverProgressHeight,
            modifier = Modifier.size(theme.components.controls.loadingIndicatorSize),
        )
        Icon(
            imageVector = Icons.Outlined.Security,
            contentDescription = null,
            tint = theme.colors.textSecondary,
            modifier = Modifier.size(theme.components.controls.iconSize),
        )
        WarmPageStateTitle(title)
        WarmPageStateMessage(message)
    }
}

@Composable
fun WarmPagePaginationError(
    message: String,
    retryLabel: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = theme.spacing.one),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Outlined.ErrorOutline,
            contentDescription = null,
            tint = theme.colors.textSecondary,
            modifier = Modifier.size(theme.components.controls.iconSize),
        )
        Text(
            text = message,
            style = theme.typography.callout,
            color = theme.colors.textSecondary,
            modifier = Modifier.weight(1f),
        )
        WarmPageTextAction(retryLabel, onRetry)
    }
}

@Composable
fun WarmPagePaginationLoading(
    message: String,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.controls.minimumTouchTarget)
            .padding(vertical = theme.spacing.one),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(
            color = theme.colors.brandAccent,
            strokeWidth = theme.metrics.coverProgressHeight,
            modifier = Modifier.size(theme.components.controls.loadingIndicatorSize),
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
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
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
        if (actionLabel != null && onAction != null) WarmPageTextAction(actionLabel, onAction)
    }
}

@Composable
fun WarmPageInlineFilter(
    label: String,
    removeLabel: String,
    onRemove: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    InputChip(
        selected = true,
        onClick = onRemove,
        label = { Text(text = label, style = theme.typography.label) },
        trailingIcon = {
            Icon(
                imageVector = Icons.Filled.Close,
                contentDescription = removeLabel,
                modifier = Modifier.size(theme.spacing.two),
            )
        },
        colors = InputChipDefaults.inputChipColors(
            selectedContainerColor = theme.colors.canvas,
            selectedLabelColor = theme.colors.brandAccent,
            selectedTrailingIconColor = theme.colors.brandAccent,
        ),
        border = InputChipDefaults.inputChipBorder(
            enabled = true,
            selected = true,
            borderColor = theme.colors.canvas,
            selectedBorderColor = theme.colors.canvas,
        ),
        modifier = modifier.heightIn(min = theme.components.controls.minimumTouchTarget),
    )
}

@Composable
private fun WarmPageCenteredState(
    modifier: Modifier,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = theme.spacing.three, vertical = theme.spacing.six),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
        content = content,
    )
}

@Composable
private fun WarmPageStateTitle(title: String) {
    val theme = WarmPageThemeValues
    Text(text = title, style = theme.typography.headline, color = theme.colors.textPrimary)
}

@Composable
private fun WarmPageStateMessage(message: String) {
    val theme = WarmPageThemeValues
    Text(text = message, style = theme.typography.callout, color = theme.colors.textSecondary)
}
