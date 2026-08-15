package com.ermao.library.ui.theme

import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Test

class WarmPageMetricsTest {
    @Test
    fun androidMetricsMapTheGeneratedWarmPageContract() {
        assertEquals(2f / 3f, WarmPageMetricTokens.coverAspectRatio, 0.0001f)
        assertEquals(2.dp, WarmPageMetricTokens.coverProgressHeight)
        assertEquals(8.dp, WarmPageMetricTokens.coverProgressHorizontalInset)
        assertEquals(3.dp, WarmPageMetricTokens.readingProgressHeight)
        assertEquals(4.dp, WarmPageMetricTokens.downloadProgressHeight)
        assertEquals(48.dp, WarmPageMetricTokens.androidMinimumTouchTarget)
    }
}
