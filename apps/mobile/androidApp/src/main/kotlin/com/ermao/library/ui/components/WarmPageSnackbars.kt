package com.ermao.library.ui.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.updateTransition
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material3.Icon
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.SnackbarVisuals
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalAccessibilityManager
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.ermao.library.shared.core.feedback.OperationFeedbackKind
import com.ermao.library.shared.core.feedback.OperationFeedbackPolicy
import com.ermao.library.ui.theme.WarmPageThemeValues
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first

/** One event, even when two consecutive operations produce identical localized text. */
private data class OperationSnackbarVisuals(
    override val message: String,
    val kind: OperationFeedbackKind,
    override val actionLabel: String?,
    override val withDismissAction: Boolean,
    override val duration: SnackbarDuration,
    val id: UUID = UUID.randomUUID(),
) : SnackbarVisuals

val LocalWarmPageFeedbackState = staticCompositionLocalOf<SnackbarHostState?> { null }

@Composable
fun rememberWarmPageFeedbackState(): SnackbarHostState =
    LocalWarmPageFeedbackState.current ?: remember { SnackbarHostState() }

/** Native SnackbarHostState owns cancellation, queued actions, and the suspended result. */
suspend fun SnackbarHostState.showFeedback(
    message: String,
    kind: OperationFeedbackKind,
    actionLabel: String? = null,
    withDismissAction: Boolean = false,
    duration: SnackbarDuration = SnackbarDuration.Short,
): SnackbarResult {
    val resolvedKind = if (actionLabel != null) OperationFeedbackKind.Action else kind
    val previous = currentSnackbarData
    if (previous != null) {
        if (!OperationFeedbackPolicy.canReplace(
                (previous.visuals as? OperationSnackbarVisuals)?.kind ?: OperationFeedbackKind.Action,
                resolvedKind,
            )) return SnackbarResult.Dismissed
        previous.dismiss()
    }
    return showSnackbar(OperationSnackbarVisuals(
        message, resolvedKind, actionLabel,
        withDismissAction && resolvedKind != OperationFeedbackKind.Success, duration,
    ))
}

/** The shell calls this inside its content bounds, above navigation and the audio accessory. */
@Composable
fun WarmPageAppFeedbackHost(modifier: Modifier = Modifier) {
    LocalWarmPageFeedbackState.current?.let { FeedbackHost(it, modifier) }
}

@Composable
fun WarmPageSnackbarHost(hostState: SnackbarHostState, modifier: Modifier = Modifier) {
    // A shell-owned state has exactly one visible host. Modal/reader states remain surface-owned.
    if (hostState !== LocalWarmPageFeedbackState.current) FeedbackHost(hostState, modifier)
}

@Composable
private fun FeedbackHost(hostState: SnackbarHostState, modifier: Modifier) {
    val theme = WarmPageThemeValues
    val accessibility = LocalAccessibilityManager.current
    val transition = updateTransition(hostState.currentSnackbarData, label = "operation-feedback")
    transition.AnimatedContent(
        modifier = modifier.testTag("warm-page-snackbar").padding(horizontal = 16.dp, vertical = 12.dp),
        transitionSpec = { (fadeIn(tween(150)) togetherWith fadeOut(tween(75))).using(null) },
        contentAlignment = Alignment.BottomCenter,
    ) { snackbar ->
        if (snackbar != null) {
            val visuals = snackbar.visuals
            val kind = (visuals as? OperationSnackbarVisuals)?.kind ?: OperationFeedbackKind.Action
            LaunchedEffect(snackbar, accessibility) {
                // Start the dwell only after the actual enter transition completes, including
                // platform animation-scale changes. A stale event cannot dismiss its replacement.
                snapshotFlow { transition.currentState === snackbar && !transition.isRunning }.first { it }
                val retained = when (visuals.duration) {
                    SnackbarDuration.Short -> 4_000L
                    SnackbarDuration.Long -> 10_000L
                    SnackbarDuration.Indefinite -> Long.MAX_VALUE
                }
                val timeout = OperationFeedbackPolicy.timeoutMillis(kind, retained)
                if (timeout != Long.MAX_VALUE) {
                    delay(accessibility?.calculateRecommendedTimeoutMillis(
                        timeout, containsIcons = true, containsText = true,
                        containsControls = visuals.actionLabel != null || visuals.withDismissAction,
                    ) ?: timeout)
                    if (hostState.currentSnackbarData === snackbar) snackbar.dismiss()
                }
            }
            if (kind == OperationFeedbackKind.Success) {
                Snackbar(
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    shape = RoundedCornerShape(16.dp),
                    containerColor = theme.colors.surfaceRaised,
                    contentColor = theme.colors.textPrimary,
                ) {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Icon(Icons.Outlined.CheckCircle, contentDescription = null,
                            tint = theme.colors.brandAccent, modifier = Modifier.size(22.dp))
                        Text(visuals.message, style = theme.typography.callout)
                    }
                }
            } else {
                Snackbar(
                    snackbarData = snackbar,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    shape = RoundedCornerShape(16.dp),
                    containerColor = theme.colors.surfaceRaised,
                    contentColor = theme.colors.textPrimary,
                    actionColor = theme.colors.actionAccent,
                    dismissActionContentColor = theme.colors.textSecondary,
                )
            }
        }
    }
}
