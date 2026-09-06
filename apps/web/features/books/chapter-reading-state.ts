export type ChapterReadingUnit = { href?: string | null; sortOrder: number };
export type ChapterReadingState = 'current' | 'read' | 'unread';

/** Only the core's matching key/index pair is an exact local chapter projection. */
export function chapterPresentationSortOrder(chapter: {
  navigationKey: string | null; index: number | null;
} | null | undefined): number | null {
  if (chapter?.index == null || chapter.navigationKey !== `chapter-${chapter.index}`) return null;
  return Number.isSafeInteger(chapter.index) && chapter.index >= 0 ? chapter.index : null;
}

/** The server resolves the shared chapter key to the resource's exact preorder. */
export function resolveChapterReadingStates(
  units: readonly ChapterReadingUnit[],
  currentSortOrder: number | null | undefined,
  progress: number
): ChapterReadingState[] {
  return units.map((unit) => {
    if (!unit.href) return 'unread';
    if (progress >= 100) return 'read';
    if (currentSortOrder == null) return 'unread';
    if (unit.sortOrder === currentSortOrder) return 'current';
    return unit.sortOrder < currentSortOrder ? 'read' : 'unread';
  });
}
