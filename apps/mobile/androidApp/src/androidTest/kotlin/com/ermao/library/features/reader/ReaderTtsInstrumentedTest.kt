package com.ermao.library.features.reader

import android.os.SystemClock
import android.util.Log
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
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.tts.domain.TtsPlaybackState
import java.io.ByteArrayInputStream
import java.util.UUID
import org.json.JSONObject
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.shared.ExperimentalReadiumApi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
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
    fun stopDuringSetupAndExitRejectLatePlayback() = withReader { scenario, reader, _ ->
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
    fun systemEngineSupportsPauseResumeAndForegroundInterruptionWithoutMovingReader() = withReader { scenario, reader, source ->
        val state = checkNotNull(reader.ttsState)
        val visualPosition = reader.currentLocation.value
        val durablePosition = checkNotNull(runBlocking { loadLocalReaderV5Position(context, source) })
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
        assertEquals("TTS must not write the durable Reader report or capture timestamp", durablePosition,
            runBlocking { loadLocalReaderV5Position(context, source) })
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
        assertEquals("Foreground interruption and TTS restart must preserve the durable Reader report", durablePosition,
            runBlocking { loadLocalReaderV5Position(context, source) })
    }

    @Test
    fun openingAnotherBookDoesNotRestoreSpeech() {
        withReader { scenario, reader, _ ->
            val oldState = checkNotNull(reader.ttsState)
            scenario.onActivity { reader.playTts() }
            await("old book decoration") { decorationProbe(scenario).getBoolean("visible") }
            scenario.close()
            assertEquals(TtsPlaybackState.Disposed, oldState.value.playbackState)
        }
        withReader { scenario, reader, _ ->
            assertEquals(TtsPlaybackState.Idle, checkNotNull(reader.ttsState).value.playbackState)
            assertNotNull(reader.currentLocation.value)
            assertEquals("A new book must not inherit speech decoration", 0, decorationProbe(scenario).getInt("count"))
        }
    }

    @Test
    fun readerToolbarControlsStartPauseResumeAndStop() = withReader { scenario, reader, _ ->
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
    fun startBorrowsTheCurrentReaderChapterLocator() = withReader { scenario, reader, _ ->
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

    @OptIn(ExperimentalReadiumApi::class)
    @Test
    fun toolbarSpeechHighlightsItsParagraphAndClearsOnStopWithoutWritingProgress() = withReader { scenario, reader, source ->
        val initialReport = runBlocking { loadLocalReaderV5Position(context, source) }
        runBlocking { reader.loadTableOfContents(); reader.flush() }
        assertEquals("Chapter presentation settles before speech", TtsPlaybackState.Idle,
            checkNotNull(reader.ttsState).value.playbackState)
        val visual = reader.currentLocation.value
        val saved = runBlocking { loadLocalReaderV5Position(context, source) }
        assertNotNull(checkNotNull(saved).position.presentation.chapter)
        Log.i("ReaderTtsTest", "highlight_baseline_without_speech initial=$initialReport settled=$saved")
        val state = checkNotNull(reader.ttsState)
        scenario.onActivity { it.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ESCAPE)) }
        composeRule.onNodeWithTag("reader-tts-play-pause").performClick()
        await("rendered speech paragraph highlight") {
            state.value.playbackState == TtsPlaybackState.Playing && decorationProbe(scenario).getBoolean("visible")
        }
        val probe = decorationProbe(scenario)
        assertEquals(1, probe.getInt("count"))
        val spokenSelector = JSONObject(checkNotNull(state.value.locator).canonicalJson)
            .getJSONObject("locations").getString("cssSelector")
        assertEquals(spokenSelector, probe.getString("selector"))
        composeRule.onNodeWithTag("reader-tts-play-pause").performClick()
        await("paused highlight") { state.value.playbackState == TtsPlaybackState.Paused }
        assertTrue(decorationProbe(scenario).getBoolean("visible"))
        composeRule.onNodeWithTag("reader-tts-play-pause").performClick()
        await("resumed highlight") { state.value.playbackState == TtsPlaybackState.Playing }
        scenario.moveToState(Lifecycle.State.CREATED)
        assertEquals(TtsPlaybackState.Stopped, state.value.playbackState)
        scenario.moveToState(Lifecycle.State.RESUMED)
        // Readium clears via requestAnimationFrame, suspended while the WebView is backgrounded.
        await("return to foreground has no speech highlight") { decorationProbe(scenario).getInt("count") == 0 }
        assertEquals(TtsPlaybackState.Stopped, state.value.playbackState)
        assertEquals(0, decorationProbe(scenario).getInt("count"))
        composeRule.onNodeWithTag("reader-tts-play-pause").performClick()
        await("explicit restart highlight") { decorationProbe(scenario).getBoolean("visible") }
        composeRule.onNodeWithTag("reader-tts-stop").performClick()
        await("removed speech decoration") {
            val stopped = decorationProbe(scenario)
            stopped.getInt("count") == 0 && !stopped.getBoolean("visible")
        }
        assertEquals(TtsPlaybackState.Stopped, state.value.playbackState)
        assertEquals(visual, reader.currentLocation.value)
        assertEquals(saved, runBlocking { loadLocalReaderV5Position(context, source) })
    }

    @OptIn(ExperimentalReadiumApi::class)
    private fun decorationProbe(scenario: ActivityScenario<ReaderActivity>): JSONObject {
        var native: EpubNavigatorFragment? = null
        scenario.onActivity { native = it.supportFragmentManager.fragments.filterIsInstance<EpubNavigatorFragment>().single() }
        val result = runBlocking { withContext(Dispatchers.Main) {
            checkNotNull(native).evaluateJavascript("""
                (() => {
                  const items = readium.getDecorations('reader-tts').items;
                  const group = document.querySelector('[data-group="reader-tts"]');
                  const visible = group && [...group.querySelectorAll('[data-style] > *')].some(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 &&
                      r.left < innerWidth && r.top < innerHeight && getComputedStyle(el).backgroundColor !== 'rgba(0, 0, 0, 0)';
                  });
                  return {count: items.length, selector: items[0]?.decoration.locator.locations.cssSelector,
                    visible: Boolean(visible)};
                })()
            """.trimIndent())
        } }
        return JSONObject(checkNotNull(result))
    }

    @OptIn(ExperimentalReadiumApi::class)
    @Test
    fun speechStartsAtTheVisibleParagraphAfterTurningPagesWithinAChapter() = withReader(
        content = "Chapter 1: Visible start\n" + (1..120).joinToString("\n\n") {
            "Visible paragraph number $it. This paragraph belongs to the displayed page."
        },
    ) { scenario, reader, source ->
        repeat(3) {
            val before = reader.currentLocation.value
            scenario.onActivity { assertTrue(reader.goNext()) }
            await("visual next page") { reader.currentLocation.value != before }
            SystemClock.sleep(300)
        }
        var native: EpubNavigatorFragment? = null
        scenario.onActivity { native = it.supportFragmentManager.fragments.filterIsInstance<EpubNavigatorFragment>().single() }
        val (visible, expected) = runBlocking { withContext(Dispatchers.Main) {
            val active = checkNotNull(native)
            val block = checkNotNull(active.firstVisibleElementLocator())
            val selector = checkNotNull(block.locations["cssSelector"] as? String)
            val quoted = active.evaluateJavascript("document.querySelector(${JSONObject.quote(selector)}).innerText")
            block to org.json.JSONArray("[$quoted]").getString(0)
        } }
        assertTrue("Must be away from chapter heading", expected.startsWith("Visible paragraph number"))
        val baseline = reader.currentLocation.value
        val saved = runBlocking { loadLocalReaderV5Position(context, source) }
        val state = checkNotNull(reader.ttsState)
        scenario.onActivity { reader.playTts() }
        await("first utterance text") {
            state.value.failure != null || (state.value.playbackState == TtsPlaybackState.Playing &&
                state.value.locator?.canonicalJson?.let {
                    val emitted = JSONObject(it)
                    // The supplied visible-element anchor has no progression. Require a locator
                    // emitted by the content iterator, rather than accepting our own input echo.
                    emitted.getJSONObject("locations").has("progression") &&
                        emitted.optJSONObject("text")?.optString("highlight")?.isNotBlank() == true
                } == true)
        }
        scenario.onActivity { reader.pauseTts() }
        val spoken = JSONObject(checkNotNull(state.value.locator).canonicalJson)
        Log.i("ReaderTtsTest", "visible_start native=${visible.toJSON()} expected=$expected utterance=$spoken")
        assertNull(state.value.failure)
        assertEquals(visible.href.toString(), spoken.getString("href"))
        assertEquals("Spoken content must use the visible block, including repeated sentences",
            visible.locations["cssSelector"], spoken.getJSONObject("locations").getString("cssSelector"))
        assertTrue("First utterance must belong to visible paragraph: $spoken; expected=$expected",
            expected.contains(spoken.getJSONObject("text").getString("highlight")))
        assertEquals(baseline, reader.currentLocation.value)
        assertEquals(saved, runBlocking { loadLocalReaderV5Position(context, source) })
        scenario.onActivity { reader.stopTts() }
    }

    private fun withReader(content: String? = null, block: (ActivityScenario<ReaderActivity>, ReaderScreenController, LocalReaderSource) -> Unit) = runBlocking {
        val id = "tts-reader-${UUID.randomUUID()}"
        val source: LocalReaderSource = ByteArrayInputStream(
            (content ?: ("Chapter 1: Speech\n" + "This is a long spoken paragraph for pause and resume testing. ".repeat(100) +
                "\n\nChapter 2: Current position\n" + "Speech must begin at the current Reader chapter. ".repeat(100))).toByteArray(),
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
                val readyReader = checkNotNull(controller)
                val initialProjection = readyReader.currentLocation.value
                var candidate: Pair<ReflowReaderLocation?, ReaderPositionLocalState?>? = null
                var stableSince = SystemClock.elapsedRealtime()
                await("native Locator and durable Reader report settle before speech") {
                    assertEquals("Readiness must settle without starting TTS", TtsPlaybackState.Idle,
                        checkNotNull(readyReader.ttsState).value.playbackState)
                    val native = readyReader.currentLocation.value as? ReflowReaderLocation
                    val saved = runBlocking { loadLocalReaderV5Position(context, source) }
                    val current = native to saved
                    if (candidate != current) {
                        candidate = current
                        stableSince = SystemClock.elapsedRealtime()
                    }
                    val savedLocations = saved?.position?.locator?.canonicalJson?.let(::JSONObject)?.optJSONObject("locations")
                    native?.position != null && native.totalProgression != null &&
                        saved?.position?.presentation?.currentHref == native.resourceKey &&
                        savedLocations?.optInt("position", -1) == native.position &&
                        SystemClock.elapsedRealtime() - stableSince >= 300
                }
                Log.i("ReaderTtsTest", "reader_ready_without_speech initial=$initialProjection settled=${readyReader.currentLocation.value}")
                block(scenario, readyReader, source)
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
