package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget

/** One best-effort Reader v4 overwrite prepared after the exact local save succeeds. */
data class ReaderProgressUpload(
    val target: ReaderProgressSyncTarget,
    val snapshot: ReaderProgressSnapshotV4,
    val localLocation: ReaderLocation,
) {
    init {
        require(snapshot.sourceId == target.volumeId) { "Reader snapshot source does not match its volume" }
        require(snapshot.serverContentFingerprint == target.serverContentFingerprint) {
            "Reader snapshot server fingerprint does not match its target"
        }
    }
}

sealed interface ReaderProgressPushResult {
    data class Accepted(val snapshot: ReaderProgressSnapshotV4) : ReaderProgressPushResult

    /** Failures are observable to callers but are never persisted or retried by Reader v4. */
    data class Discarded(val failureCode: String) : ReaderProgressPushResult {
        init {
            require(failureCode.isNotBlank())
        }
    }
}

fun interface ReaderProgressSyncPort {
    suspend fun push(upload: ReaderProgressUpload): ReaderProgressPushResult
}

interface ReaderProgressSyncingStore : ReaderProgressStore {
    /** Waits only for the current in-memory request/slot; it never retries a failure. */
    suspend fun awaitPendingUpload()
}
