import type { VolumeResource } from '../../../types/work';
import { formatDuration } from '../work-detail';
import type { EbookChapterDetail } from './chapter-detail';

type Translate = (
  source: string,
  values?: Record<string, string | number>
) => string;

/** Display only positions derived from the Reader's exact persisted locator. */
export function currentPositionLabel(
  volume: VolumeResource,
  detail: EbookChapterDetail | null,
  translate: Translate
): string {
  if (volume.readerType === 'audio' && volume.durationMs) {
    return formatDuration(volume.durationMs * volume.progress / 100);
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
  if (detail?.currentChapterIndex !== null && detail?.currentChapterIndex !== undefined) {
    return translate('第 {value0} 章', { value0: detail.currentChapterIndex + 1 });
  }
  return volume.title;
}
