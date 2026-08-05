import { READER_SCHEMA_VERSION, type ReaderLocation, type ReaderPreferences } from '@shuku/reader-core';
import type { ReaderProgress, ReaderSettings } from '../reader-shell';

export function preferencesToReaderSettings(preferences: ReaderPreferences): ReaderSettings {
  return {
    theme: preferences.appearance.theme,
    manualTheme: preferences.appearance.theme,
    themeMode: preferences.appearance.themeMode,
    progressStyle: preferences.display.progressStyle,
    showClock: preferences.display.showClock,
    tapZones: preferences.interaction.tapZones,
    swipePageTurn: preferences.interaction.swipePageTurn,
    keyboardPageTurn: preferences.interaction.keyboardPageTurn,
    volumeKeyPageTurn: preferences.interaction.volumeKeyPageTurn,
    keepScreenAwake: preferences.interaction.keepScreenAwake,
    fontSize: preferences.epub.fontSize,
    lineHeight: preferences.epub.lineHeight,
    pageWidth: preferences.epub.pageWidth,
    fontFamily: preferences.epub.fontFamily,
    fontWeight: preferences.epub.fontWeight,
    letterSpacing: preferences.epub.letterSpacing,
    pageMargin: preferences.epub.pageMargin,
    ebookPageTurnAnimation: preferences.epub.pageTurnAnimation,
    ebookSpreadMode: preferences.epub.spreadMode,
    ebookFlow: preferences.epub.flow,
    paragraphIndent: preferences.epub.typography.paragraphIndent,
    paragraphSpacing: preferences.epub.typography.paragraphSpacing,
    textAlign: preferences.epub.typography.textAlign,
    preservePublisherStyles: preferences.epub.typography.preservePublisherStyles,
    allowPublisherColors: preferences.epub.typography.allowPublisherColors,
    allowPublisherFonts: preferences.epub.typography.allowPublisherFonts,
    smartOptimization: preferences.epub.optimization.enabled,
    deduplicateIndent: preferences.epub.optimization.deduplicateIndent,
    indentUnindented: preferences.epub.optimization.indentUnindented,
    comicZoom: preferences.comic.zoom,
    pdfZoom: preferences.pdf.zoom,
    comicDirection: preferences.comic.direction,
    comicMode: preferences.comic.mode,
    comicPageTurnAnimation: preferences.comic.pageTurnAnimation,
    imageFit: preferences.comic.imageFit,
    imageVariant: preferences.comic.imageVariant,
    comicFlow: preferences.comic.flow,
    comicCoverSingle: preferences.comic.coverSingle,
    comicPageGap: preferences.comic.pageGap,
    pdfFit: preferences.pdf.fit,
    pdfFlow: preferences.pdf.flow,
    pdfRotation: preferences.pdf.rotation,
    pdfCropMargins: preferences.pdf.cropMargins
  };
}

export function readerSettingsToPreferences(settings: ReaderSettings): ReaderPreferences {
  return {
    schemaVersion: READER_SCHEMA_VERSION,
    appearance: { theme: settings.theme, themeMode: settings.themeMode },
    display: { progressStyle: settings.progressStyle, showClock: settings.showClock },
    interaction: {
      tapZones: settings.tapZones,
      swipePageTurn: settings.swipePageTurn,
      keyboardPageTurn: settings.keyboardPageTurn,
      volumeKeyPageTurn: settings.volumeKeyPageTurn,
      keepScreenAwake: settings.keepScreenAwake
    },
    epub: {
      fontSize: settings.fontSize,
      lineHeight: settings.lineHeight,
      pageWidth: settings.pageWidth,
      fontFamily: settings.fontFamily,
      fontWeight: settings.fontWeight,
      letterSpacing: settings.letterSpacing,
      pageMargin: settings.pageMargin,
      pageTurnAnimation: settings.ebookPageTurnAnimation,
      spreadMode: settings.ebookSpreadMode,
      flow: settings.ebookFlow,
      typography: {
        paragraphIndent: settings.paragraphIndent,
        paragraphSpacing: settings.paragraphSpacing,
        textAlign: settings.textAlign,
        preservePublisherStyles: settings.preservePublisherStyles,
        allowPublisherColors: settings.allowPublisherColors,
        allowPublisherFonts: settings.allowPublisherFonts
      },
      optimization: {
        enabled: settings.smartOptimization,
        deduplicateIndent: settings.deduplicateIndent,
        indentUnindented: settings.indentUnindented
      }
    },
    comic: {
      direction: settings.comicDirection,
      mode: settings.comicMode,
      imageFit: settings.imageFit,
      pageTurnAnimation: settings.comicPageTurnAnimation,
      imageVariant: settings.imageVariant,
      zoom: settings.comicZoom,
      flow: settings.comicFlow,
      coverSingle: settings.comicCoverSingle,
      pageGap: settings.comicPageGap
    },
    pdf: {
      zoom: settings.pdfZoom,
      fit: settings.pdfFit,
      flow: settings.pdfFlow,
      rotation: settings.pdfRotation,
      cropMargins: settings.pdfCropMargins
    }
  };
}

export function locationProgress(location: ReaderLocation | null, percent: number, totalHint?: number | null): ReaderProgress {
  const safePercent = Math.max(0, Math.min(100, Number.isFinite(percent) ? percent : 0));
  if (!location) {
    return { page: 1, total: totalHint ?? null, percent: safePercent, position: '', label: '正在定位' };
  }
  if (location.kind === 'comic') {
    const total = Math.max(1, totalHint ?? location.pageIndex);
    return {
      page: location.pageIndex,
      total,
      percent: safePercent,
      position: String(location.pageIndex),
      label: `第 ${location.pageIndex} / ${total} 页`
    };
  }
  if (location.kind === 'pdf') {
    const total = Math.max(1, totalHint ?? location.pageNumber);
    return {
      page: location.pageNumber,
      total,
      percent: safePercent,
      position: String(location.pageNumber),
      label: `第 ${location.pageNumber} / ${total} 页`
    };
  }
  return {
    // EPUB screen counts are transient layout data and TOC entries are not
    // pages. Keep the legacy shape neutral instead of fabricating either.
    page: 1,
    total: null,
    percent: safePercent,
    position: location.cfi ?? location.href ?? String(location.progression ?? ''),
    label: `全书 ${Math.round(safePercent)}%`
  };
}

export function locationExtra(location: ReaderLocation | null) {
  if (!location) return {};
  if (location.kind === 'reflowable') {
    return {
      readerType: 'reflowable',
      format: location.format,
      cfi: location.cfi,
      currentHref: location.href,
      progression: location.progression,
      chapterIndex: location.foliate?.toc?.index,
      chapterTitle: location.foliate?.toc?.title,
      chapterHref: location.foliate?.toc?.href,
      navigationKey: location.foliate?.toc?.navigationKey,
      navigationFingerprint: location.foliate?.navigationFingerprint,
      sectionIndex: location.foliate?.section?.current,
      sectionTotal: location.foliate?.section?.total,
      locationCurrent: location.foliate?.location?.current,
      locationNext: location.foliate?.location?.next,
      locationTotal: location.foliate?.location?.total,
      remainingSectionSeconds: location.foliate?.remainingSeconds?.section,
      remainingTotalSeconds: location.foliate?.remainingSeconds?.total,
      progressEstimated: false
    };
  }
  if (location.kind === 'epub') {
    return {
      readerType: 'epub',
      cfi: location.cfi,
      currentHref: location.href,
      sectionIndex: location.spineIndex,
      progression: location.progression
    };
  }
  if (location.kind === 'comic') return { readerType: 'comic', volumeId: location.volumeId, pageIndex: location.pageIndex };
  return { readerType: 'pdf', pageIndex: location.pageNumber };
}
