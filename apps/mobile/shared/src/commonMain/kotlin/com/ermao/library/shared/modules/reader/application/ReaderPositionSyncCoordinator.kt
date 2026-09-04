package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.random.Random

/**
 * Single-flight/latest-only v5 outbox owner.
 *
 * The worker always reads the currently durable pending mutation and sends
 * that exact value.  A retry therefore reuses both the mutation id and body;
 * an acknowledgement is guarded by the mutation id in the storage
 * transaction, so an in-flight older response cannot clear a newer capture.
 */
class ReaderPositionSyncCoordinator(
    private val stateStore: ReaderPositionSyncStateStore,
    private val server: ReaderPositionServerPort,
    private val scope: CoroutineScope,
    private val createMutationId: () -> String = ::randomUuidV4,
) {
    private val mutex = Mutex()
    private var worker: Job? = null
    private var wakeGeneration = 0L
    private var baselineRevision = 0L
    private var remoteNotice: ReaderRemotePositionNoticeV5? = null
    private val _remotePositionNotices = MutableStateFlow<ReaderRemotePositionNoticeV5?>(null)
    val remotePositionNotices: StateFlow<ReaderRemotePositionNoticeV5?> = _remotePositionNotices.asStateFlow()

    suspend fun saveLocalAndSubmit(
        target: ReaderProgressSyncTarget,
        position: ReaderPositionLocalState,
    ) {
        require(position.resourceId == target.resourceId) {
            "Reader position resource does not match its target"
        }
        require(position.clientId.isNotBlank()) { "Reader position client id is blank" }
        val pending = position.toMutation(createMutationId())
        stateStore.commitPositionAndPending(position, pending)
        dismissRemotePositionNotice()
        launchDrain(target)
    }

    suspend fun retryPending(target: ReaderProgressSyncTarget) {
        val state = stateStore.loadPositionSyncState()
        if (state.pending != null && state.terminalFailureCode == null) launchDrain(target)
    }

    fun beginSession(snapshot: ReaderProgressSnapshotV5?) {
        baselineRevision = maxOf(baselineRevision, snapshot?.revision ?: 0)
        dismissRemotePositionNotice()
    }

    fun remotePositionNotice(): ReaderRemotePositionNoticeV5? = remoteNotice

    /** GET/bootstrapped state is presentation only until the user chooses it. */
    suspend fun observeRemotePosition(
        snapshot: ReaderProgressSnapshotV5,
        currentClientId: String,
    ): ReaderRemotePositionNoticeV5? {
        if (snapshot.revision <= baselineRevision) return remoteNotice
        baselineRevision = snapshot.revision
        if (snapshot.clientId == currentClientId) return remoteNotice
        remoteNotice = ReaderRemotePositionNoticeV5(snapshot)
        _remotePositionNotices.value = remoteNotice
        return remoteNotice
    }

    fun dismissRemotePositionNotice() {
        remoteNotice = null
        _remotePositionNotices.value = null
    }

    /** Saves a selected remote report after the SDK accepted its opaque locator. */
    suspend fun acceptRemotePosition(
        position: ReaderPositionLocalState,
        snapshot: ReaderProgressSnapshotV5,
    ) {
        require(position.resourceId == snapshot.resourceId)
        stateStore.acceptRemotePosition(position, snapshot)
        baselineRevision = maxOf(baselineRevision, snapshot.revision)
        dismissRemotePositionNotice()
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
                val state = stateStore.loadPositionSyncState()
                val next = state.pending
                if (next == null || state.terminalFailureCode != null) {
                    if (finishIfNotWoken(ownedWorker, observedWakeGeneration)) return
                    continue
                }
                val result = try {
                    server.push(ReaderPositionUpload(target, next))
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Throwable) {
                    ReaderPositionPushResult.RetryableFailure("NETWORK_UNAVAILABLE")
                }
                when (result) {
                    is ReaderPositionPushResult.Accepted -> {
                        val response = result.response
                        if (response.acceptedMutationId != next.mutationId) {
                            // A response for another mutation is not an
                            // acknowledgement of this durable body. Leave the
                            // pending row intact and stop automatic retries
                            // until the malformed server response is visible.
                            stateStore.recordPositionTerminalFailure(
                                next.mutationId,
                                "INVALID_PROGRESS_RESPONSE",
                            )
                        } else {
                            baselineRevision = maxOf(baselineRevision, response.acceptedRevision)
                            stateStore.acknowledgePosition(response.acceptedMutationId, response)
                        }
                    }
                    is ReaderPositionPushResult.RetryableFailure -> {
                        if (finishIfNotWoken(ownedWorker, observedWakeGeneration)) return
                    }
                    is ReaderPositionPushResult.Rejected -> {
                        stateStore.recordPositionTerminalFailure(next.mutationId, result.failureCode)
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

class LocalFirstReaderPositionStore(
    private val stateStore: ReaderPositionSyncStateStore,
    private val target: ReaderProgressSyncTarget,
    private val coordinator: ReaderPositionSyncCoordinator,
) : ReaderPositionSyncingStore {
    override suspend fun load(resourceId: String): ReaderPositionLocalState? = stateStore.loadPosition(resourceId)

    override suspend fun save(position: ReaderPositionLocalState) =
        coordinator.saveLocalAndSubmit(target, position)

    override suspend fun delete(resourceId: String) = stateStore.deletePosition(resourceId)

    override suspend fun awaitPendingUpload() = coordinator.awaitIdle()

    override suspend fun retryPendingUpload() = coordinator.retryPending(target)

    override suspend fun syncState(): ReaderPositionDurableState = stateStore.loadPositionSyncState()
}

/** Swift-friendly owner for the v5 coordinator and its coroutine lifetime. */
class ReaderPositionSyncRuntime(
    stateStore: ReaderPositionSyncStateStore,
    target: ReaderProgressSyncTarget,
    server: ReaderPositionServerPort,
) {
    private val scope = MainScope()
    val coordinator = ReaderPositionSyncCoordinator(stateStore, server, scope)
    val store: ReaderPositionSyncingStore = LocalFirstReaderPositionStore(stateStore, target, coordinator)

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
