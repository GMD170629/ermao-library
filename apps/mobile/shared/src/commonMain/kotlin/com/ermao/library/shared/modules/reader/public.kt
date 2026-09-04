package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode

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
typealias LocalReaderSource = com.ermao.library.shared.modules.reader.domain.LocalReaderSource
typealias PdfReaderLocation = com.ermao.library.shared.modules.reader.domain.PdfReaderLocation
typealias ReaderCapabilities = com.ermao.library.shared.modules.reader.domain.ReaderCapabilities
typealias ReaderPanel = com.ermao.library.shared.modules.reader.domain.ReaderPanel
typealias ReaderControl = com.ermao.library.shared.modules.reader.domain.ReaderControl
typealias ReaderControlAvailability = com.ermao.library.shared.modules.reader.domain.ReaderControlAvailability
typealias ReaderSettingState = com.ermao.library.shared.modules.reader.domain.ReaderSettingState

fun resetReaderPreferences(): ReaderPreferences =
    com.ermao.library.shared.modules.reader.domain.resetReaderPreferences()

fun comicOrderedPages(pageCount: Int): List<Int> =
    com.ermao.library.shared.modules.reader.domain.comicOrderedPages(pageCount)

fun comicSpreadStarts(
    orderedPages: List<Int>,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): List<Int> = com.ermao.library.shared.modules.reader.domain.comicSpreadStarts(orderedPages, mode, pairing)

fun comicNormalizePage(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): Int = com.ermao.library.shared.modules.reader.domain.comicNormalizePage(orderedPages, page, mode, pairing)

fun comicSpreadPages(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): List<Int> = com.ermao.library.shared.modules.reader.domain.comicSpreadPages(orderedPages, page, mode, pairing)

fun comicVisualPages(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    direction: ReaderComicDirection,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): List<Int> = com.ermao.library.shared.modules.reader.domain.comicVisualPages(
    orderedPages,
    page,
    mode,
    direction,
    pairing,
)

fun comicNavigationPrevious(): ComicNavigationCommand =
    com.ermao.library.shared.modules.reader.domain.ComicNavigationCommand.Previous

fun comicNavigationNext(): ComicNavigationCommand =
    com.ermao.library.shared.modules.reader.domain.ComicNavigationCommand.Next

fun comicNavigationGoToIndex(pageIndex: Int): ComicNavigationCommand =
    com.ermao.library.shared.modules.reader.domain.ComicNavigationCommand.GoToIndex(pageIndex)

fun comicNavigationGoToProgress(progression: Double): ComicNavigationCommand =
    com.ermao.library.shared.modules.reader.domain.ComicNavigationCommand.GoToProgress(progression)

fun readerPlatformCapabilities(
    morphology: ReaderMorphology,
    volumeKeys: Boolean,
    pdfZoom: Boolean,
    pdfFit: Boolean,
    comic: ReaderComicCapabilities = ReaderComicCapabilities(),
): ReaderCapabilities {
    val reflowable = ReaderCapabilities.epub(supportsVolumeKeys = volumeKeys)
    if (morphology == ReaderMorphology.Reflowable) return reflowable
    val comicSurface = morphology == ReaderMorphology.Comic
    return reflowable.copy(
        supportsBookmarks = false, supportsFontSize = false, supportsFontFamily = false,
        supportsFontWeight = false, supportsLineHeight = false, supportsPositiveLetterSpacing = false,
        supportsPageMargins = false,
        supportsPageWidth = !comicSurface || comic.supportsPageWidth,
        supportsReadingMode = comicSurface && comic.supportsFlow,
        supportsSpreadMode = comicSurface && comic.supportsSpread,
        supportsParagraphLayout = false, supportsPublisherStyles = false,
        supportsPageTurnAnimation = comicSurface && comic.supportsAnimation,
        supportsReadingProgression = false, supportsWritingMode = false,
        supportsComicDirection = comicSurface && comic.supportsDirection,
        supportsComicCoverSingle = comicSurface && comic.supportsCoverSingle,
        supportsComicPageGap = comicSurface && comic.supportsPageGap,
        comic = if (comicSurface) comic else ReaderComicCapabilities(),
        supportsPdfFit = morphology == ReaderMorphology.Pdf && pdfFit,
        supportsPdfZoomPreference = morphology == ReaderMorphology.Pdf && pdfZoom,
    )
}
typealias ReaderError = com.ermao.library.shared.modules.reader.domain.ReaderError
typealias ReaderErrorCode = com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
typealias ReaderLocationRestoreException =
    com.ermao.library.shared.modules.reader.domain.ReaderLocationRestoreException
typealias ReaderSafetyFacade = com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
typealias ReaderSafetyPolicy = com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
typealias ReaderSafetyAction = com.ermao.library.shared.modules.reader.domain.ReaderSafetyAction
typealias ReaderSafetyRuleId = com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
typealias ReaderSafetyBudgetName = com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
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
typealias ReaderComicCapabilities = com.ermao.library.shared.modules.reader.domain.ReaderComicCapabilities
typealias ReaderComicDirection = com.ermao.library.shared.modules.reader.domain.ReaderComicDirection
typealias ReaderComicSpreadMode = com.ermao.library.shared.modules.reader.domain.ReaderComicSpreadMode
typealias ReaderComicImageFit = com.ermao.library.shared.modules.reader.domain.ReaderComicImageFit
typealias ReaderComicImageVariant = com.ermao.library.shared.modules.reader.domain.ReaderComicImageVariant
typealias ComicPairingPolicy = com.ermao.library.shared.modules.reader.domain.ComicPairingPolicy
typealias ComicViewport = com.ermao.library.shared.modules.reader.domain.ComicViewport
typealias ComicPresentationPlan = com.ermao.library.shared.modules.reader.domain.ComicPresentationPlan
typealias ComicPresentationInput = com.ermao.library.shared.modules.reader.domain.ComicPresentationInput
typealias ComicNavigationCommand = com.ermao.library.shared.modules.reader.domain.ComicNavigationCommand
typealias ComicNavigationResult = com.ermao.library.shared.modules.reader.domain.ComicNavigationResult
typealias ComicReaderRuntime = com.ermao.library.shared.modules.reader.domain.ComicReaderRuntime
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
typealias ReaderProgressPresentationUpdate = com.ermao.library.shared.modules.reader.domain.ReaderProgressPresentationUpdate
typealias ReaderOpaqueLocator = com.ermao.library.shared.modules.reader.domain.ReaderOpaqueLocator
typealias ReaderPositionReport = com.ermao.library.shared.modules.reader.domain.ReaderPositionReport
typealias ReaderPositionPresentation = com.ermao.library.shared.modules.reader.domain.ReaderPositionPresentation
typealias ReaderChapterPresentation = com.ermao.library.shared.modules.reader.domain.ReaderChapterPresentation
typealias ReaderPagePresentation = com.ermao.library.shared.modules.reader.domain.ReaderPagePresentation
typealias ReaderPlaybackPresentation = com.ermao.library.shared.modules.reader.domain.ReaderPlaybackPresentation
typealias ReaderProgressSnapshotV5 = com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV5
typealias ReaderProgressMutationV5 = com.ermao.library.shared.modules.reader.domain.ReaderProgressMutationV5
typealias ReaderPositionLocalState = com.ermao.library.shared.modules.reader.domain.ReaderPositionLocalState
typealias ReaderPositionPresentationSnapshot =
    com.ermao.library.shared.modules.reader.domain.ReaderPositionPresentationSnapshot
typealias ReaderChapterUnit = com.ermao.library.shared.modules.reader.domain.ReaderChapterUnit
typealias ReaderChapterState = com.ermao.library.shared.modules.reader.domain.ReaderChapterState
typealias ReaderChapterListMetadata = com.ermao.library.shared.modules.reader.domain.ReaderChapterListMetadata
typealias ReaderLocalProgressIdentity = com.ermao.library.shared.modules.reader.domain.ReaderLocalProgressIdentity
typealias ReaderProgressSyncTarget = com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
typealias ReaderSyncNamespace = com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
typealias ReaderReadingMode = com.ermao.library.shared.modules.reader.domain.ReaderReadingMode
typealias ReaderSession = com.ermao.library.shared.modules.reader.domain.ReaderSession
typealias ReaderSessionPhase = com.ermao.library.shared.modules.reader.domain.ReaderSessionPhase
typealias ReaderSource = com.ermao.library.shared.modules.reader.domain.ReaderSource
typealias ReaderTextAlignment = com.ermao.library.shared.modules.reader.domain.ReaderTextAlignment
typealias ReaderTheme = com.ermao.library.shared.modules.reader.domain.ReaderTheme

typealias ReflowReaderLocation = com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
typealias ReaderClock = com.ermao.library.shared.modules.reader.application.ReaderClock
typealias ReaderCommandResult = com.ermao.library.shared.modules.reader.application.ReaderCommandResult
typealias ReaderCommandCompleted =
    com.ermao.library.shared.modules.reader.application.ReaderCommandResult.Completed
typealias ReaderCommandRejected =
    com.ermao.library.shared.modules.reader.application.ReaderCommandResult.Rejected
typealias ReaderDeviceIdentity = com.ermao.library.shared.modules.reader.application.ReaderDeviceIdentity
typealias ReaderEnginePort = com.ermao.library.shared.modules.reader.application.ReaderEnginePort
typealias ReaderOpenRequest = com.ermao.library.shared.modules.reader.application.ReaderOpenRequest
typealias ReaderBookmarkSyncPort = com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncPort
typealias ReaderBookmarkSyncResponse = com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncResponse
typealias ReaderBookmark = com.ermao.library.shared.modules.reader.domain.ReaderBookmark
typealias ReaderBookmarkSyncTarget = com.ermao.library.shared.modules.reader.domain.ReaderBookmarkSyncTarget
typealias ReaderPositionUpload = com.ermao.library.shared.modules.reader.application.ReaderPositionUpload
typealias ReaderPositionWriteResponse =
    com.ermao.library.shared.modules.reader.application.ReaderPositionWriteResponse
typealias ReaderPositionPushResult =
    com.ermao.library.shared.modules.reader.application.ReaderPositionPushResult
typealias ReaderPositionSyncPort = com.ermao.library.shared.modules.reader.application.ReaderPositionSyncPort
typealias ReaderPositionQueryPort = com.ermao.library.shared.modules.reader.application.ReaderPositionQueryPort
typealias ReaderPositionQueryResult =
    com.ermao.library.shared.modules.reader.application.ReaderPositionQueryResult
typealias ReaderPositionServerPort =
    com.ermao.library.shared.modules.reader.application.ReaderPositionServerPort
typealias ReaderPositionDurableState =
    com.ermao.library.shared.modules.reader.application.ReaderPositionDurableState
typealias ReaderPositionSyncStateStore =
    com.ermao.library.shared.modules.reader.application.ReaderPositionSyncStateStore
typealias ReaderPositionSyncingStore =
    com.ermao.library.shared.modules.reader.application.ReaderPositionSyncingStore
typealias ReaderPositionSyncCoordinator =
    com.ermao.library.shared.modules.reader.application.ReaderPositionSyncCoordinator
typealias LocalFirstReaderPositionStore =
    com.ermao.library.shared.modules.reader.application.LocalFirstReaderPositionStore
typealias ReaderPositionSyncRuntime =
    com.ermao.library.shared.modules.reader.application.ReaderPositionSyncRuntime
typealias ReaderRemotePositionNoticeV5 =
    com.ermao.library.shared.modules.reader.application.ReaderRemotePositionNoticeV5
typealias ReaderPositionReportJson =
    com.ermao.library.shared.modules.reader.infrastructure.ReaderPositionReportJson
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
typealias ReaderBootstrapBook =
    com.ermao.library.shared.modules.reader.application.ReaderBootstrapBook
typealias ReaderBootstrapAsset =
    com.ermao.library.shared.modules.reader.application.ReaderBootstrapAsset
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
typealias ReaderPositionJson =
    com.ermao.library.shared.modules.reader.infrastructure.ReaderPositionJson
typealias ReaderPositionSyncStateJson =
    com.ermao.library.shared.modules.reader.infrastructure.ReaderPositionSyncStateJson
typealias ReaderPreferencesJson =
    com.ermao.library.shared.modules.reader.infrastructure.ReaderPreferencesJson

fun createReaderPositionJson(): ReaderPositionJson = ReaderPositionJson()

fun createReaderPositionSyncStateJson(): ReaderPositionSyncStateJson = ReaderPositionSyncStateJson()

fun createReaderPositionReportJson(): ReaderPositionReportJson = ReaderPositionReportJson()

fun createReaderPositionSyncRuntime(
    stateStore: ReaderPositionSyncStateStore,
    target: ReaderProgressSyncTarget,
    server: ReaderPositionServerPort,
): ReaderPositionSyncRuntime = ReaderPositionSyncRuntime(stateStore, target, server)

@Throws(IllegalArgumentException::class)
fun createReaderOpaqueLocator(payloadJson: String): ReaderOpaqueLocator =
    ReaderOpaqueLocator.parse(payloadJson)

@Throws(IllegalArgumentException::class)
fun createReaderPositionReport(
    locatorJson: String,
    presentation: ReaderPositionPresentation,
): ReaderPositionReport = ReaderPositionReport(
    locator = ReaderOpaqueLocator.parse(locatorJson),
    presentation = presentation,
)

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

fun createReaderProgressPresentationUpdate(
    namespaceKey: String,
    bookId: String,
    resourceId: String,
    position: ReaderPositionReport,
    capturedAtEpochMillis: Long,
): ReaderProgressPresentationUpdate = ReaderProgressPresentationUpdate(
    namespaceKey = namespaceKey,
    bookId = bookId,
    resourceId = resourceId,
    position = position,
    capturedAtEpochMillis = capturedAtEpochMillis,
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

fun resolveReaderChapterStatesFromPresentation(
    units: List<ReaderChapterUnit>,
    presentation: ReaderPositionPresentation,
): List<ReaderChapterState> =
    com.ermao.library.shared.modules.reader.domain.resolveReaderChapterStatesFromPresentation(
        units,
        presentation,
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
