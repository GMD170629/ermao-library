package com.ermao.library.shared.modules.reader.domain

data class ReaderSyncNamespace(
    val serverIdentity: String,
    val userId: String,
    val authorizationVersion: Long,
) {
    init {
        require(serverIdentity.isNotBlank()) { "Reader sync server identity is blank" }
        require(userId.isNotBlank()) { "Reader sync user identity is blank" }
        require(authorizationVersion >= 0) { "Reader sync authorization version is negative" }
    }

    val stableKey: String
        get() = lengthPrefixed(serverIdentity, userId, authorizationVersion.toString())
}

/** Stable local identity. Authorization changes do not erase an exact location. */
data class ReaderLocalProgressIdentity(
    val namespace: ReaderSyncNamespace,
    val clientId: String,
    val volumeId: String,
    val localContentFingerprint: ContentFingerprint,
) {
    init {
        require(clientId.isNotBlank()) { "Reader local client id is blank" }
        require(volumeId.isNotBlank()) { "Reader local volume id is blank" }
    }

    val stableKey: String
        get() = lengthPrefixed(
            namespace.serverIdentity,
            namespace.userId,
            clientId,
            volumeId,
            localContentFingerprint.originalFileHash,
            localContentFingerprint.parserVersion,
            localContentFingerprint.normalizationVersion,
        )
}

data class ReaderProgressSyncTarget(
    val namespace: ReaderSyncNamespace,
    val workId: String,
    val volumeId: String,
    val sourceFormat: ReaderFormat,
) {
    init {
        require(workId.isNotBlank()) { "Reader sync work id is blank" }
        require(volumeId.isNotBlank()) { "Reader sync volume id is blank" }
    }

    val slotKey: String
        get() = lengthPrefixed(namespace.stableKey, volumeId)
}

/** Exact Reader v4 server state. Percent is a display projection only. */
data class ReaderProgressSnapshotV4(
    val sourceId: String,
    val revision: Long,
    val locator: ReadiumLocatorEnvelope,
    val displayPercent: Double,
    val receivedAtEpochMillis: Long,
    /** Original client capture time; absent on older Reader v4 servers. */
    val capturedAtEpochMillis: Long? = null,
) {
    init {
        require(sourceId.isNotBlank()) { "Reader snapshot source id is blank" }
        require(revision > 0) { "Reader snapshot revision must be positive" }
        require(displayPercent.isFinite() && displayPercent in 0.0..100.0) {
            "Reader display percent is outside 0..100"
        }
        require(receivedAtEpochMillis >= 0) { "Reader server timestamp is negative" }
        require(capturedAtEpochMillis == null || capturedAtEpochMillis >= 0) {
            "Reader capture timestamp is negative"
        }
    }

    val effectiveCapturedAtEpochMillis: Long
        get() = capturedAtEpochMillis ?: receivedAtEpochMillis
}

data class ReaderProgressMutation(
    val sourceId: String,
    val clientId: String,
    val mutationId: String,
    val baseRevision: Long,
    val capturedAtEpochMillis: Long,
    val locator: ReadiumLocatorEnvelope,
) {
    init {
        require(sourceId.isNotBlank()) { "Reader mutation source id is blank" }
        require(clientId.isNotBlank()) { "Reader mutation client id is blank" }
        require(mutationId.isNotBlank()) { "Reader mutation id is blank" }
        require(baseRevision >= 0) { "Reader mutation base revision is negative" }
        require(capturedAtEpochMillis >= 0) { "Reader mutation timestamp is negative" }
    }
}

data class ReaderProgressConflict(
    val pending: ReaderProgressMutation,
    val server: ReaderProgressSnapshotV4,
) {
    init {
        require(pending.sourceId == server.sourceId) { "Reader conflict source ids differ" }
        require(pending.baseRevision < server.revision) { "Reader conflict does not contain a newer server revision" }
    }
}

fun ReaderProgress.exactLocatorEnvelope(): ReadiumLocatorEnvelope {
    val reflow = location as? ReflowReaderLocation
        ?: throw IllegalArgumentException("Reader v4 exact sync currently requires a reflowable Readium location")
    return ReadiumLocatorEnvelope.from(reflow)
        ?: throw IllegalArgumentException("Reader progress does not contain an exact Readium block locator")
}

fun ReaderProgress.toMutation(
    baseRevision: Long,
    mutationId: String,
): ReaderProgressMutation = ReaderProgressMutation(
    sourceId = sourceId,
    clientId = deviceId,
    mutationId = mutationId,
    baseRevision = baseRevision,
    capturedAtEpochMillis = updatedAtEpochMillis,
    locator = exactLocatorEnvelope(),
)

private fun lengthPrefixed(vararg values: String): String = buildString {
    values.forEach { value ->
        append(value.length)
        append(':')
        append(value)
    }
}
