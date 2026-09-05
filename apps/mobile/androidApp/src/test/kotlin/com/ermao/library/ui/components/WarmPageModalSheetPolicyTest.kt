package com.ermao.library.ui.components

import androidx.compose.ui.graphics.Color
import com.ermao.library.ui.theme.AppLightColors
import com.ermao.library.ui.theme.ReaderNightColors
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WarmPageModalSheetPolicyTest {
    @Test
    fun systemBarForegroundFollowsTheRenderedSheetSurfaceRatherThanSystemTheme() {
        assertTrue(useDarkSystemBarForeground(AppLightColors.surface))
        assertFalse(useDarkSystemBarForeground(ReaderNightColors.surface))

        // An explicitly rendered app theme can differ from the host system
        // theme; only the actual sheet surface participates in this decision.
        assertTrue(useDarkSystemBarForeground(Color.White))
        assertFalse(useDarkSystemBarForeground(Color.Black))
    }
}
