package com.ermao.library.ui.components

import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import com.ermao.library.ui.theme.WarmPageThemeValues

@Composable
fun WarmPageSnackbarHost(
    hostState: SnackbarHostState,
    modifier: Modifier = Modifier,
) {
    val colors = WarmPageThemeValues.colors
    SnackbarHost(
        hostState = hostState,
        modifier = modifier.testTag("warm-page-snackbar"),
    ) { snackbarData ->
        Snackbar(
            snackbarData = snackbarData,
            containerColor = colors.surfaceRaised,
            contentColor = colors.textPrimary,
            actionColor = colors.actionAccent,
            dismissActionContentColor = colors.textSecondary,
        )
    }
}
