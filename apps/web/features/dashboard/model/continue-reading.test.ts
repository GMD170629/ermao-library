import assert from 'node:assert/strict';
import test from 'node:test';
import { mapContinueReadingItem } from './continue-reading';

test('maps the dashboard resume volume from the API contract', () => {
  const item = mapContinueReadingItem({
    workId: 'work-1',
    title: 'Book',
    author: 'Author',
    coverUrl: '/cover',
    mediaKind: 'EBOOK',
    volumeFormat: 'EPUB',
    readerType: 'reflowable',
    resumeVolumeId: 'volume-1',
    progress: 42,
    lastReadAt: '2026-08-03T10:00:00Z',
    chapter: 'Chapter 2',
    volumeTitle: null,
    narrator: null
  });

  assert.equal(item?.resumeVolumeId, 'volume-1');
  assert.equal(item?.progress, 42);
});

test('rejects malformed continue-reading records at the API boundary', () => {
  assert.equal(mapContinueReadingItem({ workId: '', mediaKind: 'EBOOK' }), null);
  assert.equal(mapContinueReadingItem({ workId: 'work-1', mediaKind: 'VIDEO' }), null);
});
