import type { ReadableResourceView } from '../../../types/book';
import { chapterDeepLinkHref } from '../ebook-chapter-navigation';

export const CHAPTER_DETAIL_PAGE_SIZE = 120;

export type ChapterDetailUnit = Readonly<{
  id: string;
  title: string;
  href: string | null;
  sortOrder: number;
  unitType: string;
  pageNumber: number | null;
}>;

export type ChapterDetailPage = Readonly<{
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}>;

export type EbookChapterDetail = Readonly<{
  units: ChapterDetailUnit[];
  page: ChapterDetailPage;
  currentHref: string | null;
  currentChapterIndex: number | null;
  currentChapterTitle: string | null;
  currentChapterSortOrder: number | null;
  currentPageNumber: number | null;
  progress: number;
}>;

export function singleResourceEbook(resources: readonly ReadableResourceView[]): ReadableResourceView | null {
  const resource = resources.length === 1 ? resources[0] ?? null : null;
  return resource && (resource.readerType === 'reflowable' || resource.readerType === 'pdf') ? resource : null;
}

export function detailReaderHref(resource: ReadableResourceView, unit: ChapterDetailUnit): string | null {
  if (!resource.readable) return null;
  if (resource.format === 'PDF') {
    const pageNumber = unit.pageNumber ?? unit.sortOrder + 1;
    return `/reader/${encodeURIComponent(resource.id)}?page=${encodeURIComponent(String(Math.max(1, pageNumber)))}`;
  }
  const href = chapterDeepLinkHref(resource.format, unit.href);
  return href ? `/reader/${encodeURIComponent(resource.id)}?href=${encodeURIComponent(href)}` : null;
}

export function syntheticPdfPageUnits(resource: ReadableResourceView, page: number, pageSize: number): ChapterDetailUnit[] {
  const total = Math.max(0, resource.pageCount ?? 0);
  const start = Math.max(0, (page - 1) * pageSize);
  const end = Math.min(total, start + pageSize);
  return Array.from({ length: Math.max(0, end - start) }, (_, offset) => {
    const pageNumber = start + offset + 1;
    return {
      id: `${resource.id}:page:${pageNumber}`,
      title: '',
      href: null,
      sortOrder: pageNumber - 1,
      unitType: 'page',
      pageNumber
    };
  });
}
