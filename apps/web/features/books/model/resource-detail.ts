import type { ReadableResourceView } from '../../../types/book';
import { chapterDeepLinkHref } from '../ebook-chapter-navigation';

export const RESOURCE_DETAIL_LIST_PAGE_SIZE = 50;
export const RESOURCE_DETAIL_PREVIEW_PAGE_SIZE = 24;

type ResourceDetailUnitBase = Readonly<{
  id: string;
  title: string;
  sortOrder: number;
  assetId: string | null;
  mediaType: string | null;
}>;

export type ResourceChapterDetailUnit = ResourceDetailUnitBase & Readonly<{
  unitType: 'chapter';
  href: string | null;
  level: number | null;
}>;

export type ResourcePageDetailUnit = ResourceDetailUnitBase & Readonly<{
  unitType: 'page';
  pageNumber: number;
  previewUrl: string | null;
}>;

export type ResourceTrackDetailUnit = ResourceDetailUnitBase & Readonly<{
  unitType: 'track';
  durationMs: number | null;
  discNumber: number | null;
  trackNumber: number | null;
}>;

export type ResourceDetailUnit = ResourceChapterDetailUnit | ResourcePageDetailUnit | ResourceTrackDetailUnit;

export type ResourceDetailPage = Readonly<{
  units: ResourceDetailUnit[];
  page: Readonly<{
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
  }>;
  currentHref: string | null;
  currentChapterIndex: number | null;
  currentChapterTitle: string | null;
  currentChapterSortOrder: number | null;
  currentPageNumber: number | null;
  progress: number;
}>;

export function resourceDetailPageSize(resource: ReadableResourceView): number {
  return resource.readerType === 'comic' || resource.readerType === 'pdf'
    ? RESOURCE_DETAIL_PREVIEW_PAGE_SIZE
    : RESOURCE_DETAIL_LIST_PAGE_SIZE;
}

export function resourcePreviewRetryUrl(previewUrl: string, attempt: number): string {
  if (attempt <= 0) return previewUrl;
  const hashIndex = previewUrl.indexOf('#');
  const urlWithoutFragment = hashIndex >= 0 ? previewUrl.slice(0, hashIndex) : previewUrl;
  const fragment = hashIndex >= 0 ? previewUrl.slice(hashIndex) : '';
  const separator = urlWithoutFragment.includes('?') ? '&' : '?';
  return `${urlWithoutFragment}${separator}previewRetry=${attempt}${fragment}`;
}

export function resourceDetailItemHref(
  resource: ReadableResourceView,
  unit: ResourceDetailUnit
): string | null {
  if (!resource.readable) return null;
  if (unit.unitType === 'chapter') {
    const href = chapterDeepLinkHref(resource.format, unit.href);
    return href ? `/reader/${encodeURIComponent(resource.id)}?href=${encodeURIComponent(href)}` : null;
  }
  if (unit.unitType === 'page') {
    return `/reader/${encodeURIComponent(resource.id)}?page=${encodeURIComponent(String(unit.pageNumber))}`;
  }
  return unit.assetId
    ? `/listen/${encodeURIComponent(resource.id)}?assetId=${encodeURIComponent(unit.assetId)}`
    : null;
}
