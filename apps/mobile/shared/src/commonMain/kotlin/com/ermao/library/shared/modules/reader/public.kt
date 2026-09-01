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
typealias ReaderSettingState = com.ermao.library.shared.modules.reader.domain.ReaderSettingState

fun resetReaderPreferences(): ReaderPreferences =
    com.ermao.library.shared.modules.reader.domain.resetReaderPreferences()

fun readerPlatformCapabilities(
    morphology: ReaderMorphology,
    volumeKeys: Boolean,
    pdfZoom: Boolean,
    pdfFit: Boolean,
): ReaderCapabilities {
    val reflowable = ReaderCapabilities.epub(supportsVolumeKeys = volumeKeys)
    if (morphology == ReaderMorphology.Reflowable) return reflowable
    return reflowable.copy(
        supportsBookmarks = false, supportsFontSize = false, supportsFontFamily = false,
        supportsFontWeight = false, supportsLineHeight = false, supportsPositiveLetterSpacing = false,
        supportsPageMargins = false, supportsPageWidth = true, supportsReadingMode = false, supportsSpreadMode = false,
        supportsParagraphLayout = false, supportsPublisherStyles = false,
        supportsPageTurnAnimation = false, supportsReadingProgression = false, supportsWritingMode = false,
        supportsPdfFit = morphology == ReaderMorphology.Pdf && pdfFit,
        supportsPdfZoomPreference = morphology == ReaderMorphology.Pdf && pdfZoom,
    )
}
typealias ReaderError = com.ermao.library.shared.modules.reader.domain.ReaderError
typealias ReaderErrorCode = com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
typealias ReaderSafetyFacade = com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
typealias ReaderSafetyPolicy = com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
typealias ReaderSafetyAction = com.ermao.library.shared.modules.reader.domain.ReaderSafetyAction
typealias ReaderSafetyRuleId = com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
typealias ReaderSafetyFailure = com.ermao.library.shared.modules.reader.domain.ReaderSafetyFailure
typealias ReaderSafetyException = com.ermao.library.shared.modules.reader.domain.ReaderSafetyException
typealias ReaderSafetyImplementationFailure =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyImplementationFailure
typealias ReaderSafetyImplementationException =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyImplementationException
typealias ReaderSanitizedMarkup = com.ermao.library.shared.modules.reader.domain.ReaderSanitizedMarkup
typealias ReaderSafetyMarkupResult = com.ermao.library.shared.modules.reader.domain.ReaderSafetyMarkupResult
typealias ReaderSafetyMarkupAccepted =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyMarkupResult.Accepted
typealias ReaderSafetyMarkupRejected =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyMarkupResult.Rejected

fun readerSafetyOriginalMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES,
    )

fun readerSafetyOriginalMaxBytesFailure(): ReaderSafetyFailure =
    readerSafetyFailure(com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.COMMON_ORIGINAL_MAX_BYTES)

fun readerSafetyBinaryResourceMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.BINARY_RESOURCE_MAX_BYTES,
    )

fun readerSafetyBinaryResourceFailure(): ReaderSafetyFailure =
    readerSafetyFailure(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.COMMON_BINARY_RESOURCE_MAX_BYTES,
    )

fun readerSafetyReflowableMarkupMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES,
    )

fun readerSafetyReflowableMarkupMaxBytesFailure(): ReaderSafetyFailure =
    readerSafetyFailure(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES,
    )

fun readerSafetyDrmFailure(): ReaderSafetyFailure =
    readerSafetyFailure(com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.COMMON_DRM_REJECTED)

fun readerSafetyEpubArchiveEntryMaxCount(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_COUNT,
    )

fun readerSafetyEpubArchiveExpandedMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.ARCHIVE_EXPANDED_MAX_BYTES,
    )

fun readerSafetyEpubArchiveEntryMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_BYTES,
    )

fun readerSafetyEpubArchiveCompressionRatioMax(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.ARCHIVE_COMPRESSION_RATIO_MAX,
    )

fun readerSafetyEpubArchiveFatalFindings(): List<String> =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.reflowableProfile.archiveFatalFindings

fun readerSafetyEpubArchiveStructureFailure(): ReaderSafetyFailure =
    readerSafetyFailure(com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.EPUB_ARCHIVE_STRUCTURE)

fun readerSafetyEpubArchiveEntryCountFailure(): ReaderSafetyFailure =
    readerSafetyFailure(com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.EPUB_ARCHIVE_ENTRY_MAX_COUNT)

fun readerSafetyEpubArchiveExpandedBytesFailure(): ReaderSafetyFailure =
    readerSafetyFailure(com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.EPUB_ARCHIVE_EXPANDED_MAX_BYTES)

fun readerSafetyEpubArchiveEntryBytesFailure(): ReaderSafetyFailure =
    readerSafetyFailure(com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.EPUB_ARCHIVE_ENTRY_MAX_BYTES)

fun readerSafetyEpubArchiveCompressionRatioFailure(): ReaderSafetyFailure =
    readerSafetyFailure(com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.EPUB_ARCHIVE_COMPRESSION_RATIO)

fun readerSafetyFb2TextMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.FB2_TEXT_MAX_BYTES,
    )

/**
 * Bounds the source buffer used by platform FB2 adapters before they materialize the XML text.
 * The budget and rejection outcome remain owned by the generated FB2 structure rule.
 */
fun readerSafetyFb2TextBudgetFailure(sourceByteCount: Long): ReaderSafetyFailure? {
    require(sourceByteCount >= 0L) { "FB2 source byte count must be non-negative" }
    return if (sourceByteCount > readerSafetyFb2TextMaxBytes()) {
        readerSafetyFb2StructureFailure()
    } else {
        null
    }
}

fun readerSafetyFb2DecodedImageMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.FB2_DECODED_IMAGE_MAX_BYTES,
    )

fun readerSafetyFb2DecodedImagesTotalMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.FB2_DECODED_IMAGES_TOTAL_MAX_BYTES,
    )

fun readerSafetyComicPageMaxCount(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.COMIC_PAGE_MAX_COUNT,
    )

fun readerSafetyComicPageMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.COMIC_PAGE_MAX_BYTES,
    )

fun readerSafetyComicManifestMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.COMIC_MANIFEST_MAX_BYTES,
    )

fun readerSafetyComicExpandedMaxBytes(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.COMIC_EXPANDED_MAX_BYTES,
    )

fun readerSafetyComicArchiveStructureFailure(): ReaderSafetyFailure =
    readerSafetyFailure(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
    )

fun readerSafetyComicPageCountFailure(): ReaderSafetyFailure =
    readerSafetyFailure(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.COMIC_PAGE_MAX_COUNT,
    )

fun readerSafetyComicArchiveBudgetFailure(): ReaderSafetyFailure =
    readerSafetyFailure(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.COMIC_ARCHIVE_BUDGET,
    )

fun readerSafetyComicPageBytesFailure(): ReaderSafetyFailure =
    readerSafetyFailure(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.COMIC_PAGE_MAX_BYTES,
    )

/** Maps archive-core detector outcomes to the generated policy owner. */
fun readerSafetyComicArchiveDetectorFailure(stableCode: String): ReaderSafetyFailure? =
    when (stableCode.trim().uppercase()) {
        "ARCHIVE_PATH_INVALID",
        "ARCHIVE_PATH_DUPLICATE",
        "ARCHIVE_HEADER_INVALID",
        "ARCHIVE_DATA_INVALID",
        "ARCHIVE_DATA_TRUNCATED",
        "ARCHIVE_ENTRY_TYPE_INVALID",
        "ARCHIVE_ENCRYPTED",
        -> readerSafetyComicArchiveStructureFailure()
        "ARCHIVE_PAGE_COUNT_EXCEEDED",
        "ARCHIVE_ENTRY_LIMIT_EXCEEDED",
        -> readerSafetyComicPageCountFailure()
        "ARCHIVE_EXPANDED_LIMIT_EXCEEDED",
        "ARCHIVE_COMPRESSION_RATIO_EXCEEDED",
        -> readerSafetyComicArchiveBudgetFailure()
        else -> null
    }

fun readerSafetyPdfPageMaxCount(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.PDF_PAGE_MAX_COUNT,
    )

fun readerSafetyPdfRenderMaxPixels(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.PDF_RENDER_MAX_PIXELS,
    )

fun readerSafetyPdfCanvasMaxDimension(): Long =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.budget(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName.PDF_CANVAS_MAX_DIMENSION,
    )

fun readerSafetyComicPageMimeType(extension: String): String? =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.comicPageMimeType(extension)

fun readerSafetyAllowedComicPageMimeTypes(): List<String> =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.comicProfile.allowedPageMimeTypes

fun readerSafetyFb2EmbeddedImageExtension(mediaType: String): String? =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.fb2EmbeddedImageExtension(mediaType)

fun readerSafetyReadingOrderMarkupMimeTypes(): List<String> =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.reflowableProfile.readingOrderMarkupMimeTypes

fun readerSafetyRequiredReadingOrderMarkupFailure(): ReaderSafetyFailure =
    readerSafetyFailure(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP,
    )

fun readerSafetyComicPageExtensionForMimeType(mediaType: String): String? =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.comicProfile.pageMimeTypesByExtension
        .entries.firstOrNull { (_, mimeType) -> mimeType == mediaType.trim().lowercase() }
        ?.key

fun readerSafetyFb2StructureFailure(): ReaderSafetyFailure =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade().failureFor(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET,
    )

fun readerSafetyPdfPageGeometryFailure(): ReaderSafetyFailure =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade().failureFor(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.PDF_PAGE_GEOMETRY,
    )

fun readerSafetyPdfRenderBudgetFailure(): ReaderSafetyFailure =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade().failureFor(
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.PDF_RENDER_BUDGET,
    )

fun readerSafetyPdfRangeProtocolFailure(): ReaderSafetyFailure =
    readerSafetyFailure(com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.PDF_RANGE_PROTOCOL)

fun readerSafetyPlatformAlgorithmUnsupported(ruleId: String): ReaderSafetyImplementationFailure =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade().platformFailureFor(
        requireNotNull(
            com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.entries.firstOrNull { rule ->
                rule.wireValue == ruleId
            },
        ) { "Unknown Reader safety rule: $ruleId" },
    )

fun readerSafetyEngineAlgorithmUnsupported(ruleId: String): ReaderSafetyImplementationFailure =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade().engineFailureFor(
        requireNotNull(
            com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId.entries.firstOrNull { rule ->
                rule.wireValue == ruleId
            },
        ) { "Unknown Reader safety rule: $ruleId" },
    )

private fun readerSafetyFailure(
    ruleId: com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId,
): ReaderSafetyFailure =
    com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade().failureFor(ruleId)

fun readerSafetySanitizedElementSelectors(): List<String> =
    (com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.reflowableProfile.sanitizedElements +
        com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy.reflowableProfile.svgSanitizedElements)
        .distinct()

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
typealias ReaderWritingMode = com.ermao.library.shared.modules.reader.domain.ReaderWritingMode
typealias ReaderReadingProgression = com.ermao.library.shared.modules.reader.domain.ReaderReadingProgression
typealias ReaderPageTurnDirection = com.ermao.library.shared.modules.reader.domain.ReaderPageTurnDirection
typealias ReaderPhysicalHorizontalSide = com.ermao.library.shared.modules.reader.domain.ReaderPhysicalHorizontalSide
typealias ReaderNavigationPolicy = com.ermao.library.shared.modules.reader.domain.ReaderNavigationPolicy
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
typealias PdfRangeDrainResult = com.ermao.library.shared.modules.reader.application.PdfRangeDrainResult
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
