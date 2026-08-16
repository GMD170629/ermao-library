package com.ermao.library.ui.components

import kotlin.test.assertEquals
import org.junit.Test

class ForwardProgressMotionTest {
    @Test
    fun normalForwardUpdatesAnimate() {
        assertEquals(
            ProgressMotion.AnimateForward,
            progressMotion(from = 0.2f, to = 0.8f),
        )
    }

    @Test
    fun backwardCorrectionsAndUnchangedValuesSnapImmediately() {
        assertEquals(ProgressMotion.Snap, progressMotion(from = 0.8f, to = 0.2f))
        assertEquals(ProgressMotion.Snap, progressMotion(from = 0.4f, to = 0.4f))
    }
}
