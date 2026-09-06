package com.ermao.library.release.live

import android.os.SystemClock
import android.util.Log
import android.view.WindowManager
import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.features.audio.AudioPlaybackPhase
import com.ermao.library.features.audio.AudioPlaybackRuntime
import com.ermao.library.features.audio.AudioPlaybackSnapshot
import com.ermao.library.features.reader.infrastructure.AndroidReaderDeviceIdentity
import com.ermao.library.features.reader.infrastructure.AndroidReaderV5Database
import com.ermao.library.shared.createAndroidAudioMediaTransport
import com.ermao.library.shared.createAndroidMobileRuntime
import com.ermao.library.shared.createAndroidReaderBootstrapGateway
import com.ermao.library.shared.createAndroidReaderPositionSyncPort
import com.ermao.library.shared.modules.auth.RuntimeOperationResult
import com.ermao.library.shared.modules.auth.application.InMemoryVerifiedSessionRepository
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderPositionDurableState
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderPositionServerPort
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.application.ReaderPositionQueryResult
import com.ermao.library.shared.modules.servers.application.InMemoryServerProfileRepository
import java.io.File
import kotlin.math.abs
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
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

/** Separate opt-in gate. Every input and online assertion is mandatory. */
@RunWith(AndroidJUnit4::class)
class AndroidAudioOnlineConfirmationInstrumentedTest {
    @get:Rule
    val compose = createComposeRule()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Test
    fun realHttpConfirmsPlaybackAtFiveAndTenSecondsAndRestoresAfterReopen() = withOnlineAudioFixture {
        assertTrue("RG04_NEW_SERVER_PROGRESS_REQUIRED", database.get(SystemClock.elapsedRealtime() + 15_000) == null)
        record("ISOLATION_PASS")
        prepareActivity()
        val player = openPlayer(autoplay = true)
        val pause = confirmPlaybackAndPause(player)
        val pausedSnapshot = pause.engine
        val pausedPosition = pausedSnapshot.positionMillis
        val paused = pause.confirmed
        closePlayerAndObserve()
        val reopened = openPlayer(autoplay = false)
        val restoredSnapshot = awaitRestoredPlayer(reopened, fixture)
        val restored = restoredSnapshot.positionMillis
        val restoreObservation = "restored=$restored phase=${restoredSnapshot.phase} " +
            "duration=${restoredSnapshot.durationMillis} paused=$pausedPosition " +
            "pausedPhase=${pausedSnapshot.phase} pausedDuration=${pausedSnapshot.durationMillis} " +
            "confirmed=${locatorMillis(paused)} confirmedRevision=${paused.revision} " +
            "confirmedDuration=${paused.position.presentation.playback?.durationMillis}"
        record("REOPEN_OBSERVATION $restoreObservation", restored, paused.revision)
        assertTrue("RG04_REOPEN_RESTORE_TOLERANCE $restoreObservation", abs(restored - pausedPosition) <= 2_000)
        assertTrue("RG04_REOPEN_CONFIRMED_LOCATOR_TOLERANCE $restoreObservation",
            abs(restored - locatorMillis(paused)) <= 2_000)
        val reopenedConfirmation = database.awaitConfirmed(SystemClock.elapsedRealtime() + 5_000) { local, sync ->
            abs(locatorMillis(local) - pausedPosition) <= 2_000 && sync.confirmedRevision >= paused.revision
        }
        record("REOPEN_PASS", restored, reopenedConfirmation.revision)
        assertAppSessionUnchanged()
        record("PASS", restored, reopenedConfirmation.revision)
    }

    @Test
    fun restoresWebMp3ProgressAndConfirmsPlaybackForWebHandoff() = withOnlineAudioFixture {
        assertEquals("RG04_WEB_HANDOFF_MP3_REQUIRED", "audio/mpeg", fixture.mimeType)
        val web = database.get(SystemClock.elapsedRealtime() + 15_000)
            ?: throw AssertionError("RG04_WEB_PROGRESS_REQUIRED")
        database.assertFixtureSnapshot(web)
        assertTrue("RG04_WEB_PROGRESS_CLIENT_REQUIRED", web.clientId != identity.clientId)
        assertTrue("RG04_WEB_PROGRESS_POSITION_REQUIRED", locatorMillis(web) > 0)
        record("ISOLATION_PASS")
        record("WEB_PROGRESS_OBSERVED clientId=${web.clientId} capturedAt=${web.capturedAtEpochMillis}",
            locatorMillis(web), web.revision)
        prepareActivity()
        val player = openPlayer(autoplay = false)
        val restored = awaitRestoredPlayer(player, fixture)
        val restoreObservation = "restored=${restored.positionMillis} phase=${restored.phase} " +
            "duration=${restored.durationMillis} webPosition=${locatorMillis(web)} " +
            "webRevision=${web.revision} webClientId=${web.clientId}"
        record("WEB_RESTORE_OBSERVATION $restoreObservation", restored.positionMillis, web.revision)
        assertTrue("RG04_WEB_RESTORE_TOLERANCE $restoreObservation",
            abs(restored.positionMillis - locatorMillis(web)) <= 2_000)
        record("WEB_RESTORE_PASS", restored.positionMillis, web.revision)
        instrumentation.runOnMainSync { player.play() }
        val pause = confirmPlaybackAndPause(player, initialConfirmation = web)
        record("ANDROID_HANDOFF_CONFIRMED clientId=${pause.confirmed.clientId} " +
            "capturedAt=${pause.confirmed.capturedAtEpochMillis}",
            locatorMillis(pause.confirmed), pause.confirmed.revision)
        closePlayerAndObserve()
        assertAppSessionUnchanged()
        // This JUnit result covers the Android leg; the primary verifies the final Web reopen.
        record("ANDROID_HANDOFF_PASS", locatorMillis(pause.confirmed), pause.confirmed.revision)
    }

    /** Both gates use the same real login, isolated storage and production playback owners. */
    private fun withOnlineAudioFixture(test: OnlineAudioFixture.() -> Unit) {
        val context = instrumentation.targetContext
        val privateFixture = PrivateAudioFixture.consume(
            context, InstrumentationRegistry.getArguments().getString("releaseFixture"),
        )
        val fixture = privateFixture.value
        val isolated = ReleaseAudioContext(context, privateFixture.directory)
        val app = context.applicationContext as ErmaoLibraryApplication
        assertFalse("RG04_EXISTING_APP_AUDIO_SESSION", app.audioPlaybackRuntime.snapshot.value.hasSession)
        assertTrue("RG04_FRESH_COOKIE_PREFS_REQUIRED",
            isolated.getSharedPreferences("ermao_session_cookies", 0).all.isEmpty())
        assertTrue("RG04_FRESH_DEVICE_PREFS_REQUIRED",
            isolated.getSharedPreferences("reader-device-identity", 0).all.isEmpty())
        val profiles = InMemoryServerProfileRepository()
        val sessions = InMemoryVerifiedSessionRepository()
        val auth = createAndroidMobileRuntime(isolated, profiles, sessions)
        var online: OnlineAudioFixture? = null
        try {
            val login = runBlocking {
                withTimeout(45_000) { auth.loginToServer(fixture.baseUrl, fixture.email, fixture.password) }
            }
            assertTrue("RG04_LOGIN_FAILED", login is RuntimeOperationResult.Success)
            val session = auth.currentSession as? AppSession.Authenticated
                ?: throw AssertionError("RG04_AUTHENTICATED_SESSION_REQUIRED")
            assertTrue("RG04_SINGLE_TEMPORARY_PROFILE", runBlocking { profiles.profiles().size == 1 })
            val namespace = ReaderSyncNamespace(
                session.profile.serverIdentity, session.identity.userId, session.authorization.authorizationVersion,
            )
            val identity = ReaderLocalProgressIdentity(
                namespace, AndroidReaderDeviceIdentity(isolated).stableDeviceId(), fixture.bookId, fixture.resourceId,
            )
            val target = ReaderProgressSyncTarget(namespace, fixture.bookId, fixture.resourceId, ReaderFormat.Audio)
            val port = createAndroidReaderPositionSyncPort(isolated, session.profile)
            val database = PositionObservations(isolated, identity, target, port, fixture)
            val empty = database.read()
            assertTrue("RG04_FRESH_DATABASE_REQUIRED", empty?.local == null && empty?.sync == ReaderPositionDurableState())
            online = OnlineAudioFixture(fixture, privateFixture.directory, isolated, app, session, identity, database)
            online.test()
        } finally {
            try {
                instrumentation.runOnMainSync { online?.runtime?.close() }
            } finally {
                auth.close()
            }
        }
    }

    private inner class OnlineAudioFixture(
        val fixture: ReleaseAudioFixture,
        directory: File,
        private val isolated: ReleaseAudioContext,
        private val app: ErmaoLibraryApplication,
        private val session: AppSession.Authenticated,
        val identity: ReaderLocalProgressIdentity,
        val database: PositionObservations,
    ) {
        private val evidence = File(directory, "online-evidence.log")
        private val bootstrap = createAndroidReaderBootstrapGateway(isolated)
        private val media = createAndroidAudioMediaTransport(isolated, session.profile)
        var runtime: AudioPlaybackRuntime? = null
            private set

        fun record(result: String, position: Long = 0, revision: Long = 0) {
            // IDs are fixed fixture facts; no profile, locator, URL, title, JSON or credentials.
            val line = "result=$result resourceId=${fixture.resourceId} assetId=${fixture.assetId} " +
                "position=$position revision=$revision"
            evidence.appendText("$line\n")
            Log.i("RG04ReleaseLive", line)
        }

        fun openPlayer(autoplay: Boolean): AudioPlaybackRuntime {
            lateinit var player: AudioPlaybackRuntime
            instrumentation.runOnMainSync {
                assertFalse("RG04_EXISTING_APP_AUDIO_SESSION", app.audioPlaybackRuntime.snapshot.value.hasSession)
                player = AudioPlaybackRuntime(isolated, app.audioTransportRegistry)
                runtime = player
                // No supplied chapter/position: every launch uses the production restore owner.
                player.launchRemote(
                    profile = session.profile, namespace = identity.namespace, resourceId = fixture.resourceId,
                    autoplay = autoplay, bootstrapGateway = bootstrap, mediaTransport = media,
                )
            }
            return player
        }

        fun confirmPlaybackAndPause(
            player: AudioPlaybackRuntime,
            initialConfirmation: ReaderProgressSnapshotV5? = null,
        ): ConfirmedPause {
            awaitPlayer(player) { it.phase == AudioPlaybackPhase.Playing && it.durationMillis > 0 }
            assertFixturePlayer(player, fixture)
            val started = SystemClock.elapsedRealtime()
            var previous = initialConfirmation
            for (checkpoint in listOf(5_000L, 10_000L)) {
                // Observe the last second of each absolute window; HTTP and DB reads share its deadline.
                waitUntil(started + checkpoint - 1_000)
                val confirmed = try {
                    database.awaitConfirmed(started + checkpoint) { local, sync ->
                        locatorMillis(local) > (previous?.let { locatorMillis(it) } ?: 0) &&
                            local.capturedAtEpochMillis > (previous?.capturedAtEpochMillis ?: 0) &&
                            sync.confirmedRevision > (previous?.revision ?: 0)
                    }
                } catch (failure: Throwable) {
                    // Capture before finally/close creates a different Stop position; rethrow unchanged.
                    val snapshot = player.snapshot.value
                    record("CHECKPOINT_${checkpoint}_FAIL_OBSERVATION phase=${snapshot.phase} " +
                        "duration=${snapshot.durationMillis} ${database.confirmationObservation}",
                        snapshot.positionMillis)
                    throw failure
                }
                waitUntil(started + checkpoint)
                assertEquals("RG04_CONTINUOUS_PLAYBACK", AudioPlaybackPhase.Playing, player.snapshot.value.phase)
                assertTrue("RG04_CONFIRMED_POSITION_LAG",
                    abs(player.snapshot.value.positionMillis - locatorMillis(confirmed)) <= 5_000)
                record("CHECKPOINT_${checkpoint}_PASS", locatorMillis(confirmed), confirmed.revision)
                previous = confirmed
            }
            val pauseRequestedAt = System.currentTimeMillis()
            instrumentation.runOnMainSync { player.pause() }
            awaitPlayer(player) { it.phase == AudioPlaybackPhase.Paused }
            val pausedSnapshot = player.snapshot.value
            val pausedPosition = pausedSnapshot.positionMillis
            val paused = database.awaitConfirmed(SystemClock.elapsedRealtime() + 5_000) { local, sync ->
                local.capturedAtEpochMillis >= pauseRequestedAt &&
                    abs(locatorMillis(local) - pausedPosition) <= 100 &&
                    sync.confirmedRevision > requireNotNull(previous).revision
            }
            record("PAUSE_CONFIRMED", locatorMillis(paused), paused.revision)
            return ConfirmedPause(pausedSnapshot, paused)
        }

        fun closePlayerAndObserve() {
            instrumentation.runOnMainSync { requireNotNull(runtime).close() }
            runtime = null
            // close() can capture Stop before cancelling sync. Do not erase or manually ACK that outbox.
            val closeObservationDeadline = SystemClock.elapsedRealtime() + 5_000
            var closedObservation: DurableObservation? = null
            while (closedObservation == null && SystemClock.elapsedRealtime() < closeObservationDeadline) {
                closedObservation = database.read()
                if (closedObservation == null) Thread.sleep(25)
            }
            assertTrue("RG04_CLOSE_STABLE_OBSERVATION_DEADLINE",
                closedObservation != null && SystemClock.elapsedRealtime() <= closeObservationDeadline)
            val closed = requireNotNull(closedObservation)
            assertTrue("RG04_CLOSE_TERMINAL_FAILURE", closed.sync.terminalFailureCode == null)
            record(if (closed.sync.pending == null) "CLOSED_CONFIRMED" else "CLOSED_PENDING",
                closed.local?.let(::locatorMillis) ?: 0, closed.sync.confirmedRevision)
        }

        fun assertAppSessionUnchanged() {
            assertFalse("RG04_APP_AUDIO_SESSION_CHANGED", app.audioPlaybackRuntime.snapshot.value.hasSession)
        }
    }

    private fun awaitRestoredPlayer(player: AudioPlaybackRuntime, fixture: ReleaseAudioFixture): AudioPlaybackSnapshot {
        awaitPlayer(player) {
            it.phase in setOf(AudioPlaybackPhase.Ready, AudioPlaybackPhase.Paused) && it.durationMillis > 0
        }
        assertFixturePlayer(player, fixture)
        return player.snapshot.value
    }

    private fun prepareActivity() {
        compose.setContent { Text("RG04") }
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED).single()
            activity.setShowWhenLocked(true)
            activity.setTurnScreenOn(true)
            activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    private fun awaitPlayer(player: AudioPlaybackRuntime, predicate: (AudioPlaybackSnapshot) -> Boolean) {
        compose.waitUntil(30_000) {
            val snapshot = player.snapshot.value
            assertTrue("RG04_MEDIA3_ERROR:${snapshot.error?.code}", snapshot.phase != AudioPlaybackPhase.Error)
            predicate(snapshot)
        }
    }

    private fun assertFixturePlayer(player: AudioPlaybackRuntime, fixture: ReleaseAudioFixture) {
        val snapshot = player.snapshot.value
        val tracks = player.currentTracks()
        assertTrue("RG04_SINGLE_ONLINE_ASSET", tracks.size == 1)
        assertTrue("RG04_BOOTSTRAP_IDENTITY",
            snapshot.bookId == fixture.bookId && snapshot.resourceId == fixture.resourceId &&
                snapshot.assetId == fixture.assetId && tracks.single().assetId == fixture.assetId &&
                tracks.single().apiPath == fixture.sourceApiPath && tracks.single().mimeType == fixture.mimeType)
        assertTrue("RG04_REAL_DECODER_DURATION",
            abs(snapshot.durationMillis - fixture.expectedDurationMillis) <= 2_000)
    }
}

private data class ConfirmedPause(val engine: AudioPlaybackSnapshot, val confirmed: ReaderProgressSnapshotV5)

private data class DurableObservation(val local: ReaderPositionLocalState?, val sync: ReaderPositionDurableState)

/** Each read uses a separate production SQLite connection, never the runtime's cached state. */
private class PositionObservations(
    private val context: ReleaseAudioContext,
    private val identity: ReaderLocalProgressIdentity,
    private val target: ReaderProgressSyncTarget,
    private val port: ReaderPositionServerPort,
    private val fixture: ReleaseAudioFixture,
) {
    var confirmationObservation = "read=not-started get=not-requested"
        private set

    fun read(): DurableObservation? = runBlocking {
        val database = AndroidReaderV5Database(context, identity)
        try {
            val before = database.loadPositionSyncState()
            val local = database.loadPosition(identity.resourceId)
            val after = database.loadPositionSyncState()
            if (before == after) DurableObservation(local, after) else null
        } finally {
            database.close()
        }
    }

    fun get(deadline: Long): ReaderProgressSnapshotV5? = runBlocking {
        val remaining = deadline - SystemClock.elapsedRealtime()
        assertTrue("RG04_HTTP_CONFIRMATION_DEADLINE", remaining > 0)
        when (val response = withTimeout(remaining) { port.load(target, etag = null) }) {
            is ReaderPositionQueryResult.Current -> response.snapshot
            is ReaderPositionQueryResult.Failure -> throw AssertionError("RG04_PROGRESS_GET_FAILED")
            is ReaderPositionQueryResult.Unchanged -> throw AssertionError("RG04_UNEXPECTED_NOT_MODIFIED")
        }
    }

    fun awaitConfirmed(
        deadline: Long,
        eligible: (ReaderPositionLocalState, ReaderPositionDurableState) -> Boolean,
    ): ReaderProgressSnapshotV5 {
        var lastGet = "get=not-requested"
        confirmationObservation = "read=not-started $lastGet"
        while (SystemClock.elapsedRealtime() < deadline) {
            val observed = read()
            val local = observed?.local
            val pending = observed?.sync?.pending
            // Retain scalar facts from these existing reads only; no diagnostic reads or GETs.
            val localSummary = "readAt=${SystemClock.elapsedRealtime()} readStable=${observed != null} " +
                "localPosition=${local?.position?.presentation?.playback?.positionMillis} " +
                "localDuration=${local?.position?.presentation?.playback?.durationMillis} " +
                "localCapturedAt=${local?.capturedAtEpochMillis} localClientId=${local?.clientId} " +
                "confirmedRevision=${observed?.sync?.confirmedRevision} " +
                "pending=${observed?.let { it.sync.pending != null }} " +
                "pendingPosition=${pending?.position?.presentation?.playback?.positionMillis} " +
                "pendingCapturedAt=${pending?.capturedAtEpochMillis} pendingMutationId=${pending?.mutationId} " +
                "terminal=${observed?.sync?.terminalFailureCode}"
            confirmationObservation = "$localSummary $lastGet"
            assertTrue("RG04_PROGRESS_TERMINAL_FAILURE", observed?.sync?.terminalFailureCode == null)
            if (local != null && observed.sync.pending == null && observed.sync.confirmedRevision > 0 &&
                eligible(local, observed.sync)) {
                confirmationObservation = "$localSummary get=in-flight"
                val remote = get(deadline)
                lastGet = "get=${if (remote == null) "current-null" else "current"} " +
                    "getAt=${SystemClock.elapsedRealtime()} getRevision=${remote?.revision} " +
                    "getPosition=${remote?.position?.presentation?.playback?.positionMillis} " +
                    "getDuration=${remote?.position?.presentation?.playback?.durationMillis} " +
                    "getCapturedAt=${remote?.capturedAtEpochMillis} getClientId=${remote?.clientId}"
                confirmationObservation = "$localSummary $lastGet"
                val after = read()
                confirmationObservation += " getReadStable=${after == observed}"
                if (after == observed && remote != null && remote.revision == observed.sync.confirmedRevision &&
                    remote.clientId == local.clientId && remote.capturedAtEpochMillis == local.capturedAtEpochMillis &&
                    remote.position.presentation == local.position.presentation &&
                    // The server sorts opaque-object keys; the engine retains insertion order.
                    // Compare the complete JSON value without changing any Locator member.
                    Json.parseToJsonElement(remote.position.locator.canonicalJson) ==
                        Json.parseToJsonElement(local.position.locator.canonicalJson) &&
                    SystemClock.elapsedRealtime() <= deadline) {
                    assertFixtureSnapshot(remote)
                    return remote
                }
            }
            Thread.sleep(25)
        }
        throw AssertionError("RG04_CONFIRMED_DATABASE_AND_GET_DEADLINE $confirmationObservation")
    }

    fun assertFixtureSnapshot(remote: ReaderProgressSnapshotV5) {
        assertTrue("RG04_SERVER_RESOURCE_ID", remote.resourceId == fixture.resourceId)
        val locator = Json.parseToJsonElement(remote.position.locator.canonicalJson).jsonObject
        assertTrue("RG04_CANONICAL_AUDIO_LOCATOR",
            locator.getValue("href").jsonPrimitive.content == fixture.sourceApiPath &&
                locator.getValue("type").jsonPrimitive.content == fixture.mimeType)
        assertTrue("RG04_LOCATOR_PRESENTATION_AGREE",
            abs(locatorMillis(remote) - requireNotNull(remote.position.presentation.playback).positionMillis) <= 1)
    }
}

// Test observations only; production AudioProgressSession selects and restores the Locator.
private fun locatorMillis(local: ReaderPositionLocalState): Long = locatorMillis(local.position.locator.canonicalJson)
private fun locatorMillis(remote: ReaderProgressSnapshotV5): Long = locatorMillis(remote.position.locator.canonicalJson)
private fun locatorMillis(canonicalJson: String): Long =
    (Json.parseToJsonElement(canonicalJson).jsonObject.getValue("locations").jsonObject
        .getValue("time").jsonPrimitive.double * 1_000).toLong()

private fun waitUntil(deadline: Long) {
    val remaining = deadline - SystemClock.elapsedRealtime()
    if (remaining > 0) Thread.sleep(remaining)
}
