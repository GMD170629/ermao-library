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
    val workId: String,
    val volumeId: String,
) {
    init {
        require(clientId.isNotBlank()) { "Reader local client id is blank" }
        require(workId.isNotBlank()) { "Reader local work id is blank" }
        require(volumeId.isNotBlank()) { "Reader local volume id is blank" }
    }

    val stableKey: String
        get() = lengthPrefixed(
            namespace.serverIdentity,
            namespace.userId,
            clientId,
            workId,
            volumeId,
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
    val clientId: String,
    val revision: Long,
    val locator: PublicationLocation,
    val displayPercent: Double,
    val receivedAtEpochMillis: Long,
    /** Original client capture time; absent on older Reader v4 servers. */
    val capturedAtEpochMillis: Long? = null,
) {
    constructor(
        sourceId: String,
        clientId: String,
        revision: Long,
        locator: ReadiumLocatorEnvelope,
        displayPercent: Double,
        receivedAtEpochMillis: Long,
        capturedAtEpochMillis: Long? = null,
    ) : this(
        sourceId,
        clientId,
        revision,
        ReflowablePublicationLocation(locator.asEngineLocator()),
        displayPercent,
        receivedAtEpochMillis,
        capturedAtEpochMillis,
    )
    init {
        require(sourceId.isNotBlank()) { "Reader snapshot source id is blank" }
        require(clientId.isNotBlank()) { "Reader snapshot client id is blank" }
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

/** Session-only presentation state. It is reconstructed from bootstrap/progress GET after restart. */
data class ReaderRemoteProgressNotice(
    val snapshot: ReaderProgressSnapshotV4,
) {
    val revision: Long get() = snapshot.revision
    val sourceClientId: String get() = snapshot.clientId
}

data class ReaderProgressMutation(
    val sourceId: String,
    val clientId: String,
    val mutationId: String,
    val baseRevision: Long,
    val capturedAtEpochMillis: Long,
    val locator: PublicationLocation,
) {
    constructor(
        sourceId: String,
        clientId: String,
        mutationId: String,
        baseRevision: Long,
        capturedAtEpochMillis: Long,
        locator: ReadiumLocatorEnvelope,
    ) : this(
        sourceId,
        clientId,
        mutationId,
        baseRevision,
        capturedAtEpochMillis,
        ReflowablePublicationLocation(locator.asEngineLocator()),
    )
    init {
        require(sourceId.isNotBlank()) { "Reader mutation source id is blank" }
        require(clientId.isNotBlank()) { "Reader mutation client id is blank" }
        require(mutationId.isNotBlank()) { "Reader mutation id is blank" }
        require(baseRevision >= 0) { "Reader mutation base revision is negative" }
        require(capturedAtEpochMillis >= 0) { "Reader mutation timestamp is negative" }
    }
}

fun ReaderProgress.exactPublicationLocation(): PublicationLocation = when (val exact = location) {
    is ReflowReaderLocation -> ReflowablePublicationLocation(
        engineLocator = exact.engineLocator
            ?: throw IllegalArgumentException("Reflowable progress does not contain an engine locator"),
    )
    is PdfReaderLocation -> PdfPublicationLocation(
        pageIndex = exact.pageIndex,
        pageProgression = exact.pageProgression,
        engineLocator = exact.engineLocator,
    )
    is ComicReaderLocation -> ComicPublicationLocation(
        resourceHref = exact.resourceHref,
        pageIndex = exact.pageIndex,
        engineLocator = exact.engineLocator,
    )
    is AudioReaderLocation -> AudioPublicationLocation(
        fileId = exact.fileId,
        chapterId = exact.chapterId,
        positionMillis = exact.positionMillis,
        engineLocator = exact.engineLocator,
    )
}

@Deprecated("Use exactPublicationLocation", ReplaceWith("exactPublicationLocation()"))
fun ReaderProgress.exactLocatorEnvelope(): ReadiumLocatorEnvelope =
    (exactPublicationLocation() as? ReflowablePublicationLocation)?.readiumEnvelope
        ?: throw IllegalArgumentException("Reader progress is not reflowable")

fun ReaderProgress.toMutation(
    baseRevision: Long,
    mutationId: String,
): ReaderProgressMutation = ReaderProgressMutation(
    sourceId = sourceId,
    clientId = deviceId,
    mutationId = mutationId,
    baseRevision = baseRevision,
    capturedAtEpochMillis = updatedAtEpochMillis,
    locator = exactPublicationLocation(),
)

private fun lengthPrefixed(vararg values: String): String = buildString {
    values.forEach { value ->
        append(value.length)
        append(':')
        append(value)
    }
}
