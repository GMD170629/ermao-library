package com.ermao.library.features.reader.infrastructure

import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class ReadiumRestoreCandidateTest {
    @Test
    fun acceptsSameResourceWithoutRequiringTextHighlight() {
        assertTrue(
            readiumNavigationMatchesRestoreCandidate(
                expectedHref = "chapter.xhtml",
                actualHref = "chapter.xhtml",
                expectedFragments = emptyList(),
                actualFragments = emptyList(),
                expectedPosition = null,
                actualPosition = null,
                expectedProgression = 0.8,
                actualProgression = 0.805,
            ),
        )
    }

    @Test
    fun rejectsDifferentResourceOrAnchor() {
        assertFalse(
            readiumNavigationMatchesRestoreCandidate(
                expectedHref = "chapter.xhtml",
                actualHref = "other.xhtml",
                expectedFragments = emptyList(),
                actualFragments = emptyList(),
                expectedPosition = 8,
                actualPosition = 8,
                expectedProgression = 0.8,
                actualProgression = 0.8,
            ),
        )
        assertFalse(
            readiumNavigationMatchesRestoreCandidate(
                expectedHref = "chapter.xhtml",
                actualHref = "chapter.xhtml",
                expectedFragments = emptyList(),
                actualFragments = emptyList(),
                expectedPosition = 8,
                actualPosition = 9,
                expectedProgression = 0.8,
                actualProgression = 0.8,
            ),
        )
    }
}
