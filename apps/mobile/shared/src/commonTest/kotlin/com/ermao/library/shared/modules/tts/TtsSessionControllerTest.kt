package com.ermao.library.shared.modules.tts

import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

class TtsSessionControllerTest {
    @Test
    fun attachmentAndRestorationNeverStartSpeech() {
        val controller = TtsSessionController()
        assertEquals(TtsPlaybackState.Idle, controller.snapshot().playbackState)
        assertTrue(controller.play().effects.isEmpty())

        val locator = locator()
        val opened = controller.open(session(), locator)
        assertEquals(TtsPlaybackState.Ready, opened.state.playbackState)
        assertSame(locator, opened.state.locator)
        assertTrue(opened.effects.isEmpty())

        val started = assertIs<TtsStart>(controller.play().effects.single())
        assertSame(locator, started.locator)
        assertEquals(session(), started.token.session)
        assertEquals(TtsPlaybackState.Starting, controller.snapshot().playbackState)
        assertTrue(controller.play().effects.isEmpty())
        assertEquals(TtsPlaybackState.Playing, controller.engineStarted(started.token).state.playbackState)
    }

    @Test
    fun carriesOpaqueEngineLocatorsWithoutInspectingOrRebuildingThem() {
        val controller = openedController()
        val token = startPlaying(controller)
        val locator = locator("""{"text":{"highlight":""},"unknown":null,"extensions":{"vendor":42}}""")

        val changed = controller.enginePositionChanged(token, locator)

        assertSame(locator, changed.state.locator)
        assertEquals(locator.canonicalJson, changed.state.locator?.canonicalJson)
        assertTrue(changed.effects.isEmpty())
    }

    @Test
    fun onlyPlayingAcceptsPositionAndNaturalCompletion() {
        val controller = openedController()
        val token = assertIs<TtsStart>(controller.play().effects.single()).token
        val original = controller.snapshot()

        assertEquals(original, controller.enginePositionChanged(token, locator("""{"new":true}""")).state)
        assertEquals(original, controller.engineCompleted(token).state)

        controller.engineStarted(token)
        val completed = controller.engineCompleted(token)
        assertEquals(TtsPlaybackState.Completed, completed.state.playbackState)
        assertSame(token, assertIs<TtsStop>(completed.effects.single()).token)
        assertNull(completed.state.failure)
        assertIgnoredFacts(controller, token)
    }

    @Test
    fun stoppingPendingStartRejectsAllLateEngineFacts() {
        val controller = openedController()
        val token = assertIs<TtsStart>(controller.play().effects.single()).token

        val stopped = controller.stop()

        assertEquals(TtsPlaybackState.Stopped, stopped.state.playbackState)
        assertSame(token, assertIs<TtsStop>(stopped.effects.single()).token)
        assertIgnoredFacts(controller, token)
        assertTrue(controller.stop().effects.isEmpty())
    }

    @Test
    fun stoppingPlaybackRejectsOldFactsEvenAfterExplicitRestart() {
        val controller = openedController()
        val old = startPlaying(controller)
        controller.stop()
        assertIgnoredFacts(controller, old)

        val new = assertIs<TtsStart>(controller.play().effects.single()).token

        assertNotEquals(old, new)
        assertIgnoredFacts(controller, old)
        assertEquals(TtsPlaybackState.Playing, controller.engineStarted(new).state.playbackState)
    }

    @Test
    fun pauseAndResumeKeepNativeSessionButUseNewCallbackIdentity() {
        val controller = openedController()
        val old = startPlaying(controller)
        val position = locator("""{"utterance":{"extension":"native"}}""")
        controller.enginePositionChanged(old, position)

        val paused = controller.pause()

        assertEquals(TtsPlaybackState.Paused, paused.state.playbackState)
        assertSame(old, assertIs<TtsPause>(paused.effects.single()).token)
        assertIgnoredFacts(controller, old)
        assertTrue(controller.pause().effects.isEmpty())

        val resumed = assertIs<TtsResume>(controller.play().effects.single())
        assertSame(old, resumed.pausedToken)
        assertNotEquals(old, resumed.token)
        assertEquals(old.session, resumed.token.session)
        assertSame(position, controller.snapshot().locator)
        assertIgnoredFacts(controller, old)
        assertEquals(TtsPlaybackState.Playing, controller.engineStarted(resumed.token).state.playbackState)
    }

    @Test
    fun pausingPendingStartCancelsSetupAndNextPlayStartsFresh() {
        val controller = openedController()
        val old = assertIs<TtsStart>(controller.play().effects.single()).token

        val paused = controller.pause()

        assertEquals(TtsPlaybackState.Paused, paused.state.playbackState)
        assertSame(old, assertIs<TtsStop>(paused.effects.single()).token)
        assertIgnoredFacts(controller, old)
        val new = assertIs<TtsStart>(controller.play().effects.single()).token
        assertNotEquals(old, new)
        assertIgnoredFacts(controller, old)
    }

    @Test
    fun stopReleasesPausedEngineAndDoesNotResumeIt() {
        val controller = openedController()
        val old = startPlaying(controller)
        controller.pause()

        assertSame(old, assertIs<TtsStop>(controller.stop().effects.single()).token)
        assertEquals(TtsPlaybackState.Stopped, controller.snapshot().playbackState)
        assertIgnoredFacts(controller, old)
        assertIs<TtsStart>(controller.play().effects.single())
    }

    @Test
    fun failedPauseFailsTheSessionAndStopsTheEngineInsteadOfClaimingItIsPaused() {
        val controller = openedController()
        val token = startPlaying(controller)
        controller.pause()
        val failure = TtsFailure("TTS_PAUSE_FAILED")

        val failed = controller.pauseFailed(token, failure)

        assertEquals(TtsPlaybackState.Failed, failed.state.playbackState)
        assertEquals(failure, failed.state.failure)
        assertSame(token, assertIs<TtsStop>(failed.effects.single()).token)
        assertIgnoredFacts(controller, token)
        assertTrue(controller.pauseFailed(token, failure).effects.isEmpty())
        assertIs<TtsStart>(controller.play().effects.single())
    }

    @Test
    fun delayedPauseFailureCannotAffectAResumedStoppedOrReplacedSession() {
        listOf("resume", "stop", "switch", "dispose").forEach { command ->
            val controller = openedController()
            val old = startPlaying(controller)
            controller.pause()
            when (command) {
                "resume" -> controller.play()
                "stop" -> controller.stop()
                "switch" -> controller.open(session().copy(resourceId = "other-resource"), locator())
                "dispose" -> controller.dispose()
            }
            val expected = controller.snapshot()

            val ignored = controller.pauseFailed(old, TtsFailure("TTS_LATE_PAUSE_FAILED"))

            assertEquals(expected, ignored.state)
            assertTrue(ignored.effects.isEmpty())
        }
    }

    @Test
    fun switchingServerAccountBookResourceAuthorizationOrPublicationInvalidatesPreviousRun() {
        val oldSession = session()
        val replacements = listOf(
            oldSession.copy(namespace = oldSession.namespace.copy(serverIdentity = "other-server")),
            oldSession.copy(namespace = oldSession.namespace.copy(userId = "other-user")),
            oldSession.copy(namespace = oldSession.namespace.copy(authorizationVersion = 2)),
            oldSession.copy(bookId = "other-book"),
            oldSession.copy(resourceId = "other-resource"),
            oldSession.copy(readerSessionId = "reopened-publication"),
            oldSession,
        )
        replacements.forEach { replacement ->
            val controller = openedController()
            val old = startPlaying(controller)
            val target = locator("""{"target":null}""")

            val switched = controller.open(replacement, target)

            assertEquals(TtsPlaybackState.Ready, switched.state.playbackState)
            assertEquals(replacement, switched.state.session)
            assertSame(target, switched.state.locator)
            assertSame(old, assertIs<TtsStop>(switched.effects.single()).token)
            assertIgnoredFacts(controller, old)
            val new = assertIs<TtsStart>(controller.play().effects.single()).token
            assertEquals(replacement, new.session)
            assertNotEquals(old, new)
            assertIgnoredFacts(controller, old)
        }
    }

    @Test
    fun switchDuringSetupOrPauseAlsoReleasesTheOldEngine() {
        listOf(false, true).forEach { pause ->
            val controller = openedController()
            val token = assertIs<TtsStart>(controller.play().effects.single()).token
            if (pause) {
                controller.engineStarted(token)
                controller.pause()
            }

            val switched = controller.open(session().copy(resourceId = "other-resource"), locator())

            assertSame(token, assertIs<TtsStop>(switched.effects.single()).token)
            assertEquals(TtsPlaybackState.Ready, switched.state.playbackState)
            assertIgnoredFacts(controller, token)
        }
    }

    @Test
    fun errorIsTerminalForThatRunAndNeverBecomesCompleted() {
        listOf(false, true).forEach { started ->
            val controller = openedController()
            val token = assertIs<TtsStart>(controller.play().effects.single()).token
            if (started) controller.engineStarted(token)
            val failure = TtsFailure("TTS_ENGINE_UNAVAILABLE")

            val failed = controller.engineFailed(token, failure)

            assertEquals(TtsPlaybackState.Failed, failed.state.playbackState)
            assertEquals(failure, failed.state.failure)
            assertSame(token, assertIs<TtsStop>(failed.effects.single()).token)
            assertIgnoredFacts(controller, token)

            val retry = assertIs<TtsStart>(controller.play().effects.single()).token
            assertNotEquals(token, retry)
            assertNull(controller.snapshot().failure)
            assertEquals(TtsPlaybackState.Starting, controller.snapshot().playbackState)
            assertIgnoredFacts(controller, token)
        }
    }

    @Test
    fun disposalCancelsStartingPlayingAndPausedRunsAndCannotBeReopened() {
        listOf(TtsPlaybackState.Starting, TtsPlaybackState.Playing, TtsPlaybackState.Paused).forEach { stage ->
            val controller = openedController()
            val token = assertIs<TtsStart>(controller.play().effects.single()).token
            if (stage != TtsPlaybackState.Starting) controller.engineStarted(token)
            if (stage == TtsPlaybackState.Paused) controller.pause()

            val disposed = controller.dispose()

            assertEquals(TtsPlaybackState.Disposed, disposed.state.playbackState)
            assertNull(disposed.state.session)
            assertNull(disposed.state.locator)
            assertSame(token, assertIs<TtsStop>(disposed.effects.single()).token)
            assertIgnoredFacts(controller, token)
            assertEquals(disposed.state, controller.open(session(), locator()).state)
            assertTrue(controller.play().effects.isEmpty())
            assertTrue(controller.pause().effects.isEmpty())
            assertTrue(controller.stop().effects.isEmpty())
            assertTrue(controller.dispose().effects.isEmpty())
            assertEquals(disposed.state, controller.snapshot())
        }
    }

    @Test
    fun tokenFromAnotherControllerCannotMatchEvenWithIdenticalSessionIdentity() {
        val first = openedController()
        val second = openedController()
        val old = startPlaying(first)
        val current = startPlaying(second)
        assertEquals(old.session, current.session)

        assertIgnoredFacts(second, old)
        assertEquals(TtsPlaybackState.Completed, second.engineCompleted(current).state.playbackState)
    }

    @Test
    fun validatesPublicSessionAndStateBoundaries() {
        assertFailsWith<IllegalArgumentException> { session().copy(readerSessionId = " ") }
        assertFailsWith<IllegalArgumentException> { session().copy(bookId = "") }
        assertFailsWith<IllegalArgumentException> { session().copy(resourceId = " ") }
        assertFailsWith<IllegalArgumentException> { ReaderSyncNamespace("", "user", 1) }
        assertFailsWith<IllegalArgumentException> { ReaderSyncNamespace("server", "", 1) }
        assertFailsWith<IllegalArgumentException> { TtsFailure(" ") }
        assertFailsWith<IllegalArgumentException> { TtsState(TtsPlaybackState.Playing) }
        assertFailsWith<IllegalArgumentException> { TtsState(TtsPlaybackState.Ready, session()) }
        assertFailsWith<IllegalArgumentException> { TtsState(TtsPlaybackState.Failed, session(), locator()) }
        assertFailsWith<IllegalArgumentException> {
            TtsState(TtsPlaybackState.Completed, session(), locator(), TtsFailure("TTS_ENGINE_FAILURE"))
        }
    }

    private fun openedController(): TtsSessionController = TtsSessionController().also {
        it.open(session(), locator())
    }

    private fun startPlaying(controller: TtsSessionController): TtsPlaybackToken {
        val token = assertIs<TtsStart>(controller.play().effects.single()).token
        controller.engineStarted(token)
        return token
    }

    private fun assertIgnoredFacts(controller: TtsSessionController, token: TtsPlaybackToken) {
        val expected = controller.snapshot()
        val transitions = listOf(
            controller.engineStarted(token),
            controller.enginePositionChanged(token, locator("""{"late":true}""")),
            controller.engineCompleted(token),
            controller.engineFailed(token, TtsFailure("TTS_LATE_ERROR")),
        )
        transitions.forEach {
            assertEquals(expected, it.state)
            assertTrue(it.effects.isEmpty())
        }
    }

    private fun session(): TtsSession = TtsSession(
        readerSessionId = "reader-session-1",
        namespace = ReaderSyncNamespace("server-1", "user-1", 1),
        bookId = "book-1",
        resourceId = "resource-1",
    )

    private fun locator(json: String = "{}"): ReaderOpaqueLocator = ReaderOpaqueLocator.parse(json)
}
