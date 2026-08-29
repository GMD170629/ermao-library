package com.ermao.library.features.reader.infrastructure

import kotlin.test.assertEquals
import kotlin.test.assertNull
import org.junit.Test

class ReadiumPublicationPositionIndexTest {
    private val points = listOf(
        ReflowablePositionPoint("chapter-1.xhtml", 0.0, 0.0, 1),
        ReflowablePositionPoint("chapter-1.xhtml", 1.0, 0.4, 2),
        ReflowablePositionPoint("chapter-2.xhtml", 0.0, 0.4, 3),
        ReflowablePositionPoint("chapter-2.xhtml", 1.0, 1.0, 4),
    )

    @Test
    fun interpolatesChapterProgressionIntoWholePublicationProgress() {
        assertEquals(
            0.7,
            checkNotNull(resolveReflowableTotalProgression("chapter-2.xhtml", 0.5, null, points)),
            absoluteTolerance = 0.0001,
        )
    }

    @Test
    fun exactGlobalPositionWinsOverChapterProgression() {
        assertEquals(
            0.4,
            checkNotNull(resolveReflowableTotalProgression("chapter-1.xhtml", 0.9, 3, points)),
            absoluteTolerance = 0.0001,
        )
    }

    @Test
    fun clampsToNearestPointAtResourceBoundaries() {
        assertEquals(
            0.4,
            checkNotNull(resolveReflowableTotalProgression("chapter-2.xhtml#fragment", -0.2, null, points)),
            absoluteTolerance = 0.0001,
        )
        assertEquals(
            1.0,
            checkNotNull(resolveReflowableTotalProgression("chapter-2.xhtml", 1.4, null, points)),
            absoluteTolerance = 0.0001,
        )
    }

    @Test
    fun refusesToInventProgressWithoutMatchingPublicationPositions() {
        assertNull(resolveReflowableTotalProgression("missing.xhtml", 0.5, null, points))
        assertNull(resolveReflowableTotalProgression("chapter-1.xhtml", 0.5, null, emptyList()))
    }

    @Test
    fun selectsTheLocatorNearestToTheRequestedWholePublicationProgress() {
        val totalProgressions = listOf(0.0, 0.55, 1.0)

        assertEquals(1, nearestReflowablePositionIndex(0.6, totalProgressions))
        assertEquals(0, nearestReflowablePositionIndex(0.0, totalProgressions))
        assertEquals(2, nearestReflowablePositionIndex(1.0, totalProgressions))
        assertNull(nearestReflowablePositionIndex(0.5, emptyList()))
    }
}
