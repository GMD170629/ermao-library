package com.ermao.library.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

enum class WarmPageContentMessageKind {
    Loading,
    Empty,
    Error,
}

/** Compatibility bridge for pages migrated before the v2 visual component layer. */
@Composable
fun WarmPageContentMessage(
    kind: WarmPageContentMessageKind,
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    when (kind) {
        WarmPageContentMessageKind.Loading -> WarmPageLoadingState(
            modifier = modifier,
            title = title,
            message = message,
        )
        WarmPageContentMessageKind.Empty -> WarmPageEmptyState(
            title = title,
            message = message,
            modifier = modifier,
            actionLabel = actionLabel,
            onAction = onAction,
        )
        WarmPageContentMessageKind.Error -> WarmPageErrorState(
            title = title,
            message = message,
            modifier = modifier,
            retryLabel = actionLabel,
            onRetry = onAction,
        )
    }
}
