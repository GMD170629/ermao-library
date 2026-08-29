package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.reader.domain.toMutation
import com.ermao.library.shared.modules.reader.domain.exactPublicationLocation
import com.ermao.library.shared.modules.reader.domain.compareExactProgressLocations

typealias ReaderAdmission = com.ermao.library.shared.modules.reader.application.ReaderAdmission
typealias ReaderLaunchCoordinator = com.ermao.library.shared.modules.reader.application.ReaderLaunchCoordinator
typealias ReaderLaunch = com.ermao.library.shared.modules.reader.application.ReaderLaunch
typealias ReaderLaunchStream = com.ermao.library.shared.modules.reader.application.ReaderLaunch.Stream
typealias ReaderLaunchLocal = com.ermao.library.shared.modules.reader.application.ReaderLaunch.Local
typealias ReaderLaunchDownload = com.ermao.library.shared.modules.reader.application.ReaderLaunch.Download
typealias ReaderLaunchUnavailable = com.ermao.library.shared.modules.reader.application.ReaderLaunch.Unavailable
typealias ReaderDeliveryMode = com.ermao.library.shared.modules.reader.domain.ReaderDeliveryMode

typealias Fb2PublicationDecoder = com.ermao.library.shared.modules.reader.infrastructure.Fb2PublicationDecoder
typealias MobiMarkupEnvelope = com.ermao.library.shared.modules.reader.infrastructure.MobiMarkupEnvelope
typealias Fb2XmlPolicy = com.ermao.library.shared.modules.reader.infrastructure.Fb2XmlPolicy
typealias Fb2ImageLink = com.ermao.library.shared.modules.reader.infrastructure.Fb2ImageLink
typealias Fb2PublicationDocument = com.ermao.library.shared.modules.reader.infrastructure.Fb2PublicationDocument
typealias Fb2NavigationEntry = com.ermao.library.shared.modules.reader.infrastructure.Fb2NavigationEntry

typealias ComicReaderLocation = com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
typealias AudioReaderLocation = com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
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
typealias ReaderPanel = com.ermao.library.shared.modules.reader.domain.ReaderPanel
typealias ReaderControl = com.ermao.library.shared.modules.reader.domain.ReaderControl
typealias ReaderControlAvailability = com.ermao.library.shared.modules.reader.domain.ReaderControlAvailability
typealias ReaderControlState = com.ermao.library.shared.modules.reader.domain.ReaderControlState

fun resolveReaderControlContext(
    control: ReaderControl, morphology: ReaderMorphology, capabilities: ReaderCapabilities,
    ready: Boolean, scrolling: Boolean, nativeUnavailable: Set<ReaderControl>,
): ReaderControlAvailability = com.ermao.library.shared.modules.reader.domain.resolveReaderControlContext(
    control, morphology, capabilities, ready, scrolling, nativeUnavailable,
)

fun resolveReaderControl(
    control: ReaderControl,
    morphology: ReaderMorphology,
    capabilities: ReaderCapabilities,
    preferences: ReaderPreferences,
    ready: Boolean,
    nativeUnavailable: Set<ReaderControl> = emptySet(),
): ReaderControlAvailability = com.ermao.library.shared.modules.reader.domain.resolveReaderControl(
    control, morphology, capabilities, preferences, ready, nativeUnavailable,
)

fun resetReaderPreferences(): ReaderPreferences =
    com.ermao.library.shared.modules.reader.domain.resetReaderPreferences()

fun readerPlatformCapabilities(
    morphology: ReaderMorphology,
    volumeKeys: Boolean,
    pdfFit: Boolean,
): ReaderCapabilities {
    val reflowable = ReaderCapabilities.epub(supportsVolumeKeys = volumeKeys)
    if (morphology == ReaderMorphology.Reflowable) return reflowable
    return reflowable.copy(
        supportsBookmarks = false, supportsFontSize = false, supportsFontFamily = false,
        supportsFontWeight = false, supportsLineHeight = false, supportsPositiveLetterSpacing = false,
        supportsPageMargins = false, supportsPageWidth = true, supportsReadingMode = false, supportsSpreadMode = false,
        supportsParagraphLayout = false, supportsPublisherStyles = false,
        supportsPageTurnAnimation = false, supportsPdfFit = morphology == ReaderMorphology.Pdf && pdfFit,
    )
}
typealias ReaderError = com.ermao.library.shared.modules.reader.domain.ReaderError
typealias ReaderErrorCode = com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
fun readerErrorCodeForFailure(failureCode: String, recoverable: Boolean): ReaderErrorCode =
    com.ermao.library.shared.modules.reader.domain.readerErrorCodeForFailure(failureCode, recoverable)
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
typealias ReaderComicPreferences = com.ermao.library.shared.modules.reader.domain.ReaderComicPreferences
typealias ReaderComicDirection = com.ermao.library.shared.modules.reader.domain.ReaderComicDirection
typealias ReaderComicSpreadMode = com.ermao.library.shared.modules.reader.domain.ReaderComicSpreadMode
typealias ReaderComicImageFit = com.ermao.library.shared.modules.reader.domain.ReaderComicImageFit
typealias ReaderComicImageVariant = com.ermao.library.shared.modules.reader.domain.ReaderComicImageVariant
typealias ReaderPdfPreferences = com.ermao.library.shared.modules.reader.domain.ReaderPdfPreferences
typealias ReaderPdfFit = com.ermao.library.shared.modules.reader.domain.ReaderPdfFit
typealias ReaderPdfFlow = com.ermao.library.shared.modules.reader.domain.ReaderPdfFlow
typealias ReaderPdfCropMargins = com.ermao.library.shared.modules.reader.domain.ReaderPdfCropMargins
typealias ReaderMorphology = com.ermao.library.shared.modules.reader.domain.ReaderMorphology
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
typealias ReaderRemoteProgressNotice = com.ermao.library.shared.modules.reader.domain.ReaderRemoteProgressNotice
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
typealias ReaderCommandCompleted =
    com.ermao.library.shared.modules.reader.application.ReaderCommandResult.Completed
typealias ReaderCommandRejected =
    com.ermao.library.shared.modules.reader.application.ReaderCommandResult.Rejected
typealias ReaderDeviceIdentity = com.ermao.library.shared.modules.reader.application.ReaderDeviceIdentity
typealias ReaderEnginePort = com.ermao.library.shared.modules.reader.application.ReaderEnginePort
typealias ReaderOpenRequest = com.ermao.library.shared.modules.reader.application.ReaderOpenRequest
typealias ReaderProgressStore = com.ermao.library.shared.modules.reader.application.ReaderProgressStore
typealias ReaderProgressUpload = com.ermao.library.shared.modules.reader.application.ReaderProgressUpload
typealias ReaderProgressPushResult =
    com.ermao.library.shared.modules.reader.application.ReaderProgressPushResult
typealias ReaderProgressSyncPort = com.ermao.library.shared.modules.reader.application.ReaderProgressSyncPort
typealias ReaderProgressQueryPort = com.ermao.library.shared.modules.reader.application.ReaderProgressQueryPort
typealias ReaderProgressQueryResult = com.ermao.library.shared.modules.reader.application.ReaderProgressQueryResult
typealias ReaderProgressServerPort = com.ermao.library.shared.modules.reader.application.ReaderProgressServerPort
typealias ReaderProgressSyncRuntime = com.ermao.library.shared.modules.reader.application.ReaderProgressSyncRuntime
typealias ReaderDeviceLabelResolver = com.ermao.library.shared.modules.reader.application.ReaderDeviceLabelResolver
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
typealias ReaderNavigationUnit = com.ermao.library.shared.modules.reader.application.ReaderNavigationUnit
typealias ReaderBootstrapResult = com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult
typealias ReaderBootstrapContent =
    com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult.Content
typealias ReaderBootstrapFailure =
    com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult.Failure
typealias ReaderBootstrapGateway = com.ermao.library.shared.modules.reader.application.ReaderBootstrapGateway
typealias ReaderBootstrapResource =
    com.ermao.library.shared.modules.reader.application.ReaderBootstrapResource
typealias ReaderComicPage = com.ermao.library.shared.modules.reader.application.ReaderComicPage
typealias ReaderPdfPage = com.ermao.library.shared.modules.reader.application.ReaderPdfPage
typealias ReaderPublicationBootstrapResult =
    com.ermao.library.shared.modules.reader.application.ReaderPublicationBootstrapResult
typealias PdfRangeServerPort = com.ermao.library.shared.modules.reader.application.PdfRangeServerPort
typealias PdfRangeProbeResult = com.ermao.library.shared.modules.reader.application.PdfRangeProbeResult
typealias PdfRangeReadResult = com.ermao.library.shared.modules.reader.application.PdfRangeReadResult
typealias BootstrapReaderPublication =
    com.ermao.library.shared.modules.reader.application.BootstrapReaderPublication
typealias ReaderPublicationBootstrapContent =
    com.ermao.library.shared.modules.reader.application.ReaderPublicationBootstrapResult.Content
typealias ReaderPublicationBootstrapFailure =
    com.ermao.library.shared.modules.reader.application.ReaderPublicationBootstrapResult.Failure
typealias RemoteByteRangeReaderSource =
    com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
typealias RemoteComicReaderSource =
    com.ermao.library.shared.modules.reader.domain.RemoteComicReaderSource
typealias RemoteComicPage = com.ermao.library.shared.modules.reader.domain.RemoteComicPage
typealias ReaderComicAccess = com.ermao.library.shared.modules.reader.application.ReaderComicAccess
typealias ComicPageServerPort = com.ermao.library.shared.modules.reader.application.ComicPageServerPort
typealias ComicPageReadResult = com.ermao.library.shared.modules.reader.application.ComicPageReadResult
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
typealias PendingVsServerDecision =
    com.ermao.library.shared.modules.reader.application.PendingVsServerDecision
typealias ReaderTocEntry = com.ermao.library.shared.modules.reader.application.ReaderTocEntry
typealias ReaderNavigationTarget = com.ermao.library.shared.modules.reader.application.ReaderNavigationTarget

fun matchesReaderNavigationHref(currentHref: String, expectedHref: String, fragments: Set<String>, cssSelector: String?): Boolean =
    com.ermao.library.shared.modules.reader.domain.matchesReaderNavigationHref(currentHref, expectedHref, fragments, cssSelector)
typealias ReaderNavigationResult = com.ermao.library.shared.modules.reader.application.ReaderNavigationResult
typealias ReaderNavigationTargetReflowable =
    com.ermao.library.shared.modules.reader.application.ReaderNavigationTarget.Reflowable
typealias ReaderNavigationTargetPdf =
    com.ermao.library.shared.modules.reader.application.ReaderNavigationTarget.Pdf
typealias ReaderNavigationTargetComic =
    com.ermao.library.shared.modules.reader.application.ReaderNavigationTarget.Comic
typealias ReaderNavigationTargetInvalid =
    com.ermao.library.shared.modules.reader.application.ReaderNavigationTarget.Invalid
typealias ReaderNavigationCompleted =
    com.ermao.library.shared.modules.reader.application.ReaderNavigationResult.Completed
typealias ReaderNavigationRejected =
    com.ermao.library.shared.modules.reader.application.ReaderNavigationResult.Rejected
typealias ReaderProgressJson = com.ermao.library.shared.modules.reader.infrastructure.ReaderProgressJson
typealias ReaderProgressSyncStateJson =
    com.ermao.library.shared.modules.reader.infrastructure.ReaderProgressSyncStateJson
typealias ReaderPreferencesJson =
    com.ermao.library.shared.modules.reader.infrastructure.ReaderPreferencesJson

/** Swift cannot call the Kotlin constructor whose only parameter has a default value. */
fun createReaderProgressJson(): ReaderProgressJson = ReaderProgressJson()

fun createReaderProgressSyncStateJson(): ReaderProgressSyncStateJson = ReaderProgressSyncStateJson()

fun createReaderProgressSyncRuntime(
    stateStore: ReaderProgressSyncStateStore,
    target: ReaderProgressSyncTarget,
    server: ReaderProgressServerPort,
): ReaderProgressSyncRuntime = ReaderProgressSyncRuntime(stateStore, target, server)

fun createReaderPreferencesJson(): ReaderPreferencesJson = ReaderPreferencesJson()

fun createReaderSyncNamespace(
    serverIdentity: String,
    userId: String,
    authorizationVersion: Long,
): ReaderSyncNamespace = ReaderSyncNamespace(serverIdentity, userId, authorizationVersion)

fun createReaderLocalProgressIdentity(
    namespace: ReaderSyncNamespace,
    clientId: String,
    bookId: String,
    resourceId: String,
): ReaderLocalProgressIdentity = ReaderLocalProgressIdentity(
    namespace,
    clientId,
    bookId,
    resourceId,
)

fun createEngineLocator(
    engine: ReaderEngine,
    platform: ReaderEnginePlatform,
    version: String,
    payloadJson: String,
): EngineLocator = EngineLocator(engine, platform, version, EngineLocatorPayload.parse(payloadJson))

fun createReaderProgressPresentationUpdate(
    namespaceKey: String,
    bookId: String,
    resourceId: String,
    percent: Double,
    progress: ReaderProgress,
    chapterTitle: String?,
): ReaderProgressPresentationUpdate = ReaderProgressPresentationUpdate(
    namespaceKey = namespaceKey,
    bookId = bookId,
    resourceId = resourceId,
    percent = percent,
    location = progress.exactPublicationLocation(),
    chapterTitle = chapterTitle,
    capturedAtEpochMillis = progress.updatedAtEpochMillis,
)

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

fun compareExactProgressReadiumLocators(
    expected: ReadiumLocatorEnvelope,
    recaptured: ReadiumLocatorEnvelope,
): ExactBlockMatch = com.ermao.library.shared.modules.reader.domain.compareExactProgressReadiumBlocks(expected, recaptured)

fun compareExactReaderProgress(
    expected: ReaderProgress,
    recaptured: ReaderProgress,
): ExactLocationMatch = runCatching {
    compareExactProgressLocations(expected.exactPublicationLocation(), recaptured.exactPublicationLocation())
}.getOrDefault(ExactLocationMatch.AnchorMismatch)

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

fun decidePendingVsServerStartup(
    localProgress: ReaderProgress?,
    durableState: ReaderProgressDurableState,
    remoteSnapshot: ReaderProgressSnapshotV4?,
    openedSource: ReaderSource,
): PendingVsServerDecision =
    com.ermao.library.shared.modules.reader.application.decidePendingVsServerStartup(
        localProgress,
        durableState,
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

fun resolveReaderChapterStatesFromLocation(
    units: List<ReaderChapterUnit>,
    location: PublicationLocation,
    progressPercent: Double,
): List<ReaderChapterState> =
    com.ermao.library.shared.modules.reader.domain.resolveReaderChapterStatesFromLocation(
        units,
        location,
        progressPercent,
    )

fun resolveReflowableTotalProgressionFromNavigation(
    orderedResourceHrefs: List<String>,
    resourceHref: String?,
    resourceProgression: Double?,
    totalProgression: Double?,
): Double? = com.ermao.library.shared.modules.reader.domain.resolveReflowableTotalProgressionFromNavigation(
    orderedResourceHrefs,
    resourceHref,
    resourceProgression,
    totalProgression,
)

fun readingUnitLaunchTarget(readerType: String, href: String?, pageNumber: Int?): ReaderNavigationTarget =
    com.ermao.library.shared.modules.reader.application.readingUnitLaunchTarget(readerType, href, pageNumber)

fun encodeReaderLaunchTarget(target: ReaderNavigationTarget): String =
    com.ermao.library.shared.modules.reader.application.encodeReaderLaunchTarget(target)

fun decodeReaderLaunchTarget(payload: String?): ReaderNavigationTarget? =
    com.ermao.library.shared.modules.reader.application.decodeReaderLaunchTarget(payload)

fun mergeReaderPreferenceChanges(base: ReaderPreferences, requested: ReaderPreferences, current: ReaderPreferences): ReaderPreferences =
    com.ermao.library.shared.modules.reader.domain.mergeReaderPreferenceChanges(base, requested, current)

fun changedReaderControls(before: ReaderPreferences, after: ReaderPreferences): Set<ReaderControl> =
    com.ermao.library.shared.modules.reader.domain.changedReaderControls(before, after)

typealias ReaderPdfAccess = com.ermao.library.shared.modules.reader.application.ReaderPdfAccess

typealias PdfRangeMemory = com.ermao.library.shared.modules.reader.application.PdfRangeMemory

typealias PdfRangeLoader = com.ermao.library.shared.modules.reader.application.PdfRangeLoader
typealias PdfRangeFailure = com.ermao.library.shared.modules.reader.application.PdfRangeFailure

typealias ReaderFormatSupport = com.ermao.library.shared.modules.reader.domain.ReaderFormatSupport

typealias TxtPublicationEmptyException = com.ermao.library.shared.modules.reader.domain.TxtPublicationEmptyException

typealias ReaderSettingDefinition = com.ermao.library.shared.modules.reader.domain.ReaderSettingDefinition
typealias ReaderSettingSection = com.ermao.library.shared.modules.reader.domain.ReaderSettingSection
typealias ReaderSettingsCatalog = com.ermao.library.shared.modules.reader.domain.ReaderSettingsCatalog
