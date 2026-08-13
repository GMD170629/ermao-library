package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.reader.domain.toMutation

typealias ComicReaderLocation = com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
typealias AudioReaderLocation = com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
typealias ContentFingerprint = com.ermao.library.shared.modules.reader.domain.ContentFingerprint
typealias PublicationFingerprint = com.ermao.library.shared.modules.reader.domain.PublicationFingerprint
typealias PublicationLocation = com.ermao.library.shared.modules.reader.domain.PublicationLocation
typealias ReflowablePublicationLocation = com.ermao.library.shared.modules.reader.domain.ReflowablePublicationLocation
typealias PdfPublicationLocation = com.ermao.library.shared.modules.reader.domain.PdfPublicationLocation
typealias ComicPublicationLocation = com.ermao.library.shared.modules.reader.domain.ComicPublicationLocation
typealias AudioPublicationLocation = com.ermao.library.shared.modules.reader.domain.AudioPublicationLocation
typealias ExactLocationMatch = com.ermao.library.shared.modules.reader.domain.ExactLocationMatch
typealias ReadiumLocatorEnvelope = com.ermao.library.shared.modules.reader.domain.ReadiumLocatorEnvelope
typealias ExactBlockMatch = com.ermao.library.shared.modules.reader.domain.ExactBlockMatch
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
typealias ReaderSourceFormat = com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
typealias ReaderEngineCapability = com.ermao.library.shared.modules.reader.domain.ReaderEngineCapability
typealias ReaderEngineCapabilityRegistry = com.ermao.library.shared.modules.reader.domain.ReaderEngineCapabilityRegistry
typealias TxtPublicationNormalizer = com.ermao.library.shared.modules.reader.domain.TxtPublicationNormalizer
typealias NormalizedTxtPublication = com.ermao.library.shared.modules.reader.domain.NormalizedTxtPublication
typealias NormalizedTxtResource = com.ermao.library.shared.modules.reader.domain.NormalizedTxtResource
typealias ReaderLocation = com.ermao.library.shared.modules.reader.domain.ReaderLocation
typealias ReaderPreferences = com.ermao.library.shared.modules.reader.domain.ReaderPreferences
typealias ReaderAppearancePreferences = com.ermao.library.shared.modules.reader.domain.ReaderAppearancePreferences
typealias ReaderDisplayPreferences = com.ermao.library.shared.modules.reader.domain.ReaderDisplayPreferences
typealias ReaderInteractionPreferences = com.ermao.library.shared.modules.reader.domain.ReaderInteractionPreferences
typealias ReaderEpubPreferences = com.ermao.library.shared.modules.reader.domain.ReaderEpubPreferences
typealias ReaderTypographyPreferences = com.ermao.library.shared.modules.reader.domain.ReaderTypographyPreferences
typealias ReaderOptimizationPreferences = com.ermao.library.shared.modules.reader.domain.ReaderOptimizationPreferences
typealias ReaderFontFamily = com.ermao.library.shared.modules.reader.domain.ReaderFontFamily
typealias ReaderPageMargin = com.ermao.library.shared.modules.reader.domain.ReaderPageMargin
typealias ReaderSpreadMode = com.ermao.library.shared.modules.reader.domain.ReaderSpreadMode
typealias ReaderPageTurnAnimation = com.ermao.library.shared.modules.reader.domain.ReaderPageTurnAnimation
typealias ReaderProgressStyle = com.ermao.library.shared.modules.reader.domain.ReaderProgressStyle
typealias ReaderTapZones = com.ermao.library.shared.modules.reader.domain.ReaderTapZones
typealias ReaderThemeMode = com.ermao.library.shared.modules.reader.domain.ReaderThemeMode
typealias ReaderProgress = com.ermao.library.shared.modules.reader.domain.ReaderProgress
typealias ReaderProgressSnapshotV4 = com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
typealias ReaderProgressPresentationUpdate = com.ermao.library.shared.modules.reader.domain.ReaderProgressPresentationUpdate
typealias ReaderChapterUnit = com.ermao.library.shared.modules.reader.domain.ReaderChapterUnit
typealias ReaderChapterState = com.ermao.library.shared.modules.reader.domain.ReaderChapterState
typealias ReaderChapterListMetadata = com.ermao.library.shared.modules.reader.domain.ReaderChapterListMetadata
typealias ReaderLocalProgressIdentity = com.ermao.library.shared.modules.reader.domain.ReaderLocalProgressIdentity
typealias ReaderProgressSyncTarget = com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
typealias ReaderProgressMutation = com.ermao.library.shared.modules.reader.domain.ReaderProgressMutation
typealias ReaderProgressConflict = com.ermao.library.shared.modules.reader.domain.ReaderProgressConflict
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
typealias ReaderBookmarkSyncPort = com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncPort
typealias ReaderBookmarkSyncResponse = com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncResponse
typealias ReaderBookmark = com.ermao.library.shared.modules.reader.domain.ReaderBookmark
typealias ReaderBookmarkLocation = com.ermao.library.shared.modules.reader.domain.ReaderBookmarkLocation
typealias ReaderBookmarkSyncTarget = com.ermao.library.shared.modules.reader.domain.ReaderBookmarkSyncTarget
typealias ReaderProgressDurableState =
    com.ermao.library.shared.modules.reader.application.ReaderProgressDurableState
typealias ReaderProgressSyncStateStore =
    com.ermao.library.shared.modules.reader.application.ReaderProgressSyncStateStore
typealias ReaderProgressSyncingStore =
    com.ermao.library.shared.modules.reader.application.ReaderProgressSyncingStore
typealias ReaderProgressSyncCoordinator =
    com.ermao.library.shared.modules.reader.application.ReaderProgressSyncCoordinator
typealias LocalFirstReaderProgressStore =
    com.ermao.library.shared.modules.reader.application.LocalFirstReaderProgressStore
typealias ReaderBootstrapRequest = com.ermao.library.shared.modules.reader.application.ReaderBootstrapRequest
typealias ReaderBootstrap = com.ermao.library.shared.modules.reader.application.ReaderBootstrap
typealias ReaderBootstrapResult = com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult
typealias ReaderBootstrapContent =
    com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult.Content
typealias ReaderBootstrapFailure =
    com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult.Failure
typealias ReaderBootstrapGateway = com.ermao.library.shared.modules.reader.application.ReaderBootstrapGateway
typealias ReaderPublicationDownload =
    com.ermao.library.shared.modules.reader.application.ReaderPublicationDownload
typealias ReaderComicPage = com.ermao.library.shared.modules.reader.application.ReaderComicPage
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
typealias ReaderResumeDecision = com.ermao.library.shared.modules.reader.application.ReaderResumeDecision
typealias ReaderResumeTarget = com.ermao.library.shared.modules.reader.application.ReaderResumeTarget
typealias ReaderResumeSource = com.ermao.library.shared.modules.reader.application.ReaderResumeSource
typealias ReaderTocEntry = com.ermao.library.shared.modules.reader.application.ReaderTocEntry
typealias ReaderProgressJson = com.ermao.library.shared.modules.reader.infrastructure.ReaderProgressJson
typealias ReaderProgressSyncStateJson =
    com.ermao.library.shared.modules.reader.infrastructure.ReaderProgressSyncStateJson
typealias ReaderPreferencesJson =
    com.ermao.library.shared.modules.reader.infrastructure.ReaderPreferencesJson

/** Swift cannot call the Kotlin constructor whose only parameter has a default value. */
fun createReaderProgressJson(): ReaderProgressJson = ReaderProgressJson()

fun createReaderProgressSyncStateJson(): ReaderProgressSyncStateJson = ReaderProgressSyncStateJson()

fun createReaderPreferencesJson(): ReaderPreferencesJson = ReaderPreferencesJson()

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

/** Swift-friendly exact Reader v4 mutation projection. */
fun createReaderProgressUpload(
    target: ReaderProgressSyncTarget,
    progress: ReaderProgress,
    baseRevision: Long,
    mutationId: String,
): ReaderProgressUpload = ReaderProgressUpload(
    target = target,
    mutation = progress.toMutation(baseRevision, mutationId),
)

fun compareExactReadiumLocators(
    expected: ReadiumLocatorEnvelope,
    recaptured: ReadiumLocatorEnvelope,
): ExactBlockMatch = com.ermao.library.shared.modules.reader.domain.compareExactReadiumBlocks(expected, recaptured)

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

fun decideReaderResume(
    localProgress: ReaderProgress?,
    remoteSnapshot: ReaderProgressSnapshotV4?,
    openedSource: ReaderSource,
): ReaderResumeDecision = com.ermao.library.shared.modules.reader.application.decideReaderResume(
    localProgress,
    remoteSnapshot,
    openedSource,
)

fun resolveReaderChapterStates(
    units: List<ReaderChapterUnit>,
    currentHref: String?,
    currentSortOrder: Int?,
    progressPercent: Double,
    metadata: ReaderChapterListMetadata,
): List<ReaderChapterState> = com.ermao.library.shared.modules.reader.domain.resolveReaderChapterStates(
    units,
    currentHref,
    currentSortOrder,
    progressPercent,
    metadata,
)
