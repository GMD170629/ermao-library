import assert from 'node:assert/strict';
import test from 'node:test';
import type { BookView, ReadableResourceView } from '../../../types/book';
import {
  bookActionIds,
  bookReadingStatus,
  nextBookReadingStatus,
  resumeResourceForBook
} from './book-action-menu';

function resource(id: string, progress: number, options: { hidden?: boolean; readable?: boolean } = {}): ReadableResourceView {
  return {
    id, bookId: 'book-1', sourceNodeId: `${id}-node`, title: id, description: '', resourceIndex: null,
    sortOrder: 0, format: 'EPUB', readerType: 'reflowable', publisher: null, publishedAt: null,
    language: null, isbn: null, identifier: null, narrator: null, abridged: null, importStatus: 'READY',
    importError: null, coverUrl: '', sizeBytes: 0, pageCount: null, chapterCount: null, durationMs: null,
    trackCount: null, progress, lastReadAt: null, hidden: options.hidden === true,
    readable: options.readable !== false, kindleSendAvailable: false, assets: []
  };
}

function book(resources: ReadableResourceView[], continueResourceId: string | null, completed = false): BookView {
  return {
    id: 'book-1', sourceNodeId: 'book-node', title: 'Book', author: 'Author', description: '', seriesName: null,
    seriesIndex: null, tags: [], publicationStatus: 'UNKNOWN', trackingStatus: 'NOT_TRACKING', ignored: false,
    organized: true, metadataQuality: 0, addedAt: '', updatedAt: '', coverUrl: '', coverStatus: '', gradient: '',
    continueResourceId, completed, resources, resourceImportSummary: { ready: resources.length, pending: 0, failed: 0 }
  };
}

test('offers the complete manager menu and only personal reading status to members', () => {
  assert.deepEqual(bookActionIds(true), ['edit', 'regenerate-image', 'reading-status', 'recognize', 'rescan', 'delete']);
  assert.deepEqual(bookActionIds(false), ['reading-status']);
});

test('reading status action always targets the opposite terminal state', () => {
  assert.equal(nextBookReadingStatus('UNREAD'), 'FINISHED');
  assert.equal(nextBookReadingStatus('READING'), 'FINISHED');
  assert.equal(nextBookReadingStatus('FINISHED'), 'UNREAD');
});

test('derives aggregate Book reading status from completion and visible progress', () => {
  assert.equal(bookReadingStatus(book([resource('first', 0)], null)), 'UNREAD');
  assert.equal(bookReadingStatus(book([resource('hidden', 50, { hidden: true }), resource('first', 0)], null)), 'UNREAD');
  assert.equal(bookReadingStatus(book([resource('first', 20)], null)), 'READING');
  assert.equal(bookReadingStatus(book([resource('first', 100)], null, true)), 'FINISHED');
});

test('resume resource prefers continue point, then first unfinished readable resource, then first readable resource', () => {
  const resources = [resource('hidden', 0, { hidden: true }), resource('finished', 100), resource('unfinished', 20), resource('later', 0)];
  assert.equal(resumeResourceForBook(book(resources, 'later'))?.id, 'later');
  assert.equal(resumeResourceForBook(book(resources, null))?.id, 'unfinished');
  assert.equal(resumeResourceForBook(book([resource('finished', 100), resource('second', 100)], null))?.id, 'finished');
  assert.equal(resumeResourceForBook(book([resource('disabled', 0, { readable: false })], null)), null);
});
