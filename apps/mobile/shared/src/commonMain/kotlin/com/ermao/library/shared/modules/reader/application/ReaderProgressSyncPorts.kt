package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ReaderProgressMutation
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget

data class ReaderProgressUpload(
    val target: ReaderProgressSyncTarget,
    val mutation: ReaderProgressMutation,
) {
    init {
        require(mutation.sourceId == target.volumeId) { "Reader mutation source does not match its volume" }
    }
}

sealed interface ReaderProgressPushResult {
    data class Accepted(val snapshot: ReaderProgressSnapshotV4) : ReaderProgressPushResult

    data class Conflict(val current: ReaderProgressSnapshotV4) : ReaderProgressPushResult

    /** The pending mutation remains durable and may be retried after connectivity/auth recovers. */
    data class RetryableFailure(val failureCode: String) : ReaderProgressPushResult {
        init { require(failureCode.isNotBlank()) }
    }

    /** The pending mutation remains visible but is not retried automatically. */
    data class Rejected(val failureCode: String) : ReaderProgressPushResult {
        init { require(failureCode.isNotBlank()) }
    }
}

fun interface ReaderProgressSyncPort {
    suspend fun push(upload: ReaderProgressUpload): ReaderProgressPushResult
}

sealed interface ReaderProgressQueryResult {
    data class Current(val snapshot: ReaderProgressSnapshotV4?, val etag: String?) : ReaderProgressQueryResult
    data class Unchanged(val etag: String?) : ReaderProgressQueryResult
    data class Failure(val failureCode: String, val recoverable: Boolean) : ReaderProgressQueryResult
}

fun interface ReaderProgressQueryPort {
    suspend fun load(target: ReaderProgressSyncTarget, etag: String?): ReaderProgressQueryResult
}

interface ReaderProgressServerPort : ReaderProgressSyncPort, ReaderProgressQueryPort

/** Device directory integration point. A null result is presented as “other device”. */
fun interface ReaderDeviceLabelResolver {
    fun resolve(clientId: String): String?
}

data class ReaderProgressDurableState(
    val confirmedRevision: Long = 0,
    val pending: ReaderProgressMutation? = null,
    val terminalFailureCode: String? = null,
) {
    init {
        require(confirmedRevision >= 0)
        require(terminalFailureCode == null || terminalFailureCode.isNotBlank())
    }
}

/** Platform persistence must implement each method as one local transaction. */
interface ReaderProgressSyncStateStore : ReaderProgressStore {
    suspend fun loadSyncState(): ReaderProgressDurableState

    suspend fun commitProgressAndPending(progress: ReaderProgress, pending: ReaderProgressMutation)

    suspend fun acknowledge(mutationId: String, snapshot: ReaderProgressSnapshotV4)

    /** Drops only the rejected mutation and adopts the newer server revision atomically. */
    suspend fun discardPendingAfterConflict(mutationId: String, serverRevision: Long)

    /** Called only after the Navigator has post-verified the remote exact location. */
    suspend fun acceptRemoteProgress(progress: ReaderProgress, snapshot: ReaderProgressSnapshotV4)

    suspend fun recordTerminalFailure(mutationId: String, failureCode: String)
}

interface ReaderProgressSyncingStore : ReaderProgressStore {
    suspend fun awaitPendingUpload()

    suspend fun retryPendingUpload()

    suspend fun syncState(): ReaderProgressDurableState
}
