package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.reader.domain.toServerSnapshot

typealias ComicReaderLocation = com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
typealias AudioReaderLocation = com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
typealias ContentFingerprint = com.ermao.library.shared.modules.reader.domain.ContentFingerprint
typealias EngineLocator = com.ermao.library.shared.modules.reader.domain.EngineLocator
typealias EngineLocatorPayload = com.ermao.library.shared.modules.reader.domain.EngineLocatorPayload
typealias ReaderEngine = com.ermao.library.shared.modules.reader.domain.ReaderEngine
typealias ReaderEnginePlatform = com.ermao.library.shared.modules.reader.domain.ReaderEnginePlatform
typealias LocalReaderSource = com.ermao.library.shared.modules.reader.domain.LocalReaderSource
typealias PdfReaderLocation = com.ermao.library.shared.modules.reader.domain.PdfReaderLocation
typealias ReaderCapabilities = com.ermao.library.shared.modules.reader.domain.ReaderCapabilities
typealias ReaderError = com.ermao.library.shared.modules.reader.domain.ReaderError
typealias ReaderErrorCode = com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
typealias ReaderFormat = com.ermao.library.shared.modules.reader.domain.ReaderFormat
typealias ReaderLocation = com.ermao.library.shared.modules.reader.domain.ReaderLocation
typealias ReaderPreferences = com.ermao.library.shared.modules.reader.domain.ReaderPreferences
typealias ReaderProgress = com.ermao.library.shared.modules.reader.domain.ReaderProgress
typealias ReaderProgressSnapshotV4 = com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
typealias ReaderLocalProgressIdentity = com.ermao.library.shared.modules.reader.domain.ReaderLocalProgressIdentity
typealias ReaderPublicAnchor = com.ermao.library.shared.modules.reader.domain.ReaderPublicAnchor
typealias ReaderProgressSyncTarget = com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
typealias ReaderServerContentFingerprint =
    com.ermao.library.shared.modules.reader.domain.ReaderServerContentFingerprint
typealias ReaderSyncNamespace = com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
typealias ReaderReadingMode = com.ermao.library.shared.modules.reader.domain.ReaderReadingMode
typealias ReaderSession = com.ermao.library.shared.modules.reader.domain.ReaderSession
typealias ReaderSessionPhase = com.ermao.library.shared.modules.reader.domain.ReaderSessionPhase
typealias ReaderSource = com.ermao.library.shared.modules.reader.domain.ReaderSource
typealias ReaderTextAlignment = com.ermao.library.shared.modules.reader.domain.ReaderTextAlignment
typealias ReaderTheme = com.ermao.library.shared.modules.reader.domain.ReaderTheme
typealias ReflowReaderLocation = com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
typealias TextQuote = com.ermao.library.shared.modules.reader.domain.TextQuote
typealias ReaderClock = com.ermao.library.shared.modules.reader.application.ReaderClock
typealias ReaderCommandResult = com.ermao.library.shared.modules.reader.application.ReaderCommandResult
typealias ReaderDeviceIdentity = com.ermao.library.shared.modules.reader.application.ReaderDeviceIdentity
typealias ReaderEnginePort = com.ermao.library.shared.modules.reader.application.ReaderEnginePort
typealias ReaderOpenRequest = com.ermao.library.shared.modules.reader.application.ReaderOpenRequest
typealias ReaderProgressStore = com.ermao.library.shared.modules.reader.application.ReaderProgressStore
typealias ReaderProgressUpload = com.ermao.library.shared.modules.reader.application.ReaderProgressUpload
typealias ReaderProgressPushResult =
    com.ermao.library.shared.modules.reader.application.ReaderProgressPushResult
typealias ReaderProgressSyncPort = com.ermao.library.shared.modules.reader.application.ReaderProgressSyncPort
typealias ReaderProgressSyncingStore =
    com.ermao.library.shared.modules.reader.application.ReaderProgressSyncingStore
typealias ReaderProgressSyncCoordinator =
    com.ermao.library.shared.modules.reader.application.ReaderProgressSyncCoordinator
typealias LocalFirstReaderProgressStore =
    com.ermao.library.shared.modules.reader.application.LocalFirstReaderProgressStore
typealias ReaderBootstrapRequest = com.ermao.library.shared.modules.reader.application.ReaderBootstrapRequest
typealias ReaderBootstrap = com.ermao.library.shared.modules.reader.application.ReaderBootstrap
typealias ReaderBootstrapResult = com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult
typealias ReaderBootstrapGateway = com.ermao.library.shared.modules.reader.application.ReaderBootstrapGateway
typealias ReaderPublicationDownload =
    com.ermao.library.shared.modules.reader.application.ReaderPublicationDownload
typealias ReaderPublicationBootstrapResult =
    com.ermao.library.shared.modules.reader.application.ReaderPublicationBootstrapResult
typealias PublicationDownloadSink =
    com.ermao.library.shared.modules.reader.application.PublicationDownloadSink
typealias PublicationDownloadSinkFactory =
    com.ermao.library.shared.modules.reader.application.PublicationDownloadSinkFactory
typealias PublicationDownloadPort =
    com.ermao.library.shared.modules.reader.application.PublicationDownloadPort
typealias PublicationDownloadResult =
    com.ermao.library.shared.modules.reader.application.PublicationDownloadResult
typealias ReaderServerGateway = com.ermao.library.shared.modules.reader.application.ReaderServerGateway
typealias BootstrapReaderPublication =
    com.ermao.library.shared.modules.reader.application.BootstrapReaderPublication
typealias ReaderPublicationBootstrapContent =
    com.ermao.library.shared.modules.reader.application.ReaderPublicationBootstrapResult.Content
typealias ReaderPublicationBootstrapFailure =
    com.ermao.library.shared.modules.reader.application.ReaderPublicationBootstrapResult.Failure
typealias ReaderRestoreCandidate = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate
typealias ReaderRestoreExactEngineLocation = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.ExactEngineLocation
typealias ReaderRestoreExactLocalLocation = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.ExactLocalLocation
typealias ReaderRestorePublicEngineLocator = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.PublicEngineLocator
typealias ReaderRestoreResourceProgression = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.ResourceProgression
typealias ReaderRestoreQuotedText = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.QuotedText
typealias ReaderRestorePosition = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.Position
typealias ReaderRestorePdfPage = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.PdfPage
typealias ReaderRestoreComicPage = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.ComicPage
typealias ReaderRestoreAudioPosition = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.AudioPosition
typealias ReaderRestoreTotalProgression = com.ermao.library.shared.modules.reader.application.ReaderRestoreCandidate.TotalProgression
typealias ReaderProgressRestorePlan = com.ermao.library.shared.modules.reader.application.ReaderProgressRestorePlan
typealias ReaderTocEntry = com.ermao.library.shared.modules.reader.application.ReaderTocEntry
typealias ReaderProgressJson = com.ermao.library.shared.modules.reader.infrastructure.ReaderProgressJson

fun createReaderSyncNamespace(
    serverIdentity: String,
    userId: String,
    authorizationVersion: Long,
): ReaderSyncNamespace = ReaderSyncNamespace(serverIdentity, userId, authorizationVersion)

fun createReaderLocalProgressIdentity(
    namespace: ReaderSyncNamespace,
    clientId: String,
    volumeId: String,
    localContentFingerprint: ContentFingerprint,
): ReaderLocalProgressIdentity = ReaderLocalProgressIdentity(
    namespace,
    clientId,
    volumeId,
    localContentFingerprint,
)

fun createEngineLocator(
    engine: ReaderEngine,
    platform: ReaderEnginePlatform,
    version: String,
    payloadJson: String,
): EngineLocator = EngineLocator(engine, platform, version, EngineLocatorPayload.parse(payloadJson))

/** Swift-friendly canonical v4 projection; native stores need not duplicate anchor/percent mapping. */
fun createReaderProgressUpload(
    target: ReaderProgressSyncTarget,
    progress: ReaderProgress,
): ReaderProgressUpload = ReaderProgressUpload(
    target = target,
    snapshot = progress.toServerSnapshot(target.serverContentFingerprint),
    localLocation = progress.location,
)

/** Rehydrates a validated native snapshot without exposing ServerBaseUrl construction to Swift. */
fun createReaderServerProfile(
    id: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    isActive: Boolean,
    acceptsInsecureTls: Boolean,
): ServerProfile {
    val parsed = ServerBaseUrl.parse(baseUrl)
    val validatedBaseUrl = (parsed as? ServerBaseUrlParseResult.Valid)?.baseUrl
        ?: throw IllegalArgumentException("Reader server base URL is invalid")
    return ServerProfile(
        id = id,
        displayName = displayName,
        baseUrl = validatedBaseUrl,
        serverIdentity = serverIdentity,
        isActive = isActive,
        tlsMode = if (acceptsInsecureTls) TlsMode.InsecureSkipAllValidation else TlsMode.SystemTrust,
    )
}

fun restoreReaderLocationCandidates(
    savedLocation: ReaderLocation,
    openedSource: ReaderSource,
): List<ReaderRestoreCandidate> =
    com.ermao.library.shared.modules.reader.application.restoreCandidates(savedLocation, openedSource)

fun planReaderProgressRestore(
    localProgress: ReaderProgress?,
    remoteSnapshot: ReaderProgressSnapshotV4?,
    openedSource: ReaderSource,
): ReaderProgressRestorePlan =
    com.ermao.library.shared.modules.reader.application.planReaderProgressRestore(
        localProgress,
        remoteSnapshot,
        openedSource,
    )
