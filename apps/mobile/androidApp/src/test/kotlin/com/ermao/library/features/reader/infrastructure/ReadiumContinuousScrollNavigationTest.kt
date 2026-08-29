package com.ermao.library.features.reader.infrastructure

import kotlin.test.assertContains
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import org.junit.Test

class ReadiumContinuousScrollNavigationTest {
    @Test
    fun viewportAdvanceUsesVerticalReadingSpaceAndRequestedMotion() {
        val forward = continuousScrollViewportScript(direction = 1, animated = true)
        val backward = continuousScrollViewportScript(direction = -1, animated = false)

        assertContains(forward, "scrollHeight - window.innerHeight")
        assertContains(forward, "1 * window.innerHeight * 0.88")
        assertContains(forward, "behavior: 'smooth'")
        assertContains(backward, "-1 * window.innerHeight * 0.88")
        assertContains(backward, "behavior: 'auto'")
        assertTrue(forward.contains("return false"))
    }

    @Test
    fun viewportAdvanceRejectsAnUnrelatedDirection() {
        assertFailsWith<IllegalArgumentException> {
            continuousScrollViewportScript(direction = 0, animated = false)
        }
    }
}
