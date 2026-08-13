package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.ReaderProgressPushResult
import com.ermao.library.shared.modules.reader.application.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.application.ReaderProgressSyncStateStore
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class ReaderProgressSyncTest {
    @Test
    fun exactLocalAndPendingCommitPrecedesNetwork() = runBlocking {
        val events = mutableListOf<String>()
        val store = FakeStore { events += "durable" }
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = { upload ->
                events += "network"
                ReaderProgressPushResult.Accepted(snapshot(upload.mutation.locator, upload.mutation.baseRevision + 1))
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { MUTATION_ID },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        coordinator.awaitIdle()

        assertEquals(listOf("durable", "network"), events)
        assertEquals(1, store.state.confirmedRevision)
        assertNull(store.state.pending)
    }

    @Test
    fun retryableFailureKeepsDurableLatestPendingAcrossWorkerRuns() = runBlocking {
        val store = FakeStore()
        var calls = 0
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = { upload ->
                calls += 1
                if (calls == 1) ReaderProgressPushResult.RetryableFailure("OFFLINE")
                else ReaderProgressPushResult.Accepted(snapshot(upload.mutation.locator, 1))
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { MUTATION_ID },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        coordinator.awaitIdle()
        assertNotNull(store.state.pending)

        coordinator.retryPending(target())
        coordinator.awaitIdle()
        assertNull(store.state.pending)
    }

    @Test
    fun conflictIsDurableAndStopsAutomaticOverwrite() = runBlocking {
        val store = FakeStore()
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = { upload -> ReaderProgressPushResult.Conflict(snapshot(upload.mutation.locator, 5)) },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { MUTATION_ID },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        coordinator.awaitIdle()

        assertEquals(5, store.state.conflict?.server?.revision)
        assertNotNull(store.state.pending)
        Unit
    }

    @Test
    fun inFlightUpdatesCollapseToDurableLatestMutation() = runBlocking {
        val release = CompletableDeferred<Unit>()
        val started = CompletableDeferred<Unit>()
        val uploaded = mutableListOf<Long>()
        var mutationCounter = 0
        val store = FakeStore()
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = { upload ->
                uploaded += upload.mutation.capturedAtEpochMillis
                if (uploaded.size == 1) {
                    started.complete(Unit)
                    release.await()
                }
                ReaderProgressPushResult.Accepted(snapshot(upload.mutation.locator, uploaded.size.toLong()))
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { "00000000-0000-4000-8000-${(++mutationCounter).toString().padStart(12, '0')}" },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        started.await()
        coordinator.saveLocalAndSubmit(target(), progress(2))
        coordinator.saveLocalAndSubmit(target(), progress(3))
        release.complete(Unit)
        coordinator.awaitIdle()

        assertEquals(listOf(1L, 3L), uploaded)
    }

    private fun target() = ReaderProgressSyncTarget(
        ReaderSyncNamespace("server", "user", 1),
        "work-1",
        "volume-1",
        ReaderFormat.Epub,
    )

    private fun progress(timestamp: Long) = ReaderProgress(
        "volume-1",
        ReflowReaderLocation(
            resourceKey = "chapter.xhtml",
            engineLocator = envelope().asEngineLocator(),
            contentFingerprint = fingerprint(),
        ),
        timestamp,
        "android-client",
    )

    private fun snapshot(locator: PublicationLocation, revision: Long) = ReaderProgressSnapshotV4(
        "volume-1",
        revision,
        locator,
        50.0,
        100,
    )

    private fun envelope() = ReadiumLocatorEnvelope.parse(
        """{"engine":"readium","platform":"android","version":"readium-kotlin:3.3.0","publication":{"originalFileHash":"${"a".repeat(64)}","parser":"readium:epub","normalization":"epub-v1"},"payload":{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#p1"},"text":{"highlight":"anchor"}}}""",
    )

    private fun fingerprint() = ContentFingerprint("sha256:" + "a".repeat(64), "readium:epub", "epub-v1")

    private class FakeStore(private val committed: () -> Unit = {}) : ReaderProgressSyncStateStore {
        var value: ReaderProgress? = null
        var state = ReaderProgressDurableState()

        override suspend fun load(sourceId: String) = value
        override suspend fun save(progress: ReaderProgress) { value = progress }
        override suspend fun delete(sourceId: String) { value = null; state = ReaderProgressDurableState() }
        override suspend fun loadSyncState() = state
        override suspend fun commitProgressAndPending(progress: ReaderProgress, pending: ReaderProgressMutation) {
            value = progress
            state = state.copy(pending = pending, conflict = null, terminalFailureCode = null)
            committed()
        }
        override suspend fun acknowledge(mutationId: String, snapshot: ReaderProgressSnapshotV4) {
            val pending = state.pending
            state = state.copy(
                confirmedRevision = snapshot.revision,
                pending = if (pending?.mutationId == mutationId) null else pending?.copy(baseRevision = snapshot.revision),
            )
        }
        override suspend fun recordConflict(conflict: ReaderProgressConflict) {
            state = state.copy(conflict = conflict)
        }
        override suspend fun recordTerminalFailure(mutationId: String, failureCode: String) {
            state = state.copy(terminalFailureCode = failureCode)
        }
    }

    private companion object {
        const val MUTATION_ID = "58a3ac3c-52d0-41ed-9c85-0524b532f25b"
    }
}
