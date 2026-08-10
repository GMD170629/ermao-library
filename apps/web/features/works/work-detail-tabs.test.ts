import assert from 'node:assert/strict';
import test from 'node:test';
import type { MediaKind, VolumeResource, WorkView } from '../../types/work';
import {
  detailTabsForBook,
  displayVolumeNumber,
  formatDuration,
  normalizeWorkDetailTabOrder,
  resolvedDetailTab,
  selectedVolumeForDetailTab,
  workDetailReturnHref,
  workDetailTabHref
} from './work-detail-tabs';

function volume(id: string, sortOrder: number, hidden = false): VolumeResource {
  return { id, mediaVersionId: 'media-1', title: id, volumeIndex: null, sortOrder, format: 'EPUB', readerType: 'reflowable', classification: { source: 'LEGACY', reason: 'LEGACY', suggestedMediaKind: null }, derivedFromVolumeId: null, publisher: null, publishedAt: null, language: null, isbn: null, identifier: null, narrator: null, abridged: null, importStatus: 'READY', importError: null, coverUrl: '', sizeBytes: 0, pageCount: null, chapterCount: null, durationMs: null, trackCount: null, progress: 0, lastReadAt: null, hidden, readable: true, conversionAvailable: false, kindleSendAvailable: true, files: [] };
}

function work(kinds: MediaKind[], continueVolumeId: string | null = null): WorkView {
  return { id: 'work-1', title: '书', author: '作者', description: '', seriesName: null, seriesIndex: null, tags: [], publicationStatus: 'UNKNOWN', trackingStatus: 'NOT_TRACKING', ignored: false, organized: true, metadataQuality: 100, addedAt: '', updatedAt: '', coverUrl: '', coverStatus: '', gradient: '', recentMediaKind: null, continueVolumeId, availableMediaKinds: kinds, detailTabs: [], selectedDetailTab: null, completed: false, mediaVersions: kinds.map((mediaKind, index) => ({ id: `media-${index}`, mediaKind, completed: false, volumeCount: 1, sizeBytes: 0, volumes: [volume(`${mediaKind}-volume`, index)] })) };
}

test('normalizes saved order and restores missing media tabs', () => {
  assert.deepEqual(normalizeWorkDetailTabOrder('["AUDIOBOOK","EBOOK","AUDIOBOOK","UNKNOWN"]'), ['AUDIOBOOK', 'EBOOK', 'COMIC', 'STRUCTURE']);
});

test('deep links use detailTab and volumeId only', () => {
  assert.equal(workDetailTabHref('work/下一部', 'EBOOK', 'volume/1'), '/works/work%2F%E4%B8%8B%E4%B8%80%E9%83%A8?detailTab=EBOOK&volumeId=volume%2F1');
});

test('detail tab links preserve a validated library return target', () => {
  assert.equal(
    workDetailTabHref('work-1', 'COMIC', null, '/library?status=READING&sort=title'),
    '/works/work-1?detailTab=COMIC&returnTo=%2Flibrary%3Fstatus%3DREADING%26sort%3Dtitle'
  );
  assert.equal(workDetailReturnHref('https://example.test/library'), '/library');
  assert.equal(workDetailReturnHref('//example.test/library'), '/library');
  assert.equal(workDetailReturnHref('/settings'), '/library');
});

test('shows actual media tabs and the structure tab only', () => {
  assert.deepEqual(detailTabsForBook(work(['EBOOK', 'AUDIOBOOK'])).map((tab) => tab.key), ['EBOOK', 'AUDIOBOOK', 'STRUCTURE']);
});

test('an absent medium resolves to the selected available media tab', () => {
  const value = { ...work(['EBOOK']), recentMediaKind: 'EBOOK' as const };
  assert.equal(resolvedDetailTab(value, 'COMIC'), 'EBOOK');
});

test('uses the server tab order and last selected tab when no URL tab is supplied', () => {
  const value = { ...work(['EBOOK', 'AUDIOBOOK']), detailTabs: [{ key: 'AUDIOBOOK' as const, label: '有声书', sortOrder: 0 }, { key: 'EBOOK' as const, label: '电子书', sortOrder: 1 }], selectedDetailTab: 'AUDIOBOOK' as const };
  assert.deepEqual(detailTabsForBook(value).map((tab) => tab.key), ['AUDIOBOOK', 'EBOOK', 'STRUCTURE']);
  assert.equal(resolvedDetailTab(value), 'AUDIOBOOK');
});

test('selects the requested volume before the continue volume and stable first volume', () => {
  const value = work(['EBOOK'], 'continue');
  value.mediaVersions[0]?.volumes.push(volume('continue', 2), volume('first', -1));
  assert.equal(selectedVolumeForDetailTab(value, 'EBOOK', 'EBOOK-volume')?.id, 'EBOOK-volume');
  assert.equal(selectedVolumeForDetailTab(value, 'EBOOK', 'missing')?.id, 'continue');
});

test('falls back to the first unfinished volume in version order', () => {
  const value = work(['EBOOK']);
  const first = value.mediaVersions[0]?.volumes[0];
  if (!first) throw new Error('missing fixture volume');
  value.mediaVersions[0]?.volumes.splice(0, 1, { ...first, progress: 100 }, volume('second', 1));
  assert.equal(selectedVolumeForDetailTab(value, 'EBOOK')?.id, 'second');
});

test('uses an explicit volume number before its sorted position', () => {
  const explicit = { ...volume('explicit', 5), volumeIndex: 9 };
  assert.equal(displayVolumeNumber(explicit, 0), 9);
  assert.equal(displayVolumeNumber(volume('fallback', 5), 1), 2);
});

test('formats audiobook durations', () => {
  assert.equal(formatDuration(65_000), '1:05');
  assert.equal(formatDuration(3_665_000), '1:01:05');
});
