package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.ReaderProgressPushResult
import com.ermao.library.shared.modules.reader.application.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.application.ReaderProgressSyncStateStore
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.yield
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
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
    fun retryWakeArrivingDuringFailingUploadIsNotLost() = runBlocking {
        val firstStarted = CompletableDeferred<Unit>()
        val releaseFirst = CompletableDeferred<Unit>()
        val store = FakeStore()
        var calls = 0
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = { upload ->
                calls += 1
                if (calls == 1) {
                    firstStarted.complete(Unit)
                    releaseFirst.await()
                    ReaderProgressPushResult.RetryableFailure("OFFLINE")
                } else {
                    ReaderProgressPushResult.Accepted(snapshot(upload.mutation.locator, 1))
                }
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { MUTATION_ID },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        firstStarted.await()
        coordinator.retryPending(target())
        releaseFirst.complete(Unit)
        coordinator.awaitIdle()

        assertEquals(2, calls)
        assertNull(store.state.pending)
    }

    @Test
    fun newerProgressSavedDuringFailingUploadStartsAnotherDrain() = runBlocking {
        val firstStarted = CompletableDeferred<Unit>()
        val releaseFirst = CompletableDeferred<Unit>()
        val uploaded = mutableListOf<Long>()
        var mutationCounter = 0
        val store = FakeStore()
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = { upload ->
                uploaded += upload.mutation.capturedAtEpochMillis
                if (uploaded.size == 1) {
                    firstStarted.complete(Unit)
                    releaseFirst.await()
                    ReaderProgressPushResult.RetryableFailure("OFFLINE")
                } else {
                    ReaderProgressPushResult.Accepted(snapshot(upload.mutation.locator, 1))
                }
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { "00000000-0000-4000-8000-${(++mutationCounter).toString().padStart(12, '0')}" },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        firstStarted.await()
        coordinator.saveLocalAndSubmit(target(), progress(2))
        releaseFirst.complete(Unit)
        coordinator.awaitIdle()

        assertEquals(listOf(1L, 2L), uploaded)
        assertNull(store.state.pending)
    }

    @Test
    fun cancelledWorkerCannotRetireItsReplacement() = runBlocking {
        val firstStarted = CompletableDeferred<Unit>()
        val allowCancelledWorkerToFinish = CompletableDeferred<Unit>()
        val replacementStarted = CompletableDeferred<Unit>()
        val allowReplacementToFinish = CompletableDeferred<Unit>()
        var mutationCounter = 0
        val store = FakeStore()
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = { upload ->
                if (upload.mutation.capturedAtEpochMillis == 1L) {
                    firstStarted.complete(Unit)
                    try {
                        awaitCancellation()
                    } finally {
                        withContext(NonCancellable) { allowCancelledWorkerToFinish.await() }
                    }
                } else {
                    replacementStarted.complete(Unit)
                    allowReplacementToFinish.await()
                    ReaderProgressPushResult.Accepted(snapshot(upload.mutation.locator, 1))
                }
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { "00000000-0000-4000-8000-${(++mutationCounter).toString().padStart(12, '0')}" },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        firstStarted.await()
        coordinator.cancelWorker()
        coordinator.saveLocalAndSubmit(target(), progress(2, movedEnvelope()))
        replacementStarted.await()
        allowCancelledWorkerToFinish.complete(Unit)

        val awaitingIdle = async { coordinator.awaitIdle() }
        yield()
        assertFalse(awaitingIdle.isCompleted)
        allowReplacementToFinish.complete(Unit)
        awaitingIdle.await()
        assertNull(store.state.pending)
    }

    @Test
    fun conflictDropsRejectedMutationAndWaitsForRealMovement() = runBlocking {
        val store = FakeStore()
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = {
                ReaderProgressPushResult.Conflict(
                    snapshot(
                        ReflowablePublicationLocation(
                            remoteEnvelope().asEngineLocator(),
                        ),
                        5,
                    ),
                )
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { MUTATION_ID },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        coordinator.awaitIdle()

        assertEquals(5, store.state.confirmedRevision)
        assertNull(store.state.pending)
        assertEquals(5, coordinator.remoteProgressNotice()?.revision)

        coordinator.saveLocalAndSubmit(target(), progress(1))
        coordinator.awaitIdle()
        assertNull(store.state.pending)
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

    @Test
    fun newerMovementDuringConflictIsRebasedBeforeItsFirstUpload() = runBlocking {
        val firstStarted = CompletableDeferred<Unit>()
        val releaseFirst = CompletableDeferred<Unit>()
        val uploaded = mutableListOf<Pair<Long, Long>>()
        var mutationCounter = 0
        val store = FakeStore()
        val coordinator = ReaderProgressSyncCoordinator(
            store,
            server = { upload ->
                uploaded += upload.mutation.capturedAtEpochMillis to upload.mutation.baseRevision
                if (uploaded.size == 1) {
                    firstStarted.complete(Unit)
                    releaseFirst.await()
                    ReaderProgressPushResult.Conflict(
                        snapshot(
                            ReflowablePublicationLocation(
                                remoteEnvelope().asEngineLocator(),
                            ),
                            5,
                        ),
                    )
                } else {
                    ReaderProgressPushResult.Accepted(snapshot(upload.mutation.locator, 6))
                }
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { "00000000-0000-4000-8000-${(++mutationCounter).toString().padStart(12, '0')}" },
        )

        coordinator.saveLocalAndSubmit(target(), progress(1))
        firstStarted.await()
        coordinator.saveLocalAndSubmit(target(), progress(2, movedEnvelope()))
        releaseFirst.complete(Unit)
        coordinator.awaitIdle()

        assertEquals(listOf(1L to 0L, 2L to 5L), uploaded)
        assertNull(store.state.pending)
    }

    private fun target() = ReaderProgressSyncTarget(
        ReaderSyncNamespace("server", "user", 1),
        "work-1",
        "volume-1",
        ReaderFormat.Epub,
    )

    private fun progress(timestamp: Long, locator: ReadiumLocatorEnvelope = envelope()) = ReaderProgress(
        "volume-1",
        ReflowReaderLocation(
            resourceKey = "chapter.xhtml",
            engineLocator = locator.asEngineLocator(),
        ),
        timestamp,
        "android-client",
    )

    private fun snapshot(locator: PublicationLocation, revision: Long) = ReaderProgressSnapshotV4(
        "volume-1",
        "ios-client",
        revision,
        locator,
        50.0,
        100,
    )

    private fun envelope() = ReadiumLocatorEnvelope.parse(
        """{"engine":"readium","platform":"android","version":"readium-kotlin:3.3.0","payload":{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#p1"},"text":{"highlight":"anchor"}}}""",
    )

    private fun remoteEnvelope() = ReadiumLocatorEnvelope.parse(
        """{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#remote"},"text":{"highlight":"remote anchor"}}}""",
    )

    private fun movedEnvelope() = ReadiumLocatorEnvelope.parse(
        """{"engine":"readium","platform":"android","version":"readium-kotlin:3.3.0","payload":{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#p2"},"text":{"highlight":"second anchor"}}}""",
    )

    private class FakeStore(private val committed: () -> Unit = {}) : ReaderProgressSyncStateStore {
        var value: ReaderProgress? = null
        var state = ReaderProgressDurableState()

        override suspend fun load(sourceId: String) = value
        override suspend fun save(progress: ReaderProgress) { value = progress }
        override suspend fun delete(sourceId: String) { value = null; state = ReaderProgressDurableState() }
        override suspend fun loadSyncState() = state
        override suspend fun commitProgressAndPending(progress: ReaderProgress, pending: ReaderProgressMutation) {
            value = progress
            state = state.copy(pending = pending, terminalFailureCode = null)
            committed()
        }
        override suspend fun acknowledge(mutationId: String, snapshot: ReaderProgressSnapshotV4) {
            val pending = state.pending
            state = state.copy(
                confirmedRevision = snapshot.revision,
                pending = if (pending?.mutationId == mutationId) null else pending?.copy(baseRevision = snapshot.revision),
            )
        }
        override suspend fun discardPendingAfterConflict(mutationId: String, serverRevision: Long) {
            val pending = state.pending?.let {
                if (it.mutationId == mutationId) null else it.copy(baseRevision = serverRevision)
            }
            state = state.copy(confirmedRevision = serverRevision, pending = pending)
        }
        override suspend fun acceptRemoteProgress(progress: ReaderProgress, snapshot: ReaderProgressSnapshotV4) {
            value = progress
            state = ReaderProgressDurableState(confirmedRevision = snapshot.revision)
        }
        override suspend fun recordTerminalFailure(mutationId: String, failureCode: String) {
            state = state.copy(terminalFailureCode = failureCode)
        }
    }

    private companion object {
        const val MUTATION_ID = "58a3ac3c-52d0-41ed-9c85-0524b532f25b"
    }
}
