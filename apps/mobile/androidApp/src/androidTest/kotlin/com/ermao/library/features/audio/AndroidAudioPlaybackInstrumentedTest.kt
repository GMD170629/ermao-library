package com.ermao.library.features.audio

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.database.DatabaseErrorHandler
import android.database.sqlite.SQLiteDatabase
import android.os.Looper
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
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
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
    fun pausingActiveResourceDuringReplacementRestoreKeepsWriterIdentity() {
        val context = instrumentation.targetContext
        val app = context.applicationContext as ErmaoLibraryApplication
        assertFalse("An existing audio session must remain untouched", app.audioPlaybackRuntime.snapshot.value.hasSession)
        prepareFixtureActivity()
        val fixtureId = "rg04-writer-${UUID.randomUUID()}"
        val directory = File(context.filesDir, fixtureId).apply { check(mkdir()) }
        check(directory.canonicalFile.parentFile == context.filesDir.canonicalFile)
        val report = File(directory, "writer-identity-evidence.log")
        fun record(message: String) {
            report.appendText("$message\n")
            Log.i("RG04WriterIdentity", message)
            println("RG04WriterIdentity: $message")
        }
        val gate = AudioRestoreOpenGate()
        val isolated = AudioPersistenceContext(context, directory, beforeOpen = gate::beforeOpen)
        val sourceA = File(directory, "a.wav").also { writeSilentPcm(it, durationSeconds = 24) }
        // Deliberately invalid from creation; never corrupt a readable source to force an outcome.
        val sourceB = File(directory, "b.wav").apply { writeText("RG04 invalid PCM fixture") }
        val sourceAHash = hash(sourceA)
        val sourceBHash = hash(sourceB)
        val parsed = ServerBaseUrl.parse("http://127.0.0.1:18741")
        check(parsed is ServerBaseUrlParseResult.Valid)
        val profile = ServerProfile(fixtureId, "RG04 writer fixture", parsed.baseUrl, fixtureId, false, TlsMode.SystemTrust)
        val namespace = AndroidAudioNamespace(fixtureId, fixtureId, 1)
        val clientId = AndroidReaderDeviceIdentity(isolated).stableDeviceId()
        val identityA = ReaderLocalProgressIdentity(
            ReaderSyncNamespace(fixtureId, fixtureId, 1), clientId, "$fixtureId-book-a", "$fixtureId-a",
        )
        val identityB = ReaderLocalProgressIdentity(
            ReaderSyncNamespace(fixtureId, fixtureId, 1), clientId, "$fixtureId-book-b", "$fixtureId-b",
        )
        val assetA = "$fixtureId-asset-a"
        val assetB = "$fixtureId-asset-b"
        val hrefA = "/api/assets/$assetA"
        val hrefB = "/api/assets/$assetB"
        fun readPosition(identity: ReaderLocalProgressIdentity): ReaderPositionLocalState? = runBlocking {
            val database = AndroidReaderV5Database(isolated, identity)
            try {
                database.loadPosition(identity.resourceId)
            } finally {
                database.close()
            }
        }
        fun href(position: ReaderPositionLocalState): String =
            Json.parseToJsonElement(position.position.locator.canonicalJson).jsonObject
                .getValue("href").jsonPrimitive.content
        var runtime: AndroidAudioPlaybackRuntime? = null
        try {
            assertEquals(null, readPosition(identityA))
            assertEquals(null, readPosition(identityB))
            lateinit var player: AndroidAudioPlaybackRuntime
            instrumentation.runOnMainSync {
                player = AndroidAudioPlaybackRuntime(isolated)
                runtime = player
                player.launchLocal(
                    namespace = namespace, bookId = identityA.bookId, resourceId = identityA.resourceId,
                    title = "RG04 writer A", author = null, assetId = assetA, localFile = sourceA,
                    mimeType = "audio/wav", sourceApiPath = hrefA, profile = profile, positionMillis = 0,
                )
            }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Playing && it.positionMillis >= 2_000 }
            gate.armed.set(true)
            instrumentation.runOnMainSync {
                player.launchLocal(
                    namespace = namespace, bookId = identityB.bookId, resourceId = identityB.resourceId,
                    title = "RG04 writer B", author = null, assetId = assetB, localFile = sourceB,
                    mimeType = "audio/wav", sourceApiPath = hrefB, profile = profile, positionMillis = null,
                )
            }
            assertTrue("RG04_POS08_B_RESTORE_GATE_NOT_ENTERED", gate.entered.await(5, TimeUnit.SECONDS))
            assertFalse("RG04_POS08_RESTORE_GATE_ON_MAIN", gate.onMain.get())
            val active = player.snapshot.value
            assertEquals(identityA.resourceId, active.resourceId)
            assertEquals(assetA, active.assetId)
            assertEquals(AndroidAudioPhase.Playing, active.phase)
            record("fixtureId=$fixtureId gate=B_restore_io activeResource=${active.resourceId} " +
                "activeAsset=${active.assetId} phase=${active.phase} position=${active.positionMillis}")
            val pauseRequestedAt = System.currentTimeMillis()
            instrumentation.runOnMainSync { player.pause() }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Paused && it.resourceId == identityA.resourceId }
            val paused = player.snapshot.value
            assertEquals(assetA, paused.assetId)
            assertFalse("RG04_POS08_RESTORE_GATE_TIMEOUT", gate.timedOut.get())
            record("pausedResource=${paused.resourceId} pausedAsset=${paused.assetId} " +
                "pausedPosition=${paused.positionMillis} pausedPhase=${paused.phase}")
            gate.release.countDown()

            var wrongB: ReaderPositionLocalState? = null
            val errorDeadline = SystemClock.elapsedRealtime() + 10_000
            while (SystemClock.elapsedRealtime() < errorDeadline) {
                val observedB = readPosition(identityB)
                if (observedB != null && href(observedB) == hrefA && wrongB == null) {
                    wrongB = observedB
                    record("wrongResource=${observedB.resourceId} locatorAsset=$assetA " +
                        "position=${locatorTimeMillis(observedB)} capturedAt=${observedB.capturedAtEpochMillis}")
                }
                val current = player.snapshot.value
                if (current.resourceId == identityB.resourceId && current.phase == AndroidAudioPhase.Error) break
                Thread.sleep(25)
            }
            val failedB = player.snapshot.value
            record("decoderResource=${failedB.resourceId} decoderAsset=${failedB.assetId} " +
                "decoderPhase=${failedB.phase} decoderCode=${failedB.error?.code}")
            assertFalse("RG04_POS08_RESTORE_GATE_TIMEOUT", gate.timedOut.get())
            assertEquals("RG04_POS08_BAD_B_DID_NOT_REACH_ENGINE", identityB.resourceId, failedB.resourceId)
            assertEquals("RG04_POS08_BAD_B_DID_NOT_REACH_ENGINE", assetB, failedB.assetId)
            assertEquals("RG04_POS08_BAD_B_DID_NOT_FAIL", AndroidAudioPhase.Error, failedB.phase)
            assertTrue("RG04_POS08_BAD_B_ERROR_CODE_REQUIRED", failedB.error != null)
            val savedA = readPosition(identityA)
            val savedB = readPosition(identityB)
            val aPauseStored = savedA != null && href(savedA) == hrefA &&
                savedA.capturedAtEpochMillis >= pauseRequestedAt &&
                abs(locatorTimeMillis(savedA) - paused.positionMillis) <= 100
            val bContainsA = wrongB != null || savedB?.let { href(it) == hrefA } == true
            record("aPauseStored=$aPauseStored aPosition=${savedA?.let(::locatorTimeMillis)} " +
                "aCapturedAt=${savedA?.capturedAtEpochMillis} bContainsA=$bContainsA " +
                "bPosition=${savedB?.let(::locatorTimeMillis)} bCapturedAt=${savedB?.capturedAtEpochMillis}")
            assertEquals(sourceAHash, hash(sourceA))
            assertEquals(sourceBHash, hash(sourceB))
            assertTrue("RG04_POS08_WRITER_IDENTITY bContainsA=$bContainsA aPauseStored=$aPauseStored", !bContainsA && aPauseStored)
        } finally {
            gate.close()
            instrumentation.runOnMainSync { runtime?.close() }
            // Preserve only this test's unique fixture directory for evidence.
        }
    }

    @Test
    fun stoppingDuringReplacementRestoreDoesNotRestartPlayback() {
        val context = instrumentation.targetContext
        val app = context.applicationContext as ErmaoLibraryApplication
        assertFalse("An existing audio session must remain untouched", app.audioPlaybackRuntime.snapshot.value.hasSession)
        prepareFixtureActivity()
        val fixtureId = "rg04-stop-${UUID.randomUUID()}"
        val directory = File(context.filesDir, fixtureId).apply { check(mkdir()) }
        check(directory.canonicalFile.parentFile == context.filesDir.canonicalFile)
        val report = File(directory, "stop-restore-evidence.log")
        fun record(message: String) {
            report.appendText("$message\n")
            Log.i("RG04StopRestore", message)
            println("RG04StopRestore: $message")
        }
        val gate = AudioRestoreOpenGate()
        val isolated = AudioPersistenceContext(context, directory, beforeOpen = gate::beforeOpen)
        val sourceA = File(directory, "a.wav").also { writeSilentPcm(it, durationSeconds = 24) }
        val sourceB = File(directory, "b.wav").also { writeSilentPcm(it, durationSeconds = 24) }
        val sourceAHash = hash(sourceA)
        val sourceBHash = hash(sourceB)
        val parsed = ServerBaseUrl.parse("http://127.0.0.1:18741")
        check(parsed is ServerBaseUrlParseResult.Valid)
        val profile = ServerProfile(fixtureId, "RG04 stop fixture", parsed.baseUrl, fixtureId, false, TlsMode.SystemTrust)
        val namespace = AndroidAudioNamespace(fixtureId, fixtureId, 1)
        val resourceA = "$fixtureId-a"
        val resourceB = "$fixtureId-b"
        val assetA = "$fixtureId-asset-a"
        val assetB = "$fixtureId-asset-b"
        var runtime: AndroidAudioPlaybackRuntime? = null
        try {
            lateinit var player: AndroidAudioPlaybackRuntime
            instrumentation.runOnMainSync {
                player = AndroidAudioPlaybackRuntime(isolated)
                runtime = player
                player.launchLocal(
                    namespace = namespace, bookId = "$fixtureId-book-a", resourceId = resourceA,
                    title = "RG04 stop A", author = null, assetId = assetA, localFile = sourceA,
                    mimeType = "audio/wav", sourceApiPath = "/api/assets/$assetA", profile = profile, positionMillis = 0,
                )
            }
            awaitPlayer(player) { it.phase == AndroidAudioPhase.Playing && it.positionMillis >= 2_000 }
            gate.armed.set(true)
            instrumentation.runOnMainSync {
                player.launchLocal(
                    namespace = namespace, bookId = "$fixtureId-book-b", resourceId = resourceB,
                    title = "RG04 stop B", author = null, assetId = assetB, localFile = sourceB,
                    mimeType = "audio/wav", sourceApiPath = "/api/assets/$assetB", profile = profile, positionMillis = null,
                )
            }
            assertTrue("RG04_POS08_B_RESTORE_GATE_NOT_ENTERED", gate.entered.await(5, TimeUnit.SECONDS))
            assertFalse("RG04_POS08_RESTORE_GATE_ON_MAIN", gate.onMain.get())
            val active = player.snapshot.value
            assertEquals(resourceA, active.resourceId)
            assertEquals(assetA, active.assetId)
            assertEquals(AndroidAudioPhase.Playing, active.phase)
            record("fixtureId=$fixtureId gate=B_restore_io activeResource=${active.resourceId} " +
                "activeAsset=${active.assetId} phase=${active.phase} position=${active.positionMillis}")
            instrumentation.runOnMainSync { player.stop() }
            val stopped = player.snapshot.value
            assertEquals("RG04_POS08_STOP_NOT_IDLE", AndroidAudioPhase.Idle, stopped.phase)
            assertFalse("RG04_POS08_STOP_SESSION_REMAINED", stopped.hasSession)
            assertTrue("RG04_POS08_STOP_QUEUE_REMAINED", player.currentTracks().isEmpty())
            assertFalse("RG04_POS08_RESTORE_GATE_TIMEOUT", gate.timedOut.get())
            record("beforeRelease phase=${stopped.phase} hasSession=${stopped.hasSession} tracks=0")
            val releasedAt = SystemClock.elapsedRealtime()
            gate.release.countDown()
            // Observe the same bounded 10s engine window used by awaitPlayer; Idle alone at
            // release would pass before the suspended replacement had a chance to resume.
            val observationDeadline = releasedAt + 10_000
            var restarted: com.ermao.library.features.audio.model.AndroidAudioPlaybackSnapshot? = null
            var restartedAtEngine: com.ermao.library.features.audio.model.AndroidAudioPlaybackSnapshot? = null
            var gateExitRecorded = false
            while (SystemClock.elapsedRealtime() < observationDeadline) {
                if (!gateExitRecorded && gate.exited.count == 0L) {
                    record("gateHookExited=true elapsed=${SystemClock.elapsedRealtime() - releasedAt}")
                    gateExitRecorded = true
                }
                val current = player.snapshot.value
                if (restarted == null && (current.phase != AndroidAudioPhase.Idle || current.hasSession)) {
                    restarted = current
                }
                if (current.resourceId == resourceB &&
                    (current.phase == AndroidAudioPhase.Playing || current.phase == AndroidAudioPhase.Error)) {
                    restartedAtEngine = current
                    break
                }
                Thread.sleep(25)
            }
            val observed = restartedAtEngine ?: player.snapshot.value
            record("afterRelease elapsed=${SystemClock.elapsedRealtime() - releasedAt} " +
                "gateHookExited=${gate.exited.count == 0L} firstRestartPhase=${restarted?.phase} " +
                "phase=${observed.phase} errorCode=${observed.error?.code} hasSession=${observed.hasSession} " +
                "resource=${observed.resourceId} asset=${observed.assetId} tracks=${player.currentTracks().size}")
            assertEquals("RG04_POS08_RESTORE_GATE_NOT_EXITED", 0L, gate.exited.count)
            assertFalse("RG04_POS08_RESTORE_GATE_TIMEOUT", gate.timedOut.get())
            assertEquals(sourceAHash, hash(sourceA))
            assertEquals(sourceBHash, hash(sourceB))
            if (restarted != null) {
                assertEquals("RG04_POS08_UNEXPECTED_RESTART_RESOURCE", resourceB, restarted.resourceId)
                assertEquals("RG04_POS08_UNEXPECTED_RESTART_ASSET", assetB, restarted.assetId)
                assertTrue("RG04_POS08_RESTART_DID_NOT_REACH_ENGINE phase=${observed.phase}", restartedAtEngine != null)
            }
            assertTrue("RG04_POS08_STOP_RESTARTED phase=${observed.phase} hasSession=${observed.hasSession}",
                restarted == null && observed.phase == AndroidAudioPhase.Idle && !observed.hasSession &&
                    player.currentTracks().isEmpty())
        } finally {
            gate.close()
            instrumentation.runOnMainSync { runtime?.close() }
            // Preserve only this test's unique fixture directory for evidence.
        }
    }

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

/** One-shot SQLite-open gate shared only by these two replacement-restore regressions. */
private class AudioRestoreOpenGate {
    val armed = AtomicBoolean(false)
    val entered = CountDownLatch(1)
    val release = CountDownLatch(1)
    val exited = CountDownLatch(1)
    val timedOut = AtomicBoolean(false)
    val onMain = AtomicBoolean(false)

    fun beforeOpen() {
        if (armed.compareAndSet(true, false)) {
            onMain.set(Looper.myLooper() == Looper.getMainLooper())
            entered.countDown()
            check(!onMain.get()) { "RG04_POS08_RESTORE_GATE_ON_MAIN" }
            val released = release.await(10, TimeUnit.SECONDS)
            timedOut.set(!released)
            check(released) { "RG04_POS08_RESTORE_GATE_TIMEOUT" }
            exited.countDown()
        }
    }

    fun close() {
        armed.set(false)
        release.countDown()
    }
}

/** Path adapter only: SQLite schema, transactions and codecs stay with the production owner. */
private class AudioPersistenceContext(
    base: Context,
    private val directory: File,
    private val beforeOpen: (() -> Unit)? = null,
) : ContextWrapper(base) {
    override fun getApplicationContext(): Context = this

    override fun getDatabasePath(name: String): File = File(directory, name).also {
        beforeOpen?.invoke()
        check(it.canonicalFile.parentFile == directory.canonicalFile)
    }

    override fun openOrCreateDatabase(name: String, mode: Int, factory: SQLiteDatabase.CursorFactory?): SQLiteDatabase =
        baseContext.openOrCreateDatabase(getDatabasePath(name).absolutePath, mode, factory)

    override fun openOrCreateDatabase(
        name: String, mode: Int, factory: SQLiteDatabase.CursorFactory?, errorHandler: DatabaseErrorHandler?,
    ): SQLiteDatabase = baseContext.openOrCreateDatabase(getDatabasePath(name).absolutePath, mode, factory, errorHandler)
}
