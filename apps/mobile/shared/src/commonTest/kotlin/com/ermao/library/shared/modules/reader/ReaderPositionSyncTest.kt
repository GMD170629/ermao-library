package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.ReaderPositionPushResult
import com.ermao.library.shared.modules.reader.application.ReaderPositionQueryResult
import com.ermao.library.shared.modules.reader.application.ReaderPositionServerPort
import com.ermao.library.shared.modules.reader.application.ReaderPositionSyncCoordinator
import com.ermao.library.shared.modules.reader.application.ReaderPositionSyncStateStore
import com.ermao.library.shared.modules.reader.application.ReaderPositionWriteResponse
import com.ermao.library.shared.modules.reader.application.ReaderPositionUpload
import com.ermao.library.shared.modules.reader.infrastructure.ReaderPositionSyncStateJson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class ReaderPositionSyncTest {
    @Test
    fun durableStateCodecKeepsPendingMutation() {
        val mutation = ReaderProgressMutationV5(
            resourceId = "resource-1",
            clientId = "android-client",
            mutationId = "58a3ac3c-52d0-41ed-9c85-0524b532f25b",
            capturedAtEpochMillis = 1_000,
            position = report(),
        )
        val state = ReaderPositionDurableState(pending = mutation)
        assertNotNull(state.pending)
        val encoded = ReaderPositionSyncStateJson().encode(state)
        assertTrue(encoded.contains("\"pending\":{"))
        assertEquals(mutation.mutationId, ReaderPositionSyncStateJson().decode(encoded).pending?.mutationId)
    }

    @Test
    fun malformedAcceptedMutationDoesNotClearTheExactPendingBody() = runBlocking {
        val store = FakeStore()
        val expectedMutationId = "58a3ac3c-52d0-41ed-9c85-0524b532f25b"
        val coordinator = ReaderPositionSyncCoordinator(
            stateStore = store,
            server = object : ReaderPositionServerPort {
                override suspend fun push(upload: ReaderPositionUpload): ReaderPositionPushResult =
                    ReaderPositionPushResult.Accepted(
                        ReaderPositionWriteResponse(
                            acceptedMutationId = "f4743f84-16dc-4202-ab50-729e4d036d16",
                            acceptedRevision = 2,
                            currentSnapshot = snapshot(upload.mutation.mutationId),
                        ),
                    )

                override suspend fun load(
                    target: ReaderProgressSyncTarget,
                    etag: String?,
                ): ReaderPositionQueryResult = ReaderPositionQueryResult.Current(null, null)
            },
            scope = CoroutineScope(coroutineContext),
            createMutationId = { expectedMutationId },
        )

        coordinator.saveLocalAndSubmit(target(), local(1_000))
        coordinator.awaitIdle()

        assertEquals(expectedMutationId, store.state.pending?.mutationId)
        assertEquals("INVALID_PROGRESS_RESPONSE", store.state.terminalFailureCode)
        assertNotNull(store.state.pending)
        Unit
    }

    @Test
    fun responseMayCarryASeparateCurrentSnapshotRevision() {
        val report = report()
        val response = ReaderPositionWriteResponse(
            acceptedMutationId = "58a3ac3c-52d0-41ed-9c85-0524b532f25b",
            acceptedRevision = 4,
            currentSnapshot = snapshot(
                mutationId = "f4743f84-16dc-4202-ab50-729e4d036d16",
                revision = 9,
            ),
        )
        assertEquals(4, response.acceptedRevision)
        assertEquals(9, response.currentSnapshot.revision)
        assertEquals(report, response.currentSnapshot.position)
    }

    private fun target() = ReaderProgressSyncTarget(
        namespace = ReaderSyncNamespace("server", "user", 1),
        bookId = "book-1",
        resourceId = "resource-1",
        sourceFormat = ReaderFormat.Epub,
    )

    private fun local(timestamp: Long) = ReaderPositionLocalState(
        resourceId = "resource-1",
        clientId = "android-client",
        capturedAtEpochMillis = timestamp,
        position = report(),
    )

    private fun report() = ReaderPositionReport(
        locator = ReaderOpaqueLocator.parse(
            "{\"href\":\"chapter.xhtml\",\"locations\":{\"progression\":0.25},\"text\":{}}",
        ),
        presentation = ReaderPositionPresentation(
            displayPercent = 25.0,
            totalProgression = 0.25,
            currentHref = "chapter.xhtml",
            chapter = null,
            page = null,
            playback = null,
        ),
    )

    private fun snapshot(
        mutationId: String,
        revision: Long = 1,
    ) = ReaderProgressSnapshotV5(
        resourceId = "resource-1",
        clientId = "ios-client",
        revision = revision,
        mutationId = mutationId,
        capturedAtEpochMillis = 1_000,
        receivedAtEpochMillis = 2_000,
        position = report(),
    )

    private class FakeStore : ReaderPositionSyncStateStore {
        var value: ReaderPositionLocalState? = null
        var state = ReaderPositionDurableState()

        override suspend fun loadPosition(resourceId: String) = value
        override suspend fun savePosition(position: ReaderPositionLocalState) { value = position }
        override suspend fun deletePosition(resourceId: String) {
            value = null
            state = ReaderPositionDurableState()
        }
        override suspend fun loadPositionSyncState() = state
        override suspend fun commitPositionAndPending(
            position: ReaderPositionLocalState,
            pending: ReaderProgressMutationV5,
        ) {
            value = position
            state = state.copy(pending = pending, terminalFailureCode = null)
        }
        override suspend fun acknowledgePosition(
            mutationId: String,
            response: ReaderPositionWriteResponse,
        ) {
            if (state.pending?.mutationId == mutationId) {
                state = state.copy(
                    confirmedRevision = maxOf(response.acceptedRevision, response.currentSnapshot.revision),
                    pending = null,
                )
            }
        }
        override suspend fun acceptRemotePosition(
            position: ReaderPositionLocalState,
            snapshot: ReaderProgressSnapshotV5,
        ) {
            value = position
            state = ReaderPositionDurableState(confirmedRevision = snapshot.revision)
        }
        override suspend fun recordPositionTerminalFailure(mutationId: String, failureCode: String) {
            if (state.pending?.mutationId == mutationId) state = state.copy(terminalFailureCode = failureCode)
        }
    }
}
