import { resolveActiveEpubNavigationIndex } from '../reader/v2/epub-navigation';

export type ChapterReadingUnit = {
  href?: string;
  sortOrder: number;
};

export type ChapterReadingState = 'current' | 'read' | 'unread';

/**
 * Resolves chapter rows without treating every anchor in a shared XHTML file
 * as the current chapter. The exact TOC href wins; stored sort order is only a
 * fallback for paginated lists or older progress records.
 */
export function resolveChapterReadingStates(
  units: readonly ChapterReadingUnit[],
  currentHref: string | null | undefined,
  currentSortOrder: number | null | undefined,
  progress: number
): ChapterReadingState[] {
  const activeIndex = resolveActiveEpubNavigationIndex(units, currentHref, null);
  const activeSortOrder = activeIndex === null ? currentSortOrder : units[activeIndex]?.sortOrder;

  return units.map((unit, index) => {
    // Completion is stronger than the transient current-position marker: the
    // final chapter is both the last location and a fully read chapter.
    if (progress >= 100) return 'read';
    const isCurrent = activeIndex === null
      ? activeSortOrder !== null && activeSortOrder !== undefined && unit.sortOrder === activeSortOrder
      : index === activeIndex;
    if (isCurrent) return 'current';
    if (activeSortOrder !== null && activeSortOrder !== undefined && unit.sortOrder < activeSortOrder) return 'read';
    return 'unread';
  });
}
