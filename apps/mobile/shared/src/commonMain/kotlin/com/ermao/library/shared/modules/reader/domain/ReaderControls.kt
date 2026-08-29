package com.ermao.library.shared.modules.reader.domain

/** Task semantics only; each platform owns its native sheet and focus behavior. */
enum class ReaderPanel { Contents, Bookmarks, Appearance, Settings }

enum class ReaderControl {
    Previous, Next, Progress, Contents, Bookmarks, Annotations,
    Theme, SystemTheme, FontSize, FontFamily, FontWeight, LineHeight,
    LetterSpacing, NegativeLetterSpacing, PageMargins, PageWidth,
    ReadingMode, Spread, ParagraphIndent, ParagraphSpacing, TextAlignment,
    PublisherStyles, SmartOptimization,
    DeduplicateIndent, IndentUnindented, ProgressStyle, Clock, KeepAwake,
    TapZones, Swipe, CommandAnimation, Keyboard, VolumeKeys,
    ComicZoom, ComicFit, ComicQuality, ComicDirection, ComicCoverSingle, ComicPageGap, PdfZoom, PdfFit, PdfRotation, PdfCrop,
}

enum class ReaderControlAvailability {
    Available, TemporarilyUnavailable, NotImplemented, NotApplicable,
}

data class ReaderControlState(val control: ReaderControl, val availability: ReaderControlAvailability)

/** An SDK adapter supplies publication-specific limitations, without leaking SDK types. */
fun resolveReaderControl(
    control: ReaderControl,
    morphology: ReaderMorphology,
    capabilities: ReaderCapabilities,
    preferences: ReaderPreferences,
    ready: Boolean,
    nativeUnavailable: Set<ReaderControl> = emptySet(),
): ReaderControlAvailability = resolveReaderControlContext(
    control, morphology, capabilities, ready,
    when (morphology) {
        ReaderMorphology.Reflowable -> preferences.epub.flow == ReaderReadingMode.ContinuousScroll
        ReaderMorphology.Comic -> preferences.comic.flow == ReaderReadingMode.ContinuousScroll
        ReaderMorphology.Pdf -> false
    },
    nativeUnavailable,
).let { availability ->
    if (availability != ReaderControlAvailability.Available) return@let availability
    when {
        morphology == ReaderMorphology.Reflowable && preferences.epub.typography.preservePublisherStyles &&
            control in PUBLISHER_OWNED_CONTROLS -> ReaderControlAvailability.TemporarilyUnavailable
        morphology == ReaderMorphology.Reflowable && !preferences.epub.optimization.enabled &&
            control in SMART_OPTIMIZATION_CHILD_CONTROLS -> ReaderControlAvailability.TemporarilyUnavailable
        morphology == ReaderMorphology.Comic && preferences.comic.flow == ReaderReadingMode.ContinuousScroll &&
            control in COMIC_PAGINATED_CONTROLS -> ReaderControlAvailability.TemporarilyUnavailable
        morphology == ReaderMorphology.Comic && control == ReaderControl.ComicCoverSingle &&
            preferences.comic.spreadMode != ReaderComicSpreadMode.Double -> ReaderControlAvailability.TemporarilyUnavailable
        else -> availability
    }
}

fun resolveReaderControlContext(
    control: ReaderControl,
    morphology: ReaderMorphology,
    capabilities: ReaderCapabilities,
    ready: Boolean,
    scrolling: Boolean,
    nativeUnavailable: Set<ReaderControl>,
): ReaderControlAvailability {
    if (control in REFLOW_CONTROLS && morphology != ReaderMorphology.Reflowable ||
        control in COMIC_CONTROLS && morphology != ReaderMorphology.Comic ||
        control in PDF_CONTROLS && morphology != ReaderMorphology.Pdf
    ) return ReaderControlAvailability.NotApplicable
    if (control !in capabilities.supportedControls) return ReaderControlAvailability.NotImplemented
    if (!ready || control in nativeUnavailable) return ReaderControlAvailability.TemporarilyUnavailable
    if (morphology == ReaderMorphology.Reflowable) {
        if (control == ReaderControl.Spread && scrolling) {
            return ReaderControlAvailability.TemporarilyUnavailable
        }
    }
    return ReaderControlAvailability.Available
}

/** Reset all reading formats in the current local account namespace. */
fun resetReaderPreferences(): ReaderPreferences = ReaderPreferences()

/** Stable control-set contract consumed by native presentation adapters. */
val ReaderCapabilities.supportedControls: Set<ReaderControl>
    get() = ReaderControl.entries.filterTo(linkedSetOf()) { supportsDeclaredControl(it) }

private fun ReaderCapabilities.supportsDeclaredControl(control: ReaderControl): Boolean = when (control) {
    ReaderControl.Previous -> canGoPrevious
    ReaderControl.Next -> canGoNext
    ReaderControl.Progress -> canGoPrevious || canGoNext
    ReaderControl.Contents -> hasTableOfContents
    ReaderControl.Bookmarks -> supportsBookmarks
    ReaderControl.Annotations -> supportsAnnotations
    ReaderControl.Theme -> supportsTheme
    ReaderControl.SystemTheme -> supportsSystemTheme
    ReaderControl.FontSize -> supportsFontSize
    ReaderControl.FontFamily -> supportsFontFamily
    ReaderControl.FontWeight -> supportsFontWeight
    ReaderControl.LineHeight -> supportsLineHeight
    ReaderControl.LetterSpacing -> supportsPositiveLetterSpacing
    ReaderControl.NegativeLetterSpacing -> supportsNegativeLetterSpacing
    ReaderControl.PageMargins -> supportsPageMargins
    ReaderControl.PageWidth -> supportsPageWidth
    ReaderControl.ReadingMode -> supportsReadingMode
    ReaderControl.Spread -> supportsSpreadMode
    ReaderControl.ParagraphIndent, ReaderControl.ParagraphSpacing, ReaderControl.TextAlignment -> supportsParagraphLayout
    ReaderControl.PublisherStyles -> supportsPublisherStyles
    ReaderControl.SmartOptimization, ReaderControl.DeduplicateIndent, ReaderControl.IndentUnindented -> supportsSmartOptimization
    ReaderControl.ProgressStyle -> supportsProgressStyles
    ReaderControl.Clock -> supportsClock
    ReaderControl.KeepAwake -> supportsKeepAwake
    ReaderControl.TapZones -> supportsTapZones
    ReaderControl.Swipe -> supportsSwipeToggle
    ReaderControl.CommandAnimation -> supportsPageTurnAnimation
    ReaderControl.Keyboard -> supportsKeyboardPageTurn
    ReaderControl.VolumeKeys -> supportsVolumeKeyPageTurn
    ReaderControl.ComicDirection -> supportsComicDirection
    ReaderControl.ComicCoverSingle -> supportsComicCoverSingle
    ReaderControl.ComicPageGap -> supportsComicPageGap
    ReaderControl.ComicZoom, ReaderControl.ComicFit, ReaderControl.ComicQuality -> false
    ReaderControl.PdfZoom -> supportsPdfZoomPreference
    ReaderControl.PdfFit -> supportsPdfFit
    ReaderControl.PdfRotation -> supportsPdfRotation
    ReaderControl.PdfCrop -> supportsPdfCropMargins
}

private val REFLOW_CONTROLS = setOf(
    ReaderControl.FontSize, ReaderControl.FontFamily, ReaderControl.FontWeight, ReaderControl.LineHeight,
    ReaderControl.LetterSpacing, ReaderControl.NegativeLetterSpacing, ReaderControl.PageMargins,
    ReaderControl.ParagraphIndent, ReaderControl.ParagraphSpacing,
    ReaderControl.TextAlignment, ReaderControl.PublisherStyles,
    ReaderControl.SmartOptimization, ReaderControl.DeduplicateIndent,
    ReaderControl.IndentUnindented,
)
private val COMIC_CONTROLS = setOf(ReaderControl.ComicDirection, ReaderControl.ComicCoverSingle, ReaderControl.ComicPageGap)
private val PDF_CONTROLS = setOf(ReaderControl.PdfZoom, ReaderControl.PdfFit, ReaderControl.PdfRotation, ReaderControl.PdfCrop)
private val PUBLISHER_OWNED_CONTROLS = setOf(
    ReaderControl.FontFamily, ReaderControl.FontWeight, ReaderControl.LetterSpacing,
    ReaderControl.LineHeight, ReaderControl.ParagraphIndent, ReaderControl.ParagraphSpacing,
    ReaderControl.TextAlignment,
)
private val SMART_OPTIMIZATION_CHILD_CONTROLS = setOf(ReaderControl.DeduplicateIndent, ReaderControl.IndentUnindented)
private val COMIC_PAGINATED_CONTROLS = setOf(
    ReaderControl.Spread, ReaderControl.ComicDirection, ReaderControl.ComicCoverSingle, ReaderControl.ComicPageGap,
)
