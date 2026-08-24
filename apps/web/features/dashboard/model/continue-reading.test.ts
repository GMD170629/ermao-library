import assert from 'node:assert/strict';
import test from 'node:test';
import { mapContinueReadingItem } from './continue-reading';

test('maps the dashboard resume resource from the API contract', () => {
  const item = mapContinueReadingItem({
    bookId: 'book-1',
    title: 'Book',
    author: 'Author',
    coverUrl: '/cover',
    resourceFormat: 'EPUB',
    readerType: 'reflowable',
    resumeResourceId: 'resource-1',
    progress: 42,
    lastReadAt: '2026-08-03T10:00:00Z',
    chapter: 'Chapter 2',
    resourceTitle: null,
    narrator: null
  });

  assert.equal(item?.resumeResourceId, 'resource-1');
  assert.equal(item?.progress, 42);
});

test('rejects malformed continue-reading records at the API boundary', () => {
  assert.equal(mapContinueReadingItem({ bookId: '' }), null);
  assert.equal(mapContinueReadingItem({ bookId: 'book-1', readerType: 'unknown' }), null);
});
