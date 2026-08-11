package com.ermao.library.ui.theme

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Test

class WarmPageTokensTest {
    @Test
    fun appPalettesUseTheFrozenWarmPageValues() {
        assertEquals(Color(0xFFFBFAF8), AppLightColors.canvas)
        assertEquals(Color(0xFF17191D), AppLightColors.textPrimary)
        assertEquals(Color(0xFFFF4F2A), AppLightColors.brandAccent)
        assertEquals(Color(0xFFC83B23), AppLightColors.actionAccent)

        assertEquals(Color(0xFF151311), AppDarkColors.canvas)
        assertEquals(Color(0xFFF3ECE4), AppDarkColors.textPrimary)
        assertEquals(Color(0xFFFF6B48), AppDarkColors.brandAccent)
        assertEquals(Color(0xFFFF7A58), AppDarkColors.actionAccent)
    }

    @Test
    fun readerPalettesRemainIndependentFromAppAppearance() {
        assertEquals(Color(0xFFFDF6EA), ReaderPaperColors.canvas)
        assertEquals(Color(0xFF2B2118), ReaderPaperColors.textPrimary)
        assertEquals(Color(0xFF151311), ReaderNightColors.canvas)
        assertEquals(Color(0xFFEFE7DD), ReaderNightColors.textPrimary)
    }
}
