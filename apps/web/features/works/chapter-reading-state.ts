import { resolveActiveEpubNavigationIndex } from '../reader/v3/epub-navigation';

export type ChapterReadingUnit = {
  href?: string;
  sortOrder: number;
};

export type ChapterReadingState = 'current' | 'read' | 'unread';

export type ChapterReadingListMeta = {
  page?: number;
  pageSize?: number;
  total?: number;
  currentIndex?: number | null;
};

/**
 * Resolves chapter rows without treating every anchor in a shared XHTML file
 * as the current chapter. The exact TOC href wins; stored sort order is only a
 * fallback for an exact server projection on paginated lists. Overall percent,
 * spine section and chapter count are never used to infer a chapter.
 */
export function resolveChapterReadingStates(
  units: readonly ChapterReadingUnit[],
  currentHref: string | null | undefined,
  currentSortOrder: number | null | undefined,
  progress: number,
  listMeta?: ChapterReadingListMeta
): ChapterReadingState[] {
  const activeIndex = resolveActiveEpubNavigationIndex(units, currentHref, null);
  const activeSortOrder = activeIndex === null ? currentSortOrder : units[activeIndex]?.sortOrder;
  const page = listMeta?.page ?? 1;
  const pageSize = listMeta?.pageSize ?? units.length;
  const pageOffset = Math.max(0, (page - 1) * pageSize);
  const exactGlobalIndex = listMeta?.currentIndex ?? null;

  return units.map((unit, index) => {
    // Completion is stronger than the transient current-position marker: the
    // final chapter is both the last location and a fully read chapter.
    if (progress >= 100) return 'read';

    if (exactGlobalIndex !== null) {
      const globalIndex = pageOffset + index;
      if (globalIndex === exactGlobalIndex) return 'current';
      if (globalIndex < exactGlobalIndex) return 'read';
      return 'unread';
    }

    const isCurrent = activeIndex === null
      ? activeSortOrder !== null && activeSortOrder !== undefined && unit.sortOrder === activeSortOrder
      : index === activeIndex;
    if (isCurrent) return 'current';
    if (activeSortOrder !== null && activeSortOrder !== undefined && unit.sortOrder < activeSortOrder) return 'read';
    return 'unread';
  });
}
