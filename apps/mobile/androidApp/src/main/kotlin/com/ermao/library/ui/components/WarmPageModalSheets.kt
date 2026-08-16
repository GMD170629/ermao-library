package com.ermao.library.ui.components

import android.view.ViewTreeObserver
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.ModalBottomSheetProperties
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.window.DialogWindowProvider
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.ermao.library.ui.theme.WarmPageThemeValues

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
    content: @Composable ColumnScope.() -> Unit,
) {
    val theme = WarmPageThemeValues
    val useDarkSystemBarIcons = useDarkSystemBarForeground(theme.colors.surface)
    val sheetState = rememberModalBottomSheetState(
        skipPartiallyExpanded = skipPartiallyExpanded,
    )
    ModalBottomSheet(
        onDismissRequest = onDismissRequest,
        modifier = modifier,
        sheetState = sheetState,
        containerColor = theme.colors.surface,
        properties = ModalBottomSheetProperties(
            isAppearanceLightStatusBars = useDarkSystemBarIcons,
            isAppearanceLightNavigationBars = useDarkSystemBarIcons,
        ),
    ) {
        KeepModalSystemBarsVisible(useDarkSystemBarIcons)
        content()
    }
}

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
