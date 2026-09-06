import type { ReadableResourceView } from '../../../types/book';
import type { ReaderPositionPresentation } from '@shuku/reader-core';
import { formatDuration } from '../book-detail';
import type { ResourceDetailPage } from './resource-detail';

type Translate = (
  source: string,
  values?: Record<string, string | number>
) => string;

/** Display the independent Reader presentation without inspecting its Locator. */
export function currentPositionLabel(
  resource: ReadableResourceView,
  detail: ResourceDetailPage | null,
  translate: Translate,
  presentation: ReaderPositionPresentation | null = null
): string {
  const currentPresentation = presentation ?? detail?.presentation;
  if (resource.readerType === 'audio' && currentPresentation?.playback) {
    return formatDuration(currentPresentation.playback.positionMillis);
  }
  if (currentPresentation?.page) {
    return translate('第 {value0} 页', { value0: currentPresentation.page.number });
  }
  if (currentPresentation?.chapter?.title) return currentPresentation.chapter.title;
  if (resource.readerType === 'audio' && resource.durationMs) {
    return formatDuration(resource.durationMs * resource.progress / 100);
  }
  if (detail?.currentPageNumber !== null && detail?.currentPageNumber !== undefined) {
    return translate('第 {value0} 页', { value0: detail.currentPageNumber });
  }
  if (detail?.currentChapterTitle) return detail.currentChapterTitle;
  if (detail?.currentChapterSortOrder !== null && detail?.currentChapterSortOrder !== undefined) {
    const matchingUnit = detail.units.find(
      (unit) => unit.sortOrder === detail.currentChapterSortOrder
    );
    if (matchingUnit?.title) return matchingUnit.title;
  }
  return resource.title;
}
