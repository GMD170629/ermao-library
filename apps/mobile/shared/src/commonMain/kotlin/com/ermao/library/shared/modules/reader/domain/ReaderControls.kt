package com.ermao.library.shared.modules.reader.domain

/** Task semantics only; each platform owns its native sheet and focus behavior. */
enum class ReaderPanel { Contents, Bookmarks, Appearance, Settings }

enum class ReaderControl {
    Previous, Next, Progress, Contents, Bookmarks, Annotations,
    Theme, SystemTheme, FontSize, FontFamily, FontWeight, LineHeight,
    LetterSpacing, NegativeLetterSpacing, PageMargins, PageWidth,
    ReadingMode, Spread, ParagraphIndent, ParagraphSpacing, TextAlignment,
    PublisherStyles, PublisherColors, PublisherFonts, SmartOptimization,
    DeduplicateIndent, IndentUnindented, ProgressStyle, Clock, KeepAwake,
    TapZones, Swipe, CommandAnimation, GestureAnimation, Keyboard, VolumeKeys,
    ComicDirection, ComicCoverSingle, ComicPageGap, PdfZoom, PdfFit, PdfRotation, PdfCrop,
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
    preferences.epub.flow == ReaderReadingMode.ContinuousScroll,
    preferences.epub.typography.preservePublisherStyles, nativeUnavailable,
)

fun resolveReaderControlContext(
    control: ReaderControl,
    morphology: ReaderMorphology,
    capabilities: ReaderCapabilities,
    ready: Boolean,
    scrolling: Boolean,
    publisherStyles: Boolean,
    nativeUnavailable: Set<ReaderControl>,
): ReaderControlAvailability {
    if (control in REFLOW_CONTROLS && morphology != ReaderMorphology.Reflowable ||
        control in COMIC_CONTROLS && morphology != ReaderMorphology.Comic ||
        control in PDF_CONTROLS && morphology != ReaderMorphology.Pdf
    ) return ReaderControlAvailability.NotApplicable
    if (!capabilities.supports(control)) return ReaderControlAvailability.NotImplemented
    if (!ready || control in nativeUnavailable) return ReaderControlAvailability.TemporarilyUnavailable
    if (morphology == ReaderMorphology.Reflowable) {
        if (control == ReaderControl.Spread && scrolling) {
            return ReaderControlAvailability.TemporarilyUnavailable
        }
        if (publisherStyles && control in PUBLISHER_CONFLICTS) {
            return ReaderControlAvailability.TemporarilyUnavailable
        }
    }
    return ReaderControlAvailability.Available
}

/** Reset never changes another morphology's preferences. */
fun resetReaderPreferences(preferences: ReaderPreferences, morphology: ReaderMorphology): ReaderPreferences {
    val defaults = ReaderPreferences()
    return preferences.copy(
        appearance = defaults.appearance,
        display = defaults.display,
        interaction = defaults.interaction,
        epub = if (morphology == ReaderMorphology.Reflowable) defaults.epub else preferences.epub,
        comic = if (morphology == ReaderMorphology.Comic) defaults.comic else preferences.comic,
        pdf = if (morphology == ReaderMorphology.Pdf) defaults.pdf else preferences.pdf,
    )
}

private fun ReaderCapabilities.supports(control: ReaderControl): Boolean = when (control) {
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
    ReaderControl.PublisherColors, ReaderControl.PublisherFonts -> supportsIndependentPublisherStyles
    ReaderControl.SmartOptimization, ReaderControl.DeduplicateIndent, ReaderControl.IndentUnindented -> supportsSmartOptimization
    ReaderControl.ProgressStyle -> supportsProgressStyles
    ReaderControl.Clock -> supportsClock
    ReaderControl.KeepAwake -> supportsKeepAwake
    ReaderControl.TapZones -> supportsTapZones
    ReaderControl.Swipe -> supportsSwipeToggle
    ReaderControl.CommandAnimation -> supportsPageTurnAnimation
    ReaderControl.GestureAnimation -> false
    ReaderControl.Keyboard -> supportsKeyboardPageTurn
    ReaderControl.VolumeKeys -> supportsVolumeKeyPageTurn
    ReaderControl.ComicDirection -> supportsComicDirection
    ReaderControl.ComicCoverSingle -> supportsComicCoverSingle
    ReaderControl.ComicPageGap -> supportsComicPageGap
    ReaderControl.PdfZoom -> supportsPdfZoomPreference
    ReaderControl.PdfFit -> supportsPdfFit
    ReaderControl.PdfRotation -> supportsPdfRotation
    ReaderControl.PdfCrop -> supportsPdfCropMargins
}

private val REFLOW_CONTROLS = setOf(
    ReaderControl.FontSize, ReaderControl.FontFamily, ReaderControl.FontWeight, ReaderControl.LineHeight,
    ReaderControl.LetterSpacing, ReaderControl.NegativeLetterSpacing, ReaderControl.PageMargins,
    ReaderControl.PageWidth, ReaderControl.ParagraphIndent, ReaderControl.ParagraphSpacing,
    ReaderControl.TextAlignment, ReaderControl.PublisherStyles, ReaderControl.PublisherColors,
    ReaderControl.PublisherFonts, ReaderControl.SmartOptimization, ReaderControl.DeduplicateIndent,
    ReaderControl.IndentUnindented,
)
private val COMIC_CONTROLS = setOf(ReaderControl.ComicDirection, ReaderControl.ComicCoverSingle, ReaderControl.ComicPageGap)
private val PDF_CONTROLS = setOf(ReaderControl.PdfZoom, ReaderControl.PdfFit, ReaderControl.PdfRotation, ReaderControl.PdfCrop)
private val PUBLISHER_CONFLICTS = setOf(
    ReaderControl.LineHeight, ReaderControl.LetterSpacing, ReaderControl.ParagraphIndent,
    ReaderControl.ParagraphSpacing, ReaderControl.TextAlignment,
)
