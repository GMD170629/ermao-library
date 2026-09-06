import { comicVisualSpreadPages } from '../../../../lib/comic-reading-order';
import { READER_SAFETY_RULES, READER_SAFETY_RULE_IDS } from '@shuku/reader-core';
import type { ReaderSafetyFailure } from '../security/reader-safety-policy';

const COMIC_RESOURCE_CORRUPT = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.COMIC_RESOURCE_INTEGRITY].errorCode;
const PUBLICATION_CORRUPT = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.EPUB_RESOURCE_INTEGRITY].errorCode;
const COMIC_RESOURCE_LIMIT = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.COMIC_PAGE_MAX_COUNT].errorCode;
const COMIC_PAGE_BLOCKED = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.COMIC_PAGE_MAX_BYTES].errorCode;
const COMIC_MIME_MISMATCH = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.COMIC_PAGE_MIME].errorCode;
const COMIC_SECURITY_REJECTED = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.COMIC_ARCHIVE_STRUCTURE].errorCode;
const PUBLICATION_SECURITY_REJECTED = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.REFLOWABLE_REJECT_XML_ENTITY].errorCode;

export function comicSafetyPlaceholderMessage(code: ReaderSafetyFailure['code']): string {
  if (code === COMIC_RESOURCE_CORRUPT || code === PUBLICATION_CORRUPT) {
    return '漫画资源已损坏，无法显示。';
  }
  if (code === COMIC_RESOURCE_LIMIT || code === COMIC_PAGE_BLOCKED) {
    return '漫画资源超过阅读器的处理限制。';
  }
  if (code === COMIC_MIME_MISMATCH) {
    return '漫画页面格式不受当前解码器支持。';
  }
  if (code === COMIC_SECURITY_REJECTED || code === PUBLICATION_SECURITY_REJECTED) {
    return '漫画页面包含无法在当前安全隔离边界内处理的风险内容。';
  }
  return '漫画页面因资源错误无法显示。';
}

export type ComicPageMeta = {
  pageIndex: number;
  resourceHref?: string;
  title?: string;
  mimeType?: string;
  width?: number | null;
  height?: number | null;
  size?: number | null;
  safetyError?: ReaderSafetyFailure;
};

export type ComicImageFit = 'width' | 'height' | 'contain' | 'original';
export type ComicPairingPolicy = 'paired-from-first' | 'cover-single';

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
  return Array.from({ length: Math.max(0, Math.round(pageCount)) }, (_, index) => index);
}

export function comicSpreadStarts(orderedPages: number[], mode: 'single' | 'double', pairing: ComicPairingPolicy = 'paired-from-first') {
  if (mode === 'single') return [...orderedPages];
  if (!orderedPages.length) return [];
  if (pairing === 'cover-single') return orderedPages.filter((_page, index) => index === 0 || index % 2 === 1);
  const firstPage = orderedPages[0];
  return orderedPages.filter((page) => (page - firstPage) % 2 === 0);
}

export function comicNormalizePage(orderedPages: number[], page: number, mode: 'single' | 'double', pairing: ComicPairingPolicy = 'paired-from-first') {
  if (!orderedPages.length) return 0;
  const clamped = Math.max(orderedPages[0], Math.min(orderedPages.at(-1) ?? orderedPages[0], Math.round(Number.isFinite(page) ? page : 0)));
  if (mode === 'single') return clamped;
  if (pairing === 'cover-single') {
    const index = orderedPages.indexOf(clamped);
    if (index <= 0) return orderedPages[0];
    return orderedPages[index % 2 === 1 ? index : index - 1] ?? orderedPages[0];
  }
  const firstPage = orderedPages[0];
  return (clamped - firstPage) % 2 === 0 ? clamped : clamped - 1;
}

export function comicAdjacentSpreadPage(orderedPages: number[], page: number, mode: 'single' | 'double', offset: -1 | 1, pairing: ComicPairingPolicy = 'paired-from-first') {
  const starts = comicSpreadStarts(orderedPages, mode, pairing);
  const current = comicNormalizePage(orderedPages, page, mode, pairing);
  const index = Math.max(0, starts.indexOf(current));
  return starts[index + offset] ?? current;
}

export function comicLastSpreadPage(orderedPages: number[], mode: 'single' | 'double', pairing: ComicPairingPolicy = 'paired-from-first') {
  return comicSpreadStarts(orderedPages, mode, pairing).at(-1) ?? 0;
}

export function comicSpreadPages(orderedPages: number[], page: number, mode: 'single' | 'double', pairing: ComicPairingPolicy = 'paired-from-first') {
  const normalized = comicNormalizePage(orderedPages, page, mode, pairing);
  const index = orderedPages.indexOf(normalized);
  if (index < 0) return [];
  if (mode === 'single') return [normalized];
  if (pairing === 'cover-single' && index === 0) return [normalized];
  return orderedPages.slice(index, index + 2);
}

export function comicVisualPages(orderedPages: number[], page: number, mode: 'single' | 'double', direction: 'ltr' | 'rtl', pairing: ComicPairingPolicy = 'paired-from-first') {
  return comicVisualSpreadPages(comicSpreadPages(orderedPages, page, mode, pairing), direction);
}

/** Current spread plus exactly one adjacent spread on either side. */
export function comicCacheWindow(orderedPages: number[], page: number, mode: 'single' | 'double', pairing: ComicPairingPolicy = 'paired-from-first') {
  const current = comicNormalizePage(orderedPages, page, mode, pairing);
  const previous = comicAdjacentSpreadPage(orderedPages, current, mode, -1, pairing);
  const next = comicAdjacentSpreadPage(orderedPages, current, mode, 1, pairing);
  return [...new Set([
    ...comicSpreadPages(orderedPages, previous, mode, pairing),
    ...comicSpreadPages(orderedPages, current, mode, pairing),
    ...comicSpreadPages(orderedPages, next, mode, pairing)
  ])].sort((left, right) => left - right);
}

export function comicPreloadWindow(orderedPages: number[], page: number, mode: 'single' | 'double', pairing: ComicPairingPolicy = 'paired-from-first') {
  const current = comicNormalizePage(orderedPages, page, mode, pairing);
  const next = comicAdjacentSpreadPage(orderedPages, current, mode, 1, pairing);
  const previous = comicAdjacentSpreadPage(orderedPages, current, mode, -1, pairing);
  const visible = new Set(comicSpreadPages(orderedPages, current, mode, pairing));
  return [...new Set([
    ...comicSpreadPages(orderedPages, next, mode, pairing),
    ...comicSpreadPages(orderedPages, previous, mode, pairing)
  ])].filter((candidate) => !visible.has(candidate));
}

export function comicPagePercent(page: number, orderedPages: number[], mode: 'single' | 'double' = 'single', pairing: ComicPairingPolicy = 'paired-from-first') {
  if (!orderedPages.length) return 0;
  if (orderedPages.length === 1) return 100;
  const visibleLastPage = comicSpreadPages(orderedPages, page, mode, pairing).at(-1) ?? page;
  const index = Math.max(0, orderedPages.indexOf(visibleLastPage));
  return (index / (orderedPages.length - 1)) * 100;
}

export function comicPageForProgress(progression: number, orderedPages: number[]) {
  if (!orderedPages.length) return 0;
  const index = Math.round(Math.max(0, Math.min(1, progression)) * (orderedPages.length - 1));
  return orderedPages[index] ?? orderedPages[0];
}
