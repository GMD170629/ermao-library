package com.ermao.library.ui.components

import android.view.ViewTreeObserver
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.ModalBottomSheetProperties
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.window.DialogWindowProvider
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.launch

/**
 * Native Material sheet with the Warm Page surface and an explicit system-bar
 * contract. Material sheets own a separate window, so applying system bars to
 * the Activity alone is not sufficient on every Android implementation.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WarmPageModalBottomSheet(
    onDismissRequest: () -> Unit,
    modifier: Modifier = Modifier,
    skipPartiallyExpanded: Boolean = false,
    onDismissCompleted: (() -> Unit)? = null,
    canDismiss: () -> Boolean = { true },
    content: @Composable ColumnScope.() -> Unit,
) {
    val theme = WarmPageThemeValues
    val useDarkSystemBarIcons = useDarkSystemBarForeground(theme.colors.surface)
    val sheetState = rememberModalBottomSheetState(
        skipPartiallyExpanded = skipPartiallyExpanded,
    )
    val coroutineScope = rememberCoroutineScope()
    var dismissRequested by remember { mutableStateOf(false) }
    val requestDismiss: () -> Unit = {
        if (canDismiss() && !dismissRequested) {
            dismissRequested = true
            coroutineScope.launch {
                sheetState.hide()
                onDismissRequest()
                onDismissCompleted?.invoke()
            }
        }
    }
    ModalBottomSheet(
        onDismissRequest = requestDismiss,
        modifier = modifier,
        sheetState = sheetState,
        containerColor = theme.colors.surface,
        properties = ModalBottomSheetProperties(
            isAppearanceLightStatusBars = useDarkSystemBarIcons,
            isAppearanceLightNavigationBars = useDarkSystemBarIcons,
        ),
    ) {
        CompositionLocalProvider(LocalWarmPageModalSheetDismiss provides requestDismiss) {
            KeepModalSystemBarsVisible(useDarkSystemBarIcons)
            content()
        }
    }
}

/**
 * Dismissal owned by the Material sheet. Consumers that need to chain work
 * after the close animation can invoke this instead of updating their own
 * visibility state synchronously.
 */
internal val LocalWarmPageModalSheetDismiss = compositionLocalOf<(() -> Unit)?> { null }

internal fun useDarkSystemBarForeground(surface: Color): Boolean =
    surface.luminance() >= SYSTEM_BAR_LIGHT_SURFACE_LUMINANCE

@Composable
private fun KeepModalSystemBarsVisible(useDarkForeground: Boolean) {
    val view = LocalView.current
    DisposableEffect(view, useDarkForeground) {
        val dialogWindow = (view as? DialogWindowProvider)?.window
            ?: return@DisposableEffect onDispose {}
        val insetsController = WindowCompat.getInsetsController(dialogWindow, dialogWindow.decorView)
        val applySystemBars = {
            insetsController.isAppearanceLightStatusBars = useDarkForeground
            insetsController.isAppearanceLightNavigationBars = useDarkForeground
            insetsController.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_DEFAULT
            insetsController.show(WindowInsetsCompat.Type.systemBars())
        }
        val focusListener = ViewTreeObserver.OnWindowFocusChangeListener { hasFocus ->
            if (hasFocus) applySystemBars()
        }
        val observer = view.viewTreeObserver
        observer.addOnWindowFocusChangeListener(focusListener)
        view.post { applySystemBars() }
        onDispose {
            if (observer.isAlive) {
                observer.removeOnWindowFocusChangeListener(focusListener)
            }
        }
    }
}

private const val SYSTEM_BAR_LIGHT_SURFACE_LUMINANCE = 0.5f
