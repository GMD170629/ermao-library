package com.ermao.library.features.audio

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.database.DatabaseErrorHandler
import android.database.sqlite.SQLiteDatabase
import android.os.SystemClock
import android.util.Log
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
import com.ermao.library.features.reader.infrastructure.AndroidReaderDeviceIdentity
import com.ermao.library.features.reader.infrastructure.AndroidReaderV5Database
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.UUID
import kotlin.math.abs
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Real MediaController -> app MediaSessionService -> Media3 decoder/device clock. */
@RunWith(AndroidJUnit4::class)
class AndroidAudioPlaybackInstrumentedTest {
    @get:Rule
    val compose = createComposeRule()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Test
    fun continuousPlaybackPersistsLocatorWithinFiveSecondsAndRestoresPausedPosition() {
        val context = instrumentation.targetContext
        val app = context.applicationContext as ErmaoLibraryApplication
        assertFalse("An existing audio session must remain untouched", app.audioPlaybackRuntime.snapshot.value.hasSession)
        prepareFixtureActivity()
        val fixtureId = "rg04-audio-${UUID.randomUUID()}"
        val directory = File(context.filesDir, fixtureId).apply { check(mkdir()) }
        val isolatedContext = AudioPersistenceContext(context, directory)
        val source = File(directory, "continuous.wav")
        writeSilentPcm(source, durationSeconds = 24)
        val originalHash = hash(source)
        val report = File(directory, "durability-evidence.log")
        fun record(message: String) {
            report.appendText("$message\n")
            Log.i("RG04Audio", message)
            println("RG04Audio: $message")
        }
        record("fixtureDirectory=${directory.absolutePath}")
        // No server is started: failed uploads must leave the real v5 outbox durable.
        val parsed = ServerBaseUrl.parse("http://127.0.0.1:18741")
        check(parsed is ServerBaseUrlParseResult.Valid)
        val profile = ServerProfile(fixtureId, "RG04 offline fixture", parsed.baseUrl, fixtureId, false, TlsMode.SystemTrust)
        val namespace = AndroidAudioNamespace(fixtureId, fixtureId, 1)
        val identity = ReaderLocalProgressIdentity(
            namespace = ReaderSyncNamespace(fixtureId, fixtureId, 1),
            clientId = AndroidReaderDeviceIdentity(isolatedContext).stableDeviceId(),
            bookId = fixtureId,
            resourceId = fixtureId,
        )
        val apiPath = "/api/assets/$fixtureId"
        fun openPlayer(positionMillis: Long?): AndroidAudioPlaybackRuntime {
            lateinit var player: AndroidAudioPlaybackRuntime
            instrumentation.runOnMainSync {
                player = AndroidAudioPlaybackRuntime(isolatedContext)
                player.launchLocal(
                    namespace = namespace, bookId = fixtureId, resourceId = fixtureId,
                    title = "RG04 continuous PCM", author = null, assetId = fixtureId,
                    localFile = source, mimeType = "audio/wav", sourceApiPath = apiPath,
                    profile = profile, positionMillis = positionMillis,
                )
            }
            return player
        }
        fun readDurablePosition(): ReaderPositionLocalState? = runBlocking {
            // Each observation opens a separate production database connection and closes it.
            val database = AndroidReaderV5Database(isolatedContext, identity)
            try {
                database.loadPosition(fixtureId)
            } finally {
                database.close()
            }
        }
        var runtime: AndroidAudioPlaybackRuntime? = null
        try {
            assertEquals(null, readDurablePosition())
            val player = openPlayer(0L).also { runtime = it }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Playing && it.durationMillis > 0 }
            val started = SystemClock.elapsedRealtime()
            var previousLocatorTime = 0L
            var previousCapturedAt = 0L
            for (checkpoint in listOf(5_000L, 10_000L)) {
                var observed: ReaderPositionLocalState? = null
                var observedAt = 0L
                while (SystemClock.elapsedRealtime() - started < checkpoint) {
                    val candidate = readDurablePosition()
                    val elapsed = SystemClock.elapsedRealtime() - started
                    if (candidate != null && elapsed <= checkpoint) {
                        observed = candidate
                        observedAt = elapsed
                    }
                    Thread.sleep(25)
                }
                val durable = requireNotNull(observed) { "RG04: no durable Locator by ${checkpoint}ms" }
                val locatorTime = locatorTimeMillis(durable)
                assertEquals(AndroidAudioPhase.Playing, player.snapshot.value.phase)
                assertTrue("Each 5s window needs a newer persisted Locator", locatorTime > previousLocatorTime)
                assertTrue("Each 5s window needs a new capture", durable.capturedAtEpochMillis > previousCapturedAt)
                assertTrue("Durable position must be at most 5s behind the actual player",
                    abs(player.snapshot.value.positionMillis - locatorTime) <= 5_000L)
                assertEquals(apiPath, Json.parseToJsonElement(durable.position.locator.canonicalJson)
                    .jsonObject.getValue("href").jsonPrimitive.content)
                record("checkpoint=$checkpoint observedAt=$observedAt capturedAt=${durable.capturedAtEpochMillis} " +
                    "player=${player.snapshot.value.positionMillis} locator=$locatorTime " +
                    "report=${durable.position.locator.canonicalJson}")
                previousLocatorTime = locatorTime
                previousCapturedAt = durable.capturedAtEpochMillis
            }
            val pauseRequestedAt = System.currentTimeMillis()
            instrumentation.runOnMainSync { player.pause() }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Paused }
            val pausedPosition = player.snapshot.value.positionMillis
            compose.waitUntil(2_000) {
                readDurablePosition()?.let {
                    it.capturedAtEpochMillis >= pauseRequestedAt &&
                        abs(locatorTimeMillis(it) - pausedPosition) <= 100L
                } == true
            }
            val paused = requireNotNull(readDurablePosition())
            runBlocking {
                val database = AndroidReaderV5Database(isolatedContext, identity)
                try {
                    assertEquals("Offline local position and pending upload must agree",
                        paused.position, database.loadPositionSyncState().pending?.position)
                } finally {
                    database.close()
                }
            }
            record("pausedPlayer=$pausedPosition pausedLocator=${locatorTimeMillis(paused)}")
            instrumentation.runOnMainSync { player.close() }
            runtime = null
            // No supplied position: the real launchLocal restore owner must read its pending v5 report.
            val reopened = openPlayer(null).also { runtime = it }
            awaitPlayer(reopened) { it.phase == AndroidAudioPhase.Playing && it.durationMillis > 0 }
            instrumentation.runOnMainSync { reopened.pause() }
            awaitPlayer(reopened) { it.phase == AndroidAudioPhase.Paused }
            val restoredPosition = reopened.snapshot.value.positionMillis
            assertTrue("Reopened pause must restore the persisted Locator within 2s",
                abs(restoredPosition - locatorTimeMillis(paused)) <= 2_000L)
            assertTrue("Reopened pause must remain within 2s of the original pause",
                abs(restoredPosition - pausedPosition) <= 2_000L)
            assertEquals(originalHash, hash(source))
            record("reopenedPaused=$restoredPosition restoreError=${abs(restoredPosition - pausedPosition)} result=PASS")
        } finally {
            instrumentation.runOnMainSync { runtime?.close() }
            // Keep only this uniquely isolated fixture directory for canonical evidence collection.
        }
    }

    @Test
    fun realMediaServiceSupportsPausedStartSeekRateAndTrackSelection() {
        val context = instrumentation.targetContext
        val app = context.applicationContext as ErmaoLibraryApplication
        // Never replace an existing user session to make a test run.
        assertFalse("An existing audio session must remain untouched", app.audioPlaybackRuntime.snapshot.value.hasSession)
        val activity = prepareFixtureActivity()
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

    private fun prepareFixtureActivity(): Activity {
        compose.setContent { Text("Release audio engine fixture") }
        lateinit var activity: Activity
        instrumentation.runOnMainSync {
            activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED).single()
            activity.setShowWhenLocked(true)
            activity.setTurnScreenOn(true)
            activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        return activity
    }

    private fun locatorTimeMillis(position: ReaderPositionLocalState): Long =
        (Json.parseToJsonElement(position.position.locator.canonicalJson).jsonObject
            .getValue("locations").jsonObject.getValue("time").jsonPrimitive.double * 1000).toLong()

    private fun writeSilentPcm(destination: File, durationSeconds: Int = 12) {
        val sampleRate = 16_000
        val pcmBytes = sampleRate * 2 * durationSeconds
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

/** Path adapter only: SQLite schema, transactions and codecs stay with the production owner. */
private class AudioPersistenceContext(base: Context, private val directory: File) : ContextWrapper(base) {
    override fun getApplicationContext(): Context = this

    override fun getDatabasePath(name: String): File = File(directory, name).also {
        check(it.canonicalFile.parentFile == directory.canonicalFile)
    }

    override fun openOrCreateDatabase(name: String, mode: Int, factory: SQLiteDatabase.CursorFactory?): SQLiteDatabase =
        baseContext.openOrCreateDatabase(getDatabasePath(name).absolutePath, mode, factory)

    override fun openOrCreateDatabase(
        name: String, mode: Int, factory: SQLiteDatabase.CursorFactory?, errorHandler: DatabaseErrorHandler?,
    ): SQLiteDatabase = baseContext.openOrCreateDatabase(getDatabasePath(name).absolutePath, mode, factory, errorHandler)
}
