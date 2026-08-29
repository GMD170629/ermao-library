package com.ermao.library.features.reader.presentation

import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue
import org.junit.Test

class ReaderNavigatorAttachmentStateTest {
    @Test
    fun containerCallbackBeforePreparationDefersThenBindsExactlyOnce() {
        val state = ReaderNavigatorAttachmentState<Any, Any>()
        val session = Any()
        val navigator = Any()

        state.markContainerReady()
        assertNull(state.claim(session, fragmentStateSaved = false))

        assertTrue(state.publish(session, session, navigator))
        val prepared = state.claim(session, fragmentStateSaved = false)
        assertSame(session, prepared?.session)
        assertSame(navigator, prepared?.navigator)
        assertNull(state.claim(session, fragmentStateSaved = false))

        state.markBound(requireNotNull(prepared))
        assertNull(state.claim(session, fragmentStateSaved = false))
    }

    @Test
    fun preparationCompletingForReplacedSessionCannotBindCurrentSession() {
        val state = ReaderNavigatorAttachmentState<Any, Any>()
        val preparingSession = Any()
        val currentSession = Any()

        state.markContainerReady()

        assertFalse(state.publish(currentSession, preparingSession, Any()))
        assertNull(state.claim(currentSession, fragmentStateSaved = false))
    }

    @Test
    fun savedFragmentStateAndUnavailableContainerDeferThePreparedPair() {
        val state = ReaderNavigatorAttachmentState<Any, Any>()
        val session = Any()
        val navigator = Any()

        assertTrue(state.publish(session, session, navigator))
        assertNull(state.claim(session, fragmentStateSaved = false))

        state.markContainerReady()
        assertNull(state.claim(session, fragmentStateSaved = true))
        assertSame(navigator, state.claim(session, fragmentStateSaved = false)?.navigator)
    }
}
