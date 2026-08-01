import type { ReadingFormat, WorkDetailTabKey } from '../../types/work';

const REFLOWABLE_EBOOK_FORMATS = new Set<ReadingFormat>([
  'EPUB',
  'MOBI',
  'AZW',
  'AZW3',
  'PRC',
  'FB2',
  'TXT'
]);

/** Formats that store chapter units and can show a detail-page chapter list. */
export function isReflowableEbookFormat(format: string | null | undefined): format is ReadingFormat {
  return Boolean(format && REFLOWABLE_EBOOK_FORMATS.has(format as ReadingFormat));
}

/** Whether the ebook detail tab should render chapter navigation for this edition. */
export function hasEbookChapterNavigation(
  detailTab: WorkDetailTabKey | null | undefined,
  format: string | null | undefined
): boolean {
  return detailTab === 'EBOOK' && isReflowableEbookFormat(format);
}

/**
 * Exact source-engine target safe to pass as `/reader?href=`. The server only
 * publishes these forms after import-time validation.
 */
export function chapterDeepLinkHref(
  format: string | null | undefined,
  href: string | null | undefined
): string | null {
  if (!href?.trim()) return null;
  const target = href.trim();
  if (format === 'EPUB') return target;
  if ((format === 'MOBI' || format === 'PRC') && /^filepos:\d+$/iu.test(target)) return target;
  if ((format === 'AZW' || format === 'AZW3')
    && /^kindle:pos:fid:[0-9a-v]+:off:[0-9a-v]+$/iu.test(target)) return target;
  if (format === 'FB2' && /^\d+(?:#\d+)?$/u.test(target)) return target;
  if (format === 'TXT' && /^txt-section:\d+$/u.test(target)) return target;
  return null;
}
