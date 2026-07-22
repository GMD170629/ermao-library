import { READER_SCHEMA_VERSION, type ReaderLocation, type ReaderPreferences } from '@shuku/reader-core';
import type { ReaderProgress, ReaderSettings } from '../reader-shell';

export function preferencesToReaderSettings(preferences: ReaderPreferences): ReaderSettings {
  return {
    theme: preferences.appearance.theme,
    fontSize: preferences.epub.fontSize,
    lineHeight: preferences.epub.lineHeight,
    pageWidth: preferences.epub.pageWidth,
    fontFamily: preferences.epub.fontFamily,
    ebookPageTurnAnimation: preferences.epub.pageTurnAnimation,
    ebookSpreadMode: preferences.epub.spreadMode,
    ebookFlow: preferences.epub.flow,
    comicZoom: preferences.comic.zoom,
    pdfZoom: preferences.pdf.zoom,
    comicDirection: preferences.comic.direction,
    comicMode: preferences.comic.mode,
    comicPageTurnAnimation: preferences.comic.pageTurnAnimation,
    imageFit: preferences.comic.imageFit,
    imageVariant: preferences.comic.imageVariant,
    pdfFit: preferences.pdf.fit
  };
}

export function readerSettingsToPreferences(settings: ReaderSettings): ReaderPreferences {
  return {
    schemaVersion: READER_SCHEMA_VERSION,
    appearance: { theme: settings.theme },
    epub: {
      fontSize: settings.fontSize,
      lineHeight: settings.lineHeight,
      pageWidth: settings.pageWidth,
      fontFamily: settings.fontFamily,
      pageTurnAnimation: settings.ebookPageTurnAnimation,
      spreadMode: settings.ebookSpreadMode,
      flow: settings.ebookFlow
    },
    comic: {
      direction: settings.comicDirection,
      mode: settings.comicMode,
      imageFit: settings.imageFit,
      pageTurnAnimation: settings.comicPageTurnAnimation,
      imageVariant: settings.imageVariant,
      zoom: settings.comicZoom
    },
    pdf: {
      zoom: settings.pdfZoom,
      fit: settings.pdfFit
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
