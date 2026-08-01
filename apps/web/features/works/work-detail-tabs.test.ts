import assert from 'node:assert/strict';
import test from 'node:test';
import type { MediaKind, VolumeResource, WorkView } from '../../types/work';
import {
  detailTabsForBook,
  formatDuration,
  normalizeWorkDetailTabOrder,
  resolvedDetailTab,
  selectedVolumeForDetailTab,
  workDetailTabHref
} from './work-detail-tabs';

function volume(id: string, sortOrder: number, hidden = false): VolumeResource {
  return { id, mediaVersionId: 'media-1', title: id, volumeIndex: null, sortOrder, format: 'EPUB', derivedFromVolumeId: null, publisher: null, publishedAt: null, language: null, isbn: null, identifier: null, narrator: null, abridged: null, importStatus: 'READY', importError: null, coverUrl: '', pageCount: null, chapterCount: null, durationMs: null, trackCount: null, progress: 0, lastReadAt: null, hidden, readable: true, conversionAvailable: false, files: [] };
}

function work(kinds: MediaKind[], continueVolumeId: string | null = null): WorkView {
  return { id: 'work-1', title: '书', author: '作者', description: '', seriesName: null, seriesIndex: null, tags: [], publicationStatus: 'UNKNOWN', trackingStatus: 'NOT_TRACKING', ignored: false, organized: true, metadataQuality: 100, addedAt: '', updatedAt: '', coverUrl: '', coverStatus: '', gradient: '', recentMediaKind: null, continueVolumeId, completed: false, mediaVersions: kinds.map((mediaKind, index) => ({ id: `media-${index}`, mediaKind, completed: false, volumes: [volume(`${mediaKind}-volume`, index)] })) };
}

test('normalizes saved order and restores missing media tabs', () => {
  assert.deepEqual(normalizeWorkDetailTabOrder('["AUDIOBOOK","EBOOK","AUDIOBOOK","UNKNOWN"]'), ['AUDIOBOOK', 'EBOOK', 'COMIC', 'STRUCTURE']);
});

test('deep links use detailTab and volumeId only', () => {
  assert.equal(workDetailTabHref('work/下一部', 'EBOOK', 'volume/1'), '/works/work%2F%E4%B8%8B%E4%B8%80%E9%83%A8?detailTab=EBOOK&volumeId=volume%2F1');
});

test('always shows the three media tabs and the structure tab', () => {
  assert.deepEqual(detailTabsForBook(work(['EBOOK', 'AUDIOBOOK'])).map((tab) => tab.key), ['EBOOK', 'COMIC', 'AUDIOBOOK', 'STRUCTURE']);
});

test('an empty requested medium stays addressable as an empty media tab', () => {
  const value = { ...work(['EBOOK']), recentMediaKind: 'EBOOK' as const };
  assert.equal(resolvedDetailTab(value, 'COMIC'), 'COMIC');
});

test('selects the requested volume before the continue volume and stable first volume', () => {
  const value = work(['EBOOK'], 'continue');
  value.mediaVersions[0]?.volumes.push(volume('continue', 2), volume('first', -1));
  assert.equal(selectedVolumeForDetailTab(value, 'EBOOK', 'EBOOK-volume')?.id, 'EBOOK-volume');
  assert.equal(selectedVolumeForDetailTab(value, 'EBOOK', 'missing')?.id, 'continue');
});

test('formats audiobook durations', () => {
  assert.equal(formatDuration(65_000), '1:05');
  assert.equal(formatDuration(3_665_000), '1:01:05');
});
