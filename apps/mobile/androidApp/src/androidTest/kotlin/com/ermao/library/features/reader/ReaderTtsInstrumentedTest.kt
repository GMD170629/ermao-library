package com.ermao.library.features.reader

import android.os.SystemClock
import android.view.KeyEvent
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.tts.domain.TtsPlaybackState
import java.io.ByteArrayInputStream
import java.util.UUID
import org.json.JSONObject
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.Rule
import org.junit.runner.RunWith

/** Uses the actual system engine and Reader Activity. Does not infer audible output from Playing. */
@RunWith(AndroidJUnit4::class)
class ReaderTtsInstrumentedTest {
    @get:Rule val composeRule = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val store = AndroidReaderPublicationStore(context)

    @Test
    fun stopDuringSetupAndExitRejectLatePlayback() = withReader { scenario, reader ->
        val state = checkNotNull(reader.ttsState)
        assertEquals(TtsPlaybackState.Idle, state.value.playbackState)
        repeat(2) {
            scenario.onActivity {
                reader.playTts()
                reader.stopTts()
                assertEquals(TtsPlaybackState.Stopped, state.value.playbackState)
            }
            SystemClock.sleep(1000)
            assertEquals(TtsPlaybackState.Stopped, state.value.playbackState)
        }
        scenario.onActivity { reader.playTts() }
        scenario.close()
        SystemClock.sleep(1000)
        assertEquals(TtsPlaybackState.Disposed, state.value.playbackState)
    }

    @Test
    fun systemEngineSupportsPauseResumeAndForegroundInterruptionWithoutMovingReader() = withReader { scenario, reader ->
        val state = checkNotNull(reader.ttsState)
        val visualPosition = reader.currentLocation.value
        scenario.onActivity { reader.playTts(); reader.playTts() }
        await("system TTS startup; failure=${state.value.failure}") {
            state.value.playbackState == TtsPlaybackState.Playing || state.value.failure != null
        }
        assertEquals("Actual engine startup failed: ${state.value.failure}", TtsPlaybackState.Playing, state.value.playbackState)
        SystemClock.sleep(2000)
        assertEquals("Engine must not report a delayed synthesis failure", TtsPlaybackState.Playing, state.value.playbackState)
        scenario.onActivity {
            reader.pauseTts()
            assertEquals(TtsPlaybackState.Paused, state.value.playbackState)
            reader.playTts()
        }
        await("system TTS resume") { state.value.playbackState == TtsPlaybackState.Playing || state.value.failure != null }
        assertEquals(TtsPlaybackState.Playing, state.value.playbackState)
        assertEquals("TTS must not move the visual Reader", visualPosition, reader.currentLocation.value)
        scenario.moveToState(Lifecycle.State.CREATED)
        assertEquals(TtsPlaybackState.Stopped, state.value.playbackState)
        scenario.moveToState(Lifecycle.State.RESUMED)
        SystemClock.sleep(300)
        assertEquals("Foreground return must not start speech", TtsPlaybackState.Stopped, state.value.playbackState)
        scenario.onActivity { reader.playTts() }
        await("explicit restart") { state.value.playbackState == TtsPlaybackState.Playing || state.value.failure != null }
        assertEquals(TtsPlaybackState.Playing, state.value.playbackState)
        scenario.onActivity { reader.stopTts() }
        assertEquals(TtsPlaybackState.Stopped, state.value.playbackState)
        assertEquals(visualPosition, reader.currentLocation.value)
    }

    @Test
    fun openingAnotherBookDoesNotRestoreSpeech() {
        withReader { scenario, reader ->
            val oldState = checkNotNull(reader.ttsState)
            scenario.onActivity { reader.playTts() }
            scenario.close()
            assertEquals(TtsPlaybackState.Disposed, oldState.value.playbackState)
        }
        withReader { _, reader ->
            assertEquals(TtsPlaybackState.Idle, checkNotNull(reader.ttsState).value.playbackState)
            assertNotNull(reader.currentLocation.value)
        }
    }

    @Test
    fun readerToolbarControlsStartPauseResumeAndStop() = withReader { scenario, reader ->
        val state = checkNotNull(reader.ttsState)
        scenario.onActivity { it.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ESCAPE)) }
        composeRule.onNodeWithTag("reader-tts-play-pause").performClick()
        await("toolbar play") { state.value.playbackState == TtsPlaybackState.Playing || state.value.failure != null }
        assertEquals(TtsPlaybackState.Playing, state.value.playbackState)
        composeRule.onNodeWithTag("reader-tts-play-pause").performClick()
        assertEquals(TtsPlaybackState.Paused, state.value.playbackState)
        composeRule.onNodeWithTag("reader-tts-play-pause").performClick()
        await("toolbar resume") { state.value.playbackState == TtsPlaybackState.Playing || state.value.failure != null }
        assertEquals(TtsPlaybackState.Playing, state.value.playbackState)
        composeRule.onNodeWithTag("reader-tts-stop").performClick()
        assertEquals(TtsPlaybackState.Stopped, state.value.playbackState)
    }

    @Test
    fun startBorrowsTheCurrentReaderChapterLocator() = withReader { scenario, reader ->
        val destination = runBlocking { reader.loadTableOfContents() }.last()
        scenario.onActivity { assertTrue(reader.goTo(destination.location)) }
        await("second Reader chapter") {
            (reader.currentLocation.value as? com.ermao.library.shared.modules.reader.ReflowReaderLocation)
                ?.resourceKey == "text/chapter-0002.xhtml"
        }
        val state = checkNotNull(reader.ttsState)
        scenario.onActivity { reader.playTts() }
        await("speech from current chapter") { state.value.playbackState == TtsPlaybackState.Playing || state.value.failure != null }
        assertEquals(TtsPlaybackState.Playing, state.value.playbackState)
        assertEquals("text/chapter-0002.xhtml", JSONObject(checkNotNull(state.value.locator).canonicalJson).getString("href"))
        scenario.onActivity { reader.stopTts() }
    }

    private fun withReader(block: (ActivityScenario<ReaderActivity>, ReaderScreenController) -> Unit) = runBlocking {
        val id = "tts-reader-${UUID.randomUUID()}"
        val source: LocalReaderSource = ByteArrayInputStream(
            ("Chapter 1: Speech\n" + "This is a long spoken paragraph for pause and resume testing. ".repeat(100) +
                "\n\nChapter 2: Current position\n" + "Speech must begin at the current Reader chapter. ".repeat(100)).toByteArray(),
        ).use { input ->
            store.publishLocalPublication(id, "Foreground TTS", input, sourceFormat = ReaderSourceFormat.Txt)
        }
        try {
            ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
                scenario.keepReaderTestFixtureVisible()
                var controller: ReaderScreenController? = null
                await("Reader ready") {
                    scenario.onActivity { controller = it.controllerForTesting }
                    controller?.currentLocation?.value != null && controller?.ttsState != null
                }
                SystemClock.sleep(300)
                block(scenario, checkNotNull(controller))
            }
        } finally {
            deleteLocalReaderV5Position(context, source)
            store.delete(id)
        }
    }

    private fun await(description: String, condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (!condition() && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50)
        assertTrue(description, condition())
    }
}
