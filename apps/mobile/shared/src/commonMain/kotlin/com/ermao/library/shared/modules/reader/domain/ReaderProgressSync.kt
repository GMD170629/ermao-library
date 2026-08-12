package com.ermao.library.shared.modules.reader.domain

/**
 * Opaque content-version token issued by Reader v4.
 *
 * This is intentionally distinct from [ContentFingerprint]. The server token
 * describes the server's current volume content while [ContentFingerprint]
 * binds a local file to a concrete parser and normalization implementation.
 * Neither value may be inferred from the other.
 */
data class ReaderServerContentFingerprint(val value: String) {
    init {
        require(value.isNotBlank()) { "Reader server content fingerprint is blank" }
        require(value.length <= MAXIMUM_SERVER_FINGERPRINT_LENGTH) {
            "Reader server content fingerprint is too long"
        }
    }

    private companion object {
        const val MAXIMUM_SERVER_FINGERPRINT_LENGTH = 191
    }
}

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

/** Stable exact-local identity. Authorization version and server token are intentionally absent. */
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
    val serverContentFingerprint: ReaderServerContentFingerprint,
) {
    init {
        require(workId.isNotBlank()) { "Reader sync work id is blank" }
        require(volumeId.isNotBlank()) { "Reader sync volume id is blank" }
    }

    val slotKey: String
        get() = lengthPrefixed(
            namespace.stableKey,
            volumeId,
            serverContentFingerprint.value,
        )
}

private fun lengthPrefixed(vararg values: String): String = buildString {
    values.forEach { value ->
        append(value.length)
        append(':')
        append(value)
    }
}

/** Cross-platform anchors which may be attempted in order without claiming local exactness. */
data class ReaderPublicAnchor(
    val format: ReaderFormat = ReaderFormat.Epub,
    val contentFingerprint: ContentFingerprint? = null,
    val engineLocator: EngineLocator? = null,
    val resourceKey: String? = null,
    val progression: Double? = null,
    val textQuote: TextQuote? = null,
    val position: Int? = null,
    /** PDF and comic page numbers are one-based on the server wire. */
    val pageNumber: Int? = null,
    val fileId: String? = null,
    val chapterId: String? = null,
    val positionMillis: Long? = null,
) {
    init {
        require(resourceKey == null || resourceKey.isNotBlank()) { "Reader anchor resource key is blank" }
        require(progression == null || progression.isFinite() && progression in 0.0..1.0) {
            "Reader anchor progression is outside 0..1"
        }
        require(position == null || position > 0) { "Reader anchor position must be positive" }
        require(pageNumber == null || pageNumber > 0) { "Reader anchor page number must be positive" }
        require(fileId == null || fileId.isNotBlank()) { "Reader anchor audio file id is blank" }
        require(chapterId == null || chapterId.isNotBlank()) { "Reader anchor audio chapter id is blank" }
        require(positionMillis == null || positionMillis >= 0) { "Reader anchor audio position is negative" }
        require(
            engineLocator != null || resourceKey != null || progression != null || textQuote != null || position != null ||
                pageNumber != null || fileId != null || positionMillis != null,
        ) {
            "Reader public anchor is empty"
        }
        when (format) {
            ReaderFormat.Pdf, ReaderFormat.Comic -> require(pageNumber != null)
            ReaderFormat.Audio -> require(fileId != null && positionMillis != null)
            else -> require(pageNumber == null && fileId == null && positionMillis == null)
        }
    }
}

/** Reader v4 server snapshot. It deliberately excludes local ContentFingerprint. */
data class ReaderProgressSnapshotV4(
    val sourceId: String,
    val percent: Double,
    val updatedAtEpochMillis: Long,
    val clientId: String,
    val serverContentFingerprint: ReaderServerContentFingerprint,
    val anchor: ReaderPublicAnchor? = null,
) {
    init {
        require(sourceId.isNotBlank()) { "Reader snapshot source id is blank" }
        require(percent.isFinite() && percent in PERCENT_RANGE) { "Reader progress percent is outside 0..100" }
        require(updatedAtEpochMillis >= 0) { "Reader snapshot timestamp is negative" }
        require(clientId.isNotBlank()) { "Reader snapshot client id is blank" }
    }

    private companion object {
        val PERCENT_RANGE = 0.0..100.0
    }
}

fun ReaderProgress.projectedPercent(): Double = when (val currentLocation = location) {
    is ReflowReaderLocation ->
        currentLocation.totalProgression?.times(100.0)?.coerceIn(0.0, 100.0)
            ?: percent
            ?: currentLocation.progression?.times(100.0)?.coerceIn(0.0, 100.0)
            ?: error("Reflow Reader progress requires a whole-volume percent or progression")
    is PdfReaderLocation, is ComicReaderLocation, is AudioReaderLocation ->
        requireNotNull(percent) { "Non-reflow Reader progress requires an explicit whole-volume percent" }
}

fun ReaderProgress.toServerSnapshot(
    serverContentFingerprint: ReaderServerContentFingerprint,
): ReaderProgressSnapshotV4 {
    val reflow = location as? ReflowReaderLocation
    return ReaderProgressSnapshotV4(
        sourceId = sourceId,
        percent = projectedPercent(),
        updatedAtEpochMillis = updatedAtEpochMillis,
        clientId = deviceId,
        serverContentFingerprint = serverContentFingerprint,
        anchor = when (val currentLocation = location) {
            is ReflowReaderLocation -> ReaderPublicAnchor(
                contentFingerprint = currentLocation.contentFingerprint,
                engineLocator = currentLocation.engineLocator,
                resourceKey = currentLocation.resourceKey,
                progression = currentLocation.progression,
                textQuote = currentLocation.textQuote,
                position = currentLocation.position,
            )
            is PdfReaderLocation -> ReaderPublicAnchor(
                format = ReaderFormat.Pdf,
                contentFingerprint = currentLocation.contentFingerprint,
                engineLocator = currentLocation.engineLocator,
                pageNumber = currentLocation.pageIndex + 1,
            )
            is ComicReaderLocation -> ReaderPublicAnchor(
                format = ReaderFormat.Comic,
                contentFingerprint = currentLocation.contentFingerprint,
                engineLocator = currentLocation.engineLocator,
                pageNumber = currentLocation.pageIndex + 1,
            )
            is AudioReaderLocation -> ReaderPublicAnchor(
                format = ReaderFormat.Audio,
                contentFingerprint = currentLocation.contentFingerprint,
                engineLocator = currentLocation.engineLocator,
                fileId = currentLocation.fileId,
                chapterId = currentLocation.chapterId,
                positionMillis = currentLocation.positionMillis,
            )
        },
    )
}
