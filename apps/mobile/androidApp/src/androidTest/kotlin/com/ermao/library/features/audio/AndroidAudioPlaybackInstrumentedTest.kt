package com.ermao.library.features.audio

import android.app.Activity
import android.view.WindowManager
import androidx.compose.material3.Text
import androidx.compose.ui.test.ComposeTimeoutException
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.features.audio.application.AndroidAudioPlaybackRuntime
import com.ermao.library.features.audio.model.AndroidAudioLaunchIntent
import com.ermao.library.features.audio.model.AndroidAudioNamespace
import com.ermao.library.features.audio.model.AndroidAudioPhase
import com.ermao.library.features.audio.model.AndroidAudioTrack
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Real MediaController -> app MediaSessionService -> Media3 decoder/device clock.
 * This deliberately excludes server bootstrap, download verification and v5 persistence.
 */
@RunWith(AndroidJUnit4::class)
class AndroidAudioPlaybackInstrumentedTest {
    @get:Rule
    val compose = createComposeRule()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Test
    fun realMediaServiceSupportsPausedStartSeekRateAndTrackSelection() {
        val context = instrumentation.targetContext
        val app = context.applicationContext as ErmaoLibraryApplication
        // Never replace an existing user session to make a test run.
        assertFalse("An existing audio session must remain untouched", app.audioPlaybackRuntime.snapshot.value.hasSession)
        compose.setContent { Text("Release audio engine fixture") }
        lateinit var activity: Activity
        instrumentation.runOnMainSync {
            activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED).single()
            activity.setShowWhenLocked(true)
            activity.setTurnScreenOn(true)
            activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        val source = File.createTempFile("release-audio-engine-", ".wav", context.cacheDir)
        writeSilentPcm(source)
        val originalHash = hash(source)
        var runtime: AndroidAudioPlaybackRuntime? = null
        try {
            lateinit var player: AndroidAudioPlaybackRuntime
            instrumentation.runOnMainSync {
                player = AndroidAudioPlaybackRuntime(context)
                runtime = player
                player.launch(
                    AndroidAudioLaunchIntent(
                        namespace = AndroidAudioNamespace("release-audio-server", "release-audio-user", 1),
                        bookId = "release-audio-book",
                        resourceId = "release-audio-resource",
                        title = "Release PCM fixture",
                        tracks = listOf("first", "second").map { assetId ->
                            AndroidAudioTrack(
                                assetId = assetId, title = assetId,
                                sourceUri = source.toURI().toString(), mimeType = "audio/wav",
                            )
                        },
                        assetId = "first",
                        positionMillis = 1_000,
                        autoplay = false,
                    ),
                )
            }
            awaitPlayer(player) {
                it.durationMillis > 0 && it.phase in setOf(AndroidAudioPhase.Ready, AndroidAudioPhase.Paused)
            }
            assertEquals(12_000L, player.snapshot.value.durationMillis)
            val pausedStart = player.snapshot.value.positionMillis
            Thread.sleep(500)
            assertTrue("Paused launch must not advance", abs(player.snapshot.value.positionMillis - pausedStart) <= 100)

            instrumentation.runOnMainSync { player.play() }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Playing && it.positionMillis >= pausedStart + 500 }
            instrumentation.runOnMainSync { player.pause() }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Paused }
            val pausedPosition = player.snapshot.value.positionMillis
            Thread.sleep(500)
            assertTrue("Pause must stop the real clock", abs(player.snapshot.value.positionMillis - pausedPosition) <= 100)

            instrumentation.runOnMainSync { player.seekTo(7_000) }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Paused && abs(it.positionMillis - 7_000) <= 2_000 }
            instrumentation.runOnMainSync { player.setPlaybackRate(1.5f) }
            awaitPlayer(player) { it.playbackRate == 1.5f }
            instrumentation.runOnMainSync { player.selectAsset("second") }
            awaitPlayer(player) {
                it.assetId == "second" && it.positionMillis < 2_000 && it.phase == AndroidAudioPhase.Paused
            }
            instrumentation.runOnMainSync { player.play() }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Playing && it.positionMillis >= 500 }
            val foregroundPosition = player.snapshot.value.positionMillis
            instrumentation.runOnMainSync { assertTrue(activity.moveTaskToBack(true)) }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Playing && it.positionMillis >= foregroundPosition + 500 }
            assertEquals("Decoder must leave the original fixture unchanged", originalHash, hash(source))
            instrumentation.runOnMainSync { player.stop() }
            assertFalse(player.snapshot.value.hasSession)
        } finally {
            instrumentation.runOnMainSync { runtime?.close() }
            assertTrue("Remove only this test's PCM file", source.delete())
        }
    }

    private fun awaitPlayer(
        player: AndroidAudioPlaybackRuntime,
        condition: (com.ermao.library.features.audio.model.AndroidAudioPlaybackSnapshot) -> Boolean,
    ) {
        try {
            compose.waitUntil(10_000) {
                val snapshot = player.snapshot.value
                check(snapshot.phase != AndroidAudioPhase.Error) { "Media3 playback failed: ${snapshot.error?.code}" }
                condition(snapshot)
            }
        } catch (error: ComposeTimeoutException) {
            val state = player.snapshot.value
            throw AssertionError("Audio condition timed out: phase=${state.phase}, position=${state.positionMillis}, duration=${state.durationMillis}", error)
        }
    }

    private fun writeSilentPcm(destination: File) {
        val sampleRate = 16_000
        val pcmBytes = sampleRate * 2 * 12
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray(Charsets.US_ASCII)); putInt(36 + pcmBytes)
            put("WAVEfmt ".toByteArray(Charsets.US_ASCII)); putInt(16)
            putShort(1); putShort(1); putInt(sampleRate); putInt(sampleRate * 2)
            putShort(2); putShort(16)
            put("data".toByteArray(Charsets.US_ASCII)); putInt(pcmBytes)
        }
        destination.outputStream().use { output ->
            output.write(header.array())
            output.write(ByteArray(pcmBytes))
        }
    }

    private fun hash(source: File): List<Byte> =
        MessageDigest.getInstance("SHA-256").digest(source.readBytes()).toList()
}
