package com.ermao.library.ui.theme

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Test

class WarmPageComponentMetricsTest {
    @Test
    fun androidComponentGeometryHasOneNamedSource() {
        val metrics = WarmPageComponentMetricTokens

        assertEquals(16.dp, metrics.page.compactGutter)
        assertEquals(24.dp, metrics.page.sectionGap)
        assertEquals(840.dp, metrics.page.expandedBreakpoint)
        assertEquals(72.dp, metrics.topBar.rootHeight)
        assertEquals(64.dp, metrics.topBar.detailHeight)
        assertEquals(48.dp, metrics.controls.minimumTouchTarget)
        assertEquals(48.dp, metrics.controls.searchMinimumHeight)
        assertEquals(48.dp, metrics.controls.segmentedMinimumHeight)
        assertEquals(48.dp, metrics.menu.itemMinimumHeight)
        assertEquals(3, metrics.grid.compactColumns)
        assertEquals(2, metrics.grid.largeTextColumns)
        assertEquals(Dp.Hairline, metrics.dividerThickness)
    }

    @Test
    fun repeatedCoverCompositionGeometryIsCentralized() {
        val covers = WarmPageComponentMetricTokens.covers

        assertEquals(104.dp, covers.continueWidth)
        assertEquals(112.dp, covers.heroWidth)
        assertEquals(2f / 3f, covers.heroAspectRatio, 0.0001f)
        assertEquals(104.dp, covers.groupingStackWidth)
        assertEquals(78.dp, covers.groupingStackHeight)
        assertEquals(52.dp, covers.groupingCoverWidth)
        assertEquals(24.dp, covers.groupingCoverOffset)
    }

    @Test
    fun workDetailContinuousLayoutGeometryIsCentralized() {
        val metrics = WarmPageComponentMetricTokens.workDetail

        assertEquals(120.dp, metrics.heroCoverWidth)
        assertEquals(84.dp, metrics.horizontalVolumeWidth)
        assertEquals(56.dp, metrics.chapterRowMinimumHeight)
        assertEquals(24.dp, metrics.statusBadgeMinimumHeight)
    }
}
