package com.ermao.library.features.reader.presentation

import com.ermao.library.features.reader.application.shouldAnimateReaderNavigation
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderPageTurnAnimation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class ReaderMotionTest {
    @Test
    fun controlsUseTheApprovedTimingAndEightDpTravel() {
        assertEquals(
            ReaderControlMotionSpec(
                enterDurationMillis = 180,
                exitDurationMillis = 150,
                translationDp = 8,
            ),
            readerControlMotionSpec(systemAnimationsEnabled = true),
        )
    }

    @Test
    fun reducedMotionRemovesReaderControlTimingAndTravel() {
        assertEquals(
            ReaderControlMotionSpec(
                enterDurationMillis = 0,
                exitDurationMillis = 0,
                translationDp = 0,
            ),
            readerControlMotionSpec(systemAnimationsEnabled = false),
        )
    }

    @Test
    fun pageNavigationRespectsBothReaderPreferenceAndSystemMotionSetting() {
        val sliding = ReaderPreferences()
        val still = sliding.copy(
            epub = sliding.epub.copy(pageTurnAnimation = ReaderPageTurnAnimation.Off),
        )

        assertTrue(
            shouldAnimateReaderNavigation(sliding, ReaderMorphology.Reflowable, systemAnimationsEnabled = true),
        )
        assertFalse(
            shouldAnimateReaderNavigation(still, ReaderMorphology.Reflowable, systemAnimationsEnabled = true),
        )
        assertFalse(
            shouldAnimateReaderNavigation(sliding, ReaderMorphology.Reflowable, systemAnimationsEnabled = false),
        )
    }
}
