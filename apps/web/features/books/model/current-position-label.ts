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
  if (resource.readerType === 'audio' && presentation?.playback) {
    return formatDuration(presentation.playback.positionMillis);
  }
  if (presentation?.page) {
    return translate('第 {value0} 页', { value0: presentation.page.number });
  }
  if (presentation?.chapter?.title) return presentation.chapter.title;
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
