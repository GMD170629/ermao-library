import { comicVisualSpreadPages } from '../../../../lib/comic-reading-order';

export type ComicPageMeta = {
  pageIndex: number;
  title?: string;
  mimeType?: string;
  width?: number | null;
  height?: number | null;
  size?: number | null;
};

export type ComicImageFit = 'width' | 'height' | 'contain' | 'original';

export function comicPageSlotSizing(mode: 'single' | 'double') {
  const width = mode === 'double' ? '50%' : '100%';
  return { flex: mode === 'double' ? '1 1 50%' : '0 1 100%', maxWidth: width, width };
}

export function comicImageSizing(fit: ComicImageFit, layoutMode: 'single' | 'double' = 'single') {
  const doublePage = layoutMode === 'double';
  return {
    display: 'block',
    height: doublePage && fit !== 'original' ? '100%' : fit === 'height' || fit === 'contain' ? '100%' : 'auto',
    maxHeight: '100%',
    maxWidth: '100%',
    objectFit: 'contain',
    width: doublePage ? 'auto' : fit === 'width' || fit === 'contain' ? '100%' : 'auto'
  } as const;
}

export function comicOrderedPages(pageCount: number) {
  return Array.from({ length: Math.max(0, Math.round(pageCount)) }, (_, index) => index + 1);
}

export function comicSpreadStarts(orderedPages: number[], mode: 'single' | 'double') {
  if (mode === 'single') return [...orderedPages];
  if (!orderedPages.length) return [];
  const firstPage = orderedPages[0];
  return orderedPages.filter((page) => (page - firstPage) % 2 === 0);
}

export function comicNormalizePage(orderedPages: number[], page: number, mode: 'single' | 'double') {
  if (!orderedPages.length) return 1;
  const clamped = Math.max(orderedPages[0], Math.min(orderedPages.at(-1) ?? orderedPages[0], Math.round(page || 1)));
  if (mode === 'single') return clamped;
  const firstPage = orderedPages[0];
  return (clamped - firstPage) % 2 === 0 ? clamped : clamped - 1;
}

export function comicAdjacentSpreadPage(orderedPages: number[], page: number, mode: 'single' | 'double', offset: -1 | 1) {
  const starts = comicSpreadStarts(orderedPages, mode);
  const current = comicNormalizePage(orderedPages, page, mode);
  const index = Math.max(0, starts.indexOf(current));
  return starts[index + offset] ?? current;
}

export function comicLastSpreadPage(orderedPages: number[], mode: 'single' | 'double') {
  return comicSpreadStarts(orderedPages, mode).at(-1) ?? 1;
}

export function comicSpreadPages(orderedPages: number[], page: number, mode: 'single' | 'double') {
  const normalized = comicNormalizePage(orderedPages, page, mode);
  const index = orderedPages.indexOf(normalized);
  if (index < 0) return [];
  if (mode === 'single') return [normalized];
  return orderedPages.slice(index, index + 2);
}

export function comicVisualPages(orderedPages: number[], page: number, mode: 'single' | 'double', direction: 'ltr' | 'rtl') {
  return comicVisualSpreadPages(comicSpreadPages(orderedPages, page, mode), direction);
}

/** Current spread plus exactly one adjacent spread on either side. */
export function comicCacheWindow(orderedPages: number[], page: number, mode: 'single' | 'double') {
  const current = comicNormalizePage(orderedPages, page, mode);
  const previous = comicAdjacentSpreadPage(orderedPages, current, mode, -1);
  const next = comicAdjacentSpreadPage(orderedPages, current, mode, 1);
  return [...new Set([
    ...comicSpreadPages(orderedPages, previous, mode),
    ...comicSpreadPages(orderedPages, current, mode),
    ...comicSpreadPages(orderedPages, next, mode)
  ])].sort((left, right) => left - right);
}

export function comicPreloadWindow(orderedPages: number[], page: number, mode: 'single' | 'double') {
  const current = comicNormalizePage(orderedPages, page, mode);
  const next = comicAdjacentSpreadPage(orderedPages, current, mode, 1);
  const previous = comicAdjacentSpreadPage(orderedPages, current, mode, -1);
  const visible = new Set(comicSpreadPages(orderedPages, current, mode));
  return [...new Set([
    ...comicSpreadPages(orderedPages, next, mode),
    ...comicSpreadPages(orderedPages, previous, mode)
  ])].filter((candidate) => !visible.has(candidate));
}

export function comicPagePercent(page: number, orderedPages: number[], mode: 'single' | 'double' = 'single') {
  if (!orderedPages.length) return 0;
  if (orderedPages.length === 1) return 100;
  const visibleLastPage = comicSpreadPages(orderedPages, page, mode).at(-1) ?? page;
  const index = Math.max(0, orderedPages.indexOf(visibleLastPage));
  return (index / (orderedPages.length - 1)) * 100;
}

export function comicPageForProgress(progression: number, orderedPages: number[]) {
  if (!orderedPages.length) return 1;
  const index = Math.round(Math.max(0, Math.min(1, progression)) * (orderedPages.length - 1));
  return orderedPages[index] ?? orderedPages[0];
}
