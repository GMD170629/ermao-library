package com.ermao.library.shared.modules.reader.domain

/** Task semantics only; each platform owns its native sheet and focus behavior. */
enum class ReaderPanel { Contents, Bookmarks, Appearance, Settings }

enum class ReaderControl {
    Previous, Next, Progress, Contents, Bookmarks, Annotations,
    Theme, SystemTheme, FontSize, FontFamily, FontWeight, LineHeight,
    LetterSpacing, NegativeLetterSpacing, PageMargins, PageWidth,
    ReadingMode, ReadingProgression, WritingMode, Spread, ParagraphIndent, ParagraphSpacing, TextAlignment,
    PublisherStyles, SmartOptimization,
    DeduplicateIndent, IndentUnindented, ProgressStyle, Clock, KeepAwake,
    TapZones, Swipe, CommandAnimation, Keyboard, VolumeKeys,
    ComicZoom, ComicFit, ComicQuality, ComicDirection, ComicCoverSingle, ComicPageGap, PdfZoom, PdfFit, PdfRotation, PdfCrop,
}

enum class ReaderControlAvailability {
    Available, TemporarilyUnavailable, NotImplemented, NotApplicable,
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
    ReaderControl.ReadingProgression -> supportsReadingProgression
    ReaderControl.WritingMode -> supportsWritingMode
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
