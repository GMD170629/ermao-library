package com.ermao.library.features.content.ui

import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Test

class ContentProgressTest {
    @Test
    fun normalizedProgressClampsExternalValuesToTheSupportedRange() {
        assertEquals(0f, normalizedProgress(-1), 0f)
        assertEquals(0.25f, normalizedProgress(25), 0f)
        assertEquals(1f, normalizedProgress(100), 0f)
        assertEquals(1f, normalizedProgress(101), 0f)
    }

    @Test
    fun responsiveCoverGridUsesThreeColumnsOnlyAtCompactDefaultTextDensity() {
        assertEquals(3, responsiveCoverColumnCount(360.dp, 1f))
        assertEquals(3, responsiveCoverColumnCount(412.dp, 1.15f))
        assertEquals(2, responsiveCoverColumnCount(359.dp, 1f))
        assertEquals(2, responsiveCoverColumnCount(412.dp, 1.3f))
        assertEquals(2, responsiveCoverColumnCount(412.dp, 2f))
    }
}
