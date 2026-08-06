import type { VolumeResource, WorkDetailTabKey } from '../../../types/work';
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
  currentChapterSortOrder: number | null;
  currentPageNumber: number | null;
  progress: number;
}>;

export function singleVolumeEbook(tab: WorkDetailTabKey, volumes: readonly VolumeResource[]): VolumeResource | null {
  const volume = tab !== 'STRUCTURE' && volumes.length === 1 ? volumes[0] ?? null : null;
  return volume && (volume.readerType === 'reflowable' || volume.readerType === 'pdf') ? volume : null;
}

export function detailReaderHref(volume: VolumeResource, unit: ChapterDetailUnit): string | null {
  if (!volume.readable) return null;
  if (volume.format === 'PDF') {
    const pageNumber = unit.pageNumber ?? unit.sortOrder + 1;
    return `/reader/${encodeURIComponent(volume.id)}?page=${encodeURIComponent(String(Math.max(1, pageNumber)))}`;
  }
  const href = chapterDeepLinkHref(volume.format, unit.href);
  return href ? `/reader/${encodeURIComponent(volume.id)}?href=${encodeURIComponent(href)}` : null;
}

export function syntheticPdfPageUnits(volume: VolumeResource, page: number, pageSize: number): ChapterDetailUnit[] {
  const total = Math.max(0, volume.pageCount ?? 0);
  const start = Math.max(0, (page - 1) * pageSize);
  const end = Math.min(total, start + pageSize);
  return Array.from({ length: Math.max(0, end - start) }, (_, offset) => {
    const pageNumber = start + offset + 1;
    return {
      id: `${volume.id}:page:${pageNumber}`,
      title: '',
      href: null,
      sortOrder: pageNumber - 1,
      unitType: 'page',
      pageNumber
    };
  });
}
