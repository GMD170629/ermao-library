import assert from 'node:assert/strict';
import test from 'node:test';
import type { BookView, ReadableResourceView } from '../../types/book';
import { allVisibleResources, selectedResourceForBook, bookDetailHref, resourcePageFromQuery, singleReadableResourceForBook } from './book-detail';

function resource(id: string, progress = 0, hidden = false): ReadableResourceView {
  return {
    id,
    bookId: 'book-1',
    sourceNodeId: `${id}-source-node`,
    title: id,
    description: '',
    resourceIndex: null,
    sortOrder: 0,
    format: 'EPUB',
    readerType: 'reflowable',
    publisher: null,
    publishedAt: null,
    language: null,
    isbn: null,
    identifier: null,
    narrator: null,
    abridged: null,
    importStatus: 'READY',
    importError: null,
    coverUrl: '',
    sizeBytes: 0,
    pageCount: null,
    chapterCount: 3,
    durationMs: null,
    trackCount: null,
    progress,
    lastReadAt: null,
    hidden,
    readable: true,
    kindleSendAvailable: true,
    assets: []
  };
}

function book(resources: ReadableResourceView[], continueResourceId: string | null = null): BookView {
  return {
    id: 'book-1',
    sourceNodeId: 'book-1-source-node',
    title: '书',
    author: '作者',
    description: '',
    seriesName: null,
    seriesIndex: null,
    tags: [],
    publicationStatus: 'UNKNOWN',
    trackingStatus: 'NOT_TRACKING',
    ignored: false,
    organized: true,
    metadataQuality: 100,
    addedAt: '',
    updatedAt: '',
    coverUrl: '',
    coverStatus: '',
    gradient: '',
    continueResourceId,
    completed: false,
    resourceImportSummary: { ready: resources.length, pending: 0, failed: 0 },
    resources
  };
}

test('deep links use only bookId and resourceId', () => {
  assert.equal(bookDetailHref('book/下一部', 'resource/1'), '/books/book%2F%E4%B8%8B%E4%B8%80%E9%83%A8?resourceId=resource%2F1');
  assert.equal(bookDetailHref('book-1', null, '/library?status=READING&sort=title'), '/books/book-1?returnTo=%2Flibrary%3Fstatus%3DREADING%26sort%3Dtitle');
  assert.equal(new URL(bookDetailHref('book-1'), 'https://example.test').searchParams.has('resourceId'), false);
  assert.equal(bookDetailHref('book-1', 'resource-1', '/library?status=READING', 3), '/books/book-1?resourceId=resource-1&resourcePage=3&returnTo=%2Flibrary%3Fstatus%3DREADING');
  assert.equal(bookDetailHref('book-1', null, '/library?status=READING', 8), '/books/book-1?returnTo=%2Flibrary%3Fstatus%3DREADING');
  assert.equal(resourcePageFromQuery('4'), 4);
  assert.equal(resourcePageFromQuery('-1'), 1);
});

test('resource selection prefers URL, continue, first unfinished, then first resource', () => {
  const value = book([resource('finished', 100), resource('continue', 20), resource('unfinished')], 'continue');
  assert.equal(selectedResourceForBook(value, 'unfinished')?.id, 'unfinished');
  assert.equal(selectedResourceForBook(value)?.id, 'continue');
  assert.equal(selectedResourceForBook({ ...value, continueResourceId: null })?.id, 'unfinished');
  assert.deepEqual(allVisibleResources({ ...value, resources: [...value.resources, resource('hidden', 0, true)] }).map((item) => item.id), ['finished', 'continue', 'unfinished']);
});

test('single readable resource is the default detail only when it is the sole visible readable resource', () => {
  assert.equal(singleReadableResourceForBook(book([resource('only')]))?.id, 'only');
  assert.equal(singleReadableResourceForBook(book([resource('only'), resource('hidden', 0, true)]))?.id, 'only');
  assert.equal(singleReadableResourceForBook(book([resource('first'), resource('second')])), null);
  assert.equal(singleReadableResourceForBook(book([{ ...resource('not-readable'), readable: false }])), null);
});
