package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ExactLocationMatch
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderRemoteProgressNotice
import com.ermao.library.shared.modules.reader.domain.compareExactProgressLocations
import com.ermao.library.shared.modules.reader.domain.exactPublicationLocation
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.toMutation
import com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
import com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
import com.ermao.library.shared.modules.reader.domain.PdfReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
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
    private var wakeGeneration: Long = 0
    private var baselineRevision: Long = 0
    private var remoteNotice: ReaderRemoteProgressNotice? = null
    private val _remoteProgressNotices = MutableStateFlow<ReaderRemoteProgressNotice?>(null)
    val remoteProgressNotices: StateFlow<ReaderRemoteProgressNotice?> = _remoteProgressNotices.asStateFlow()

    suspend fun saveLocalAndSubmit(target: ReaderProgressSyncTarget, progress: ReaderProgress) {
        require(progress.resourceId == target.resourceId) { "Reader progress resource does not match its target" }
        require(target.sourceFormat.accepts(progress)) { "Reader progress morphology does not match its source format" }
        val state = stateStore.loadSyncState()
        val notice = remoteNotice
        if (notice != null) {
            val previous = stateStore.load(progress.resourceId)
            val genuinelyMoved = previous == null || compareExactProgressLocations(
                previous.exactPublicationLocation(),
                progress.exactPublicationLocation(),
            ) != ExactLocationMatch.Exact
            if (!genuinelyMoved) return
        }
        val baseRevision = notice?.revision ?: maxOf(state.confirmedRevision, baselineRevision)
        val pending = progress.toMutation(baseRevision, createMutationId())
        stateStore.commitProgressAndPending(progress, pending)
        if (notice != null) {
            remoteNotice = null
            _remoteProgressNotices.value = null
        }
        launchDrain(target)
    }

    suspend fun retryPending(target: ReaderProgressSyncTarget) {
        val state = stateStore.loadSyncState()
        if (state.pending != null && state.terminalFailureCode == null) launchDrain(target)
    }

    suspend fun continueStartupWithLocal(
        target: ReaderProgressSyncTarget,
        progress: ReaderProgress,
        serverRevision: Long,
    ) {
        val pending = progress.toMutation(serverRevision, createMutationId())
        stateStore.commitProgressAndPending(progress, pending)
        baselineRevision = serverRevision
        launchDrain(target)
    }

    suspend fun discardStartupPending(mutationId: String, serverRevision: Long) {
        stateStore.discardPendingAfterConflict(mutationId, serverRevision)
        baselineRevision = serverRevision
    }

    fun beginSession(snapshot: ReaderProgressSnapshotV4?) {
        baselineRevision = snapshot?.revision ?: 0
        remoteNotice = null
        _remoteProgressNotices.value = null
    }

    fun remoteProgressNotice(): ReaderRemoteProgressNotice? = remoteNotice

    /** Applies lifecycle GET/409 state without navigating or mutating durable exact progress. */
    suspend fun observeRemoteProgress(
        snapshot: ReaderProgressSnapshotV4,
        currentClientId: String,
        currentProgress: ReaderProgress?,
    ): ReaderRemoteProgressNotice? {
        if (snapshot.revision <= baselineRevision) return remoteNotice
        baselineRevision = snapshot.revision
        if (snapshot.clientId == currentClientId) return remoteNotice
        val sameExact = currentProgress?.let {
            runCatching {
                compareExactProgressLocations(it.exactPublicationLocation(), snapshot.locator) == ExactLocationMatch.Exact
            }.getOrDefault(false)
        } ?: false
        if (!sameExact) {
            remoteNotice = ReaderRemoteProgressNotice(snapshot)
            _remoteProgressNotices.value = remoteNotice
        }
        return remoteNotice
    }

    fun dismissRemoteProgressNotice() {
        remoteNotice = null
        _remoteProgressNotices.value = null
    }

    suspend fun acceptVerifiedRemoteProgress(progress: ReaderProgress, snapshot: ReaderProgressSnapshotV4) {
        require(compareExactProgressLocations(progress.exactPublicationLocation(), snapshot.locator) == ExactLocationMatch.Exact) {
            "Remote Reader progress was not post-verified"
        }
        stateStore.acceptRemoteProgress(progress, snapshot)
        baselineRevision = snapshot.revision
        remoteNotice = null
        _remoteProgressNotices.value = null
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
            wakeGeneration += 1
            if (worker?.isActive != true) worker = scope.launch { drain(target) }
        }
    }

    private suspend fun drain(target: ReaderProgressSyncTarget) {
        val ownedWorker = checkNotNull(currentCoroutineContext()[Job])
        try {
            while (true) {
                val observedWakeGeneration = mutex.withLock { wakeGeneration }
                val state = stateStore.loadSyncState()
                val next = state.pending
                if (next == null || state.terminalFailureCode != null) {
                    if (finishIfNotWoken(ownedWorker, observedWakeGeneration)) return
                    continue
                }
                when (val result = try {
                    server.push(ReaderProgressUpload(target, next))
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Throwable) {
                    ReaderProgressPushResult.RetryableFailure("NETWORK_UNAVAILABLE")
                }) {
                    is ReaderProgressPushResult.Accepted -> stateStore.acknowledge(next.mutationId, result.snapshot)
                    is ReaderProgressPushResult.Conflict -> {
                        stateStore.discardPendingAfterConflict(next.mutationId, result.current.revision)
                        observeRemoteProgress(result.current, next.clientId, stateStore.load(next.resourceId))
                        if (finishIfNotWoken(ownedWorker, observedWakeGeneration)) return
                    }
                    is ReaderProgressPushResult.RetryableFailure -> {
                        if (finishIfNotWoken(ownedWorker, observedWakeGeneration)) return
                    }
                    is ReaderProgressPushResult.Rejected -> {
                        stateStore.recordTerminalFailure(next.mutationId, result.failureCode)
                        if (finishIfNotWoken(ownedWorker, observedWakeGeneration)) return
                    }
                }
            }
        } finally {
            mutex.withLock {
                if (worker === ownedWorker) worker = null
            }
        }
    }

    /** Atomically retires this worker only when no lifecycle/save wake arrived during its attempt. */
    private suspend fun finishIfNotWoken(ownedWorker: Job, observedWakeGeneration: Long): Boolean =
        mutex.withLock {
            when {
                worker !== ownedWorker -> true
                wakeGeneration != observedWakeGeneration -> false
                else -> {
                    worker = null
                    true
                }
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

/** Swift-friendly owner for the shared coordinator and its coroutine lifetime. */
class ReaderProgressSyncRuntime(
    stateStore: ReaderProgressSyncStateStore,
    target: ReaderProgressSyncTarget,
    server: ReaderProgressServerPort,
) {
    private val scope = MainScope()
    val coordinator = ReaderProgressSyncCoordinator(stateStore, server, scope)
    val store: ReaderProgressSyncingStore = LocalFirstReaderProgressStore(stateStore, target, coordinator)

    fun close() {
        scope.cancel()
    }
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
