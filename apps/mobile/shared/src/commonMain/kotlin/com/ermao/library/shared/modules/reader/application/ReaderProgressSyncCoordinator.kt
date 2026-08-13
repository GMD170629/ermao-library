package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ReaderProgressConflict
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.toMutation
import com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
import com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
import com.ermao.library.shared.modules.reader.domain.PdfReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.random.Random

/** Durable, single-flight, latest-only Reader v4 mutation coordinator. */
class ReaderProgressSyncCoordinator(
    private val stateStore: ReaderProgressSyncStateStore,
    private val server: ReaderProgressSyncPort,
    private val scope: CoroutineScope,
    private val createMutationId: () -> String = ::randomUuidV4,
) {
    private val mutex = Mutex()
    private var worker: Job? = null

    suspend fun saveLocalAndSubmit(target: ReaderProgressSyncTarget, progress: ReaderProgress) {
        require(progress.sourceId == target.volumeId) { "Reader progress source does not match its volume" }
        require(target.sourceFormat.accepts(progress)) { "Reader progress morphology does not match its source format" }
        val state = stateStore.loadSyncState()
        val baseRevision = state.conflict?.server?.revision ?: state.confirmedRevision
        val pending = progress.toMutation(baseRevision, createMutationId())
        stateStore.commitProgressAndPending(progress, pending)
        launchDrain(target)
    }

    suspend fun retryPending(target: ReaderProgressSyncTarget) {
        val state = stateStore.loadSyncState()
        if (state.pending != null && state.conflict == null && state.terminalFailureCode == null) launchDrain(target)
    }

    suspend fun awaitIdle() {
        while (true) {
            val active = mutex.withLock { worker } ?: return
            active.join()
        }
    }

    suspend fun cancelWorker() {
        mutex.withLock { worker.also { worker = null } }?.cancel()
    }

    private suspend fun launchDrain(target: ReaderProgressSyncTarget) {
        mutex.withLock {
            if (worker?.isActive != true) worker = scope.launch { drain(target) }
        }
    }

    private suspend fun drain(target: ReaderProgressSyncTarget) {
        try {
            while (true) {
                val state = stateStore.loadSyncState()
                val next = state.pending ?: return
                if (state.conflict != null || state.terminalFailureCode != null) return
                when (val result = try {
                    server.push(ReaderProgressUpload(target, next))
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Throwable) {
                    ReaderProgressPushResult.RetryableFailure("NETWORK_UNAVAILABLE")
                }) {
                    is ReaderProgressPushResult.Accepted -> stateStore.acknowledge(next.mutationId, result.snapshot)
                    is ReaderProgressPushResult.Conflict -> {
                        stateStore.recordConflict(ReaderProgressConflict(next, result.current))
                        return
                    }
                    is ReaderProgressPushResult.RetryableFailure -> return
                    is ReaderProgressPushResult.Rejected -> {
                        stateStore.recordTerminalFailure(next.mutationId, result.failureCode)
                        return
                    }
                }
            }
        } finally {
            mutex.withLock { worker = null }
        }
    }
}

private fun ReaderFormat.accepts(progress: ReaderProgress): Boolean = when (this) {
    ReaderFormat.Epub, ReaderFormat.Mobi, ReaderFormat.Text -> progress.location is ReflowReaderLocation
    ReaderFormat.Pdf -> progress.location is PdfReaderLocation
    ReaderFormat.Comic -> progress.location is ComicReaderLocation
    ReaderFormat.Audio -> progress.location is AudioReaderLocation
}

class LocalFirstReaderProgressStore(
    private val stateStore: ReaderProgressSyncStateStore,
    private val target: ReaderProgressSyncTarget,
    private val coordinator: ReaderProgressSyncCoordinator,
) : ReaderProgressSyncingStore {
    override suspend fun load(sourceId: String): ReaderProgress? = stateStore.load(sourceId)

    override suspend fun save(progress: ReaderProgress) = coordinator.saveLocalAndSubmit(target, progress)

    override suspend fun delete(sourceId: String) = stateStore.delete(sourceId)

    override suspend fun awaitPendingUpload() = coordinator.awaitIdle()

    override suspend fun retryPendingUpload() = coordinator.retryPending(target)

    override suspend fun syncState(): ReaderProgressDurableState = stateStore.loadSyncState()
}

private fun randomUuidV4(): String {
    val bytes = ByteArray(16).also(Random.Default::nextBytes)
    bytes[6] = ((bytes[6].toInt() and 0x0f) or 0x40).toByte()
    bytes[8] = ((bytes[8].toInt() and 0x3f) or 0x80).toByte()
    return buildString(36) {
        bytes.forEachIndexed { index, byte ->
            if (index in setOf(4, 6, 8, 10)) append('-')
            val value = byte.toInt() and 0xff
            append(HEX[value ushr 4])
            append(HEX[value and 0x0f])
        }
    }
}

private const val HEX = "0123456789abcdef"
