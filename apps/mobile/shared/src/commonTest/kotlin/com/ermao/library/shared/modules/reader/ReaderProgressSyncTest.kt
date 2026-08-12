package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.LocalFirstReaderProgressStore
import com.ermao.library.shared.modules.reader.application.ReaderProgressPushResult
import com.ermao.library.shared.modules.reader.application.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.application.ReaderProgressUpload
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ReaderProgressSyncTest {
    @Test
    fun localSavePrecedesSingleNetworkPut() = runBlocking {
        val events = mutableListOf<String>()
        val local = FakeStore { events += "local" }
        val coordinator = ReaderProgressSyncCoordinator(
            local,
            server = { upload ->
                events += "network:${upload.snapshot.percent}"
                ReaderProgressPushResult.Accepted(upload.snapshot)
            },
            scope = CoroutineScope(coroutineContext),
        )

        coordinator.saveLocalAndSubmit(target(), progress(0.4, 1))
        coordinator.awaitIdle()

        assertEquals(listOf("local", "network:40.0"), events)
        assertEquals(progress(0.4, 1), local.value)
    }

    @Test
    fun inFlightRequestKeepsOnlyLatestPendingSnapshotAndFailureIsDiscarded() = runBlocking {
        val releaseFirst = CompletableDeferred<Unit>()
        val startedFirst = CompletableDeferred<Unit>()
        val uploaded = mutableListOf<Double>()
        val coordinator = ReaderProgressSyncCoordinator(
            FakeStore(),
            server = { upload ->
                uploaded += upload.snapshot.percent
                if (uploaded.size == 1) {
                    startedFirst.complete(Unit)
                    releaseFirst.await()
                    ReaderProgressPushResult.Discarded("OFFLINE")
                } else ReaderProgressPushResult.Accepted(upload.snapshot)
            },
            scope = CoroutineScope(coroutineContext),
        )

        coordinator.saveLocalAndSubmit(target(), progress(0.1, 1))
        startedFirst.await()
        coordinator.saveLocalAndSubmit(target(), progress(0.2, 2))
        coordinator.saveLocalAndSubmit(target(), progress(0.3, 3))
        releaseFirst.complete(Unit)
        coordinator.awaitIdle()

        assertEquals(listOf(10.0, 30.0), uploaded)
    }

    @Test
    fun localFailurePreventsNetworkPut() = runBlocking {
        var uploaded: ReaderProgressUpload? = null
        val coordinator = ReaderProgressSyncCoordinator(
            object : ReaderProgressStore {
                override suspend fun load(sourceId: String) = null
                override suspend fun save(progress: ReaderProgress) = error("disk full")
                override suspend fun delete(sourceId: String) = Unit
            },
            server = { upload ->
                uploaded = upload
                ReaderProgressPushResult.Accepted(upload.snapshot)
            },
            scope = CoroutineScope(coroutineContext),
        )

        runCatching { coordinator.saveLocalAndSubmit(target(), progress(0.5, 1)) }

        assertNull(uploaded)
    }

    @Test
    fun exactIdentityIgnoresAuthorizationVersionButSeparatesClientAndContent() {
        val first = identity(ReaderSyncNamespace("server", "user", 4))
        val second = identity(ReaderSyncNamespace("server", "user", 5))

        assertEquals(first.stableKey, second.stableKey)
        kotlin.test.assertNotEquals(first.stableKey, first.copy(clientId = "another-client").stableKey)
        kotlin.test.assertNotEquals(
            first.stableKey,
            first.copy(localContentFingerprint = fingerprint('b')).stableKey,
        )
    }

    private fun target() = ReaderProgressSyncTarget(
        ReaderSyncNamespace("server", "user", 1),
        "work-1",
        "volume-1",
        ReaderFormat.Epub,
        ReaderServerContentFingerprint("server-token"),
    )

    private fun progress(progression: Double, timestamp: Long) = ReaderProgress(
        "volume-1",
        ReflowReaderLocation(
            "chapter.xhtml",
            progression,
            progression,
            contentFingerprint = fingerprint(),
        ),
        timestamp,
        "android-client",
    )

    private fun identity(namespace: ReaderSyncNamespace) = ReaderLocalProgressIdentity(
        namespace,
        "android-client",
        "volume-1",
        fingerprint(),
    )

    private fun fingerprint(character: Char = 'a') = ContentFingerprint(
        "sha256:" + character.toString().repeat(64),
        "readium-kotlin:3.3.0",
        "v1",
    )

    private class FakeStore(private val afterSave: () -> Unit = {}) : ReaderProgressStore {
        var value: ReaderProgress? = null
        override suspend fun load(sourceId: String) = value
        override suspend fun save(progress: ReaderProgress) {
            value = progress
            afterSave()
        }
        override suspend fun delete(sourceId: String) {
            value = null
        }
    }
}
