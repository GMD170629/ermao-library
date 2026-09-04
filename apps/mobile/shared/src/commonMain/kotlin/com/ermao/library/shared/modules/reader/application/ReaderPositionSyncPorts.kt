package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.domain.ReaderProgressMutationV5
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.requireReaderMutationId
import kotlinx.coroutines.flow.StateFlow

data class ReaderPositionUpload(
    val target: ReaderProgressSyncTarget,
    val mutation: ReaderProgressMutationV5,
) {
    init {
        require(mutation.resourceId == target.resourceId) {
            "Reader mutation resource does not match its target"
        }
    }
}

data class ReaderPositionWriteResponse(
    val acceptedMutationId: String,
    val acceptedRevision: Long,
    val currentSnapshot: ReaderProgressSnapshotV5,
) {
    init {
        requireReaderMutationId(acceptedMutationId)
        require(acceptedRevision > 0)
    }
}

sealed interface ReaderPositionPushResult {
    data class Accepted(val response: ReaderPositionWriteResponse) : ReaderPositionPushResult

    /** The exact mutation remains durable and is retried after connectivity recovers. */
    data class RetryableFailure(val failureCode: String) : ReaderPositionPushResult {
        init { require(failureCode.isNotBlank()) }
    }

    /** The exact mutation remains visible but is not retried automatically. */
    data class Rejected(val failureCode: String) : ReaderPositionPushResult {
        init { require(failureCode.isNotBlank()) }
    }
}

fun interface ReaderPositionSyncPort {
    suspend fun push(upload: ReaderPositionUpload): ReaderPositionPushResult
}

sealed interface ReaderPositionQueryResult {
    data class Current(val snapshot: ReaderProgressSnapshotV5?, val etag: String?) : ReaderPositionQueryResult
    data class Unchanged(val etag: String?) : ReaderPositionQueryResult
    data class Failure(val failureCode: String, val recoverable: Boolean) : ReaderPositionQueryResult
}

fun interface ReaderPositionQueryPort {
    suspend fun load(target: ReaderProgressSyncTarget, etag: String?): ReaderPositionQueryResult
}

interface ReaderPositionServerPort : ReaderPositionSyncPort, ReaderPositionQueryPort

data class ReaderPositionDurableState(
    val confirmedRevision: Long = 0,
    val pending: ReaderProgressMutationV5? = null,
    val terminalFailureCode: String? = null,
) {
    init {
        require(confirmedRevision >= 0)
        require(terminalFailureCode == null || terminalFailureCode.isNotBlank())
    }
}

/** Durable storage for one v5 resource slot and its latest-only outbox. */
interface ReaderPositionSyncStateStore {
    suspend fun loadPosition(resourceId: String): ReaderPositionLocalState?

    suspend fun savePosition(position: ReaderPositionLocalState)

    suspend fun deletePosition(resourceId: String)

    suspend fun loadPositionSyncState(): ReaderPositionDurableState

    /** Stores the report and replaces the pending mutation in one local transaction. */
    suspend fun commitPositionAndPending(
        position: ReaderPositionLocalState,
        pending: ReaderProgressMutationV5,
    )

    /** Clears only [mutationId]; a newer pending mutation must remain durable. */
    suspend fun acknowledgePosition(
        mutationId: String,
        response: ReaderPositionWriteResponse,
    )

    suspend fun acceptRemotePosition(
        position: ReaderPositionLocalState,
        snapshot: ReaderProgressSnapshotV5,
    )

    suspend fun recordPositionTerminalFailure(mutationId: String, failureCode: String)
}

interface ReaderPositionSyncingStore {
    suspend fun load(resourceId: String): ReaderPositionLocalState?

    suspend fun save(position: ReaderPositionLocalState)

    suspend fun delete(resourceId: String)

    suspend fun awaitPendingUpload()

    suspend fun retryPendingUpload()

    suspend fun syncState(): ReaderPositionDurableState
}

/** Session-only notice. It never navigates the active Reader by itself. */
data class ReaderRemotePositionNoticeV5(val snapshot: ReaderProgressSnapshotV5) {
    val revision: Long get() = snapshot.revision
    val sourceClientId: String get() = snapshot.clientId
    val presentation: com.ermao.library.shared.modules.reader.domain.ReaderPositionPresentation
        get() = snapshot.position.presentation
}
