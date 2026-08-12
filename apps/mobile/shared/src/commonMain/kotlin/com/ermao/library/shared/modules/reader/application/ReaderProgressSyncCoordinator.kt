package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.toServerSnapshot
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.coroutines.coroutineContext

/**
 * Reader v4's deliberately ephemeral uploader.
 *
 * There is at most one request in flight. While it runs, newer progress
 * replaces the single pending slot. Success and failure both consume their
 * snapshot; a failure is never turned into durable sync state or retried.
 */
class ReaderProgressSyncCoordinator(
    private val localStore: ReaderProgressStore,
    private val server: ReaderProgressSyncPort,
    private val scope: CoroutineScope,
) {
    private val mutex = Mutex()
    private var pending: ReaderProgressUpload? = null
    private var worker: Job? = null

    suspend fun saveLocalAndSubmit(target: ReaderProgressSyncTarget, progress: ReaderProgress) {
        require(progress.sourceId == target.volumeId) { "Reader progress source does not match its volume" }
        localStore.save(progress)
        val upload = ReaderProgressUpload(
            target = target,
            snapshot = progress.toServerSnapshot(target.serverContentFingerprint),
            localLocation = progress.location,
        )
        mutex.withLock {
            pending = upload
            if (worker?.isActive != true) {
                worker = scope.launch { drain() }
            }
        }
    }

    suspend fun awaitIdle() {
        while (true) {
            val active = mutex.withLock { worker }
            if (active == null) return
            active.join()
        }
    }

    suspend fun cancel() {
        val active = mutex.withLock {
            pending = null
            worker.also { worker = null }
        }
        active?.cancel()
    }

    private suspend fun drain() {
        val runningJob = coroutineContext[Job]
        try {
            while (true) {
                val next = mutex.withLock {
                    val selected = pending
                    pending = null
                    if (selected == null) worker = null
                    selected
                } ?: return
                try {
                    server.push(next)
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Throwable) {
                    // v4 is best effort: the failed snapshot is intentionally discarded.
                }
            }
        } finally {
            mutex.withLock {
                if (worker === runningJob) worker = null
            }
        }
    }
}

class LocalFirstReaderProgressStore(
    private val localStore: ReaderProgressStore,
    private val target: ReaderProgressSyncTarget,
    private val coordinator: ReaderProgressSyncCoordinator,
) : ReaderProgressSyncingStore {
    override suspend fun load(sourceId: String): ReaderProgress? = localStore.load(sourceId)

    override suspend fun save(progress: ReaderProgress) {
        coordinator.saveLocalAndSubmit(target, progress)
    }

    override suspend fun delete(sourceId: String) {
        localStore.delete(sourceId)
    }

    override suspend fun awaitPendingUpload() {
        coordinator.awaitIdle()
    }
}
