import assert from 'node:assert/strict';
import test from 'node:test';
import { libraryBooksUrl, mapLibraryBookSummary } from './books';

test('library list selects the lightweight projection required by the active view', () => {
  const bookshelfUrl = new URL(
    libraryBooksUrl('q=example', 2, '50', 'bookshelf'),
    'http://localhost'
  );
  const managementUrl = new URL(
    libraryBooksUrl('q=example', 3, '20', 'management'),
    'http://localhost'
  );

  assert.equal(bookshelfUrl.searchParams.get('view'), 'bookshelf');
  assert.equal(bookshelfUrl.searchParams.get('page'), '2');
  assert.equal(managementUrl.searchParams.get('view'), 'management');
  assert.equal(managementUrl.searchParams.get('page'), '3');
});

test('bookshelf projection validates and preserves cover progress', () => {
  const book = mapLibraryBookSummary({
    id: 'book-1',
    title: 'Example',
    author: 'Author',
    coverUrl: '/api/books/book-1/cover',
    availableMediaKinds: ['EBOOK'],
    progress: 42.5
  }, 'bookshelf');

  assert.equal(book.projection, 'bookshelf');
  if (book.projection !== 'bookshelf') assert.fail('expected bookshelf projection');
  assert.equal(book.progress, 42.5);
});

test('management projection maps media and progress summaries without mediaVersions', () => {
  const book = mapLibraryBookSummary({
    id: 'book-1',
    title: 'Example',
    author: 'Author',
    format: 'EPUB',
    gradient: 'from-slate-950',
    coverStatus: 'READY',
    coverUrl: '/api/books/book-1/cover',
    publisher: 'Publisher',
    seriesName: 'Series',
    tags: ['tag'],
    type: 'ebook',
    availableMediaKinds: ['EBOOK', 'AUDIOBOOK'],
    statusValue: 'READING',
    lastReadAt: '2026-08-01T00:00:00Z',
    importedAt: '2026-07-31T00:00:00Z'
  }, 'management');

  assert.equal(book.projection, 'management');
  if (book.projection !== 'management') assert.fail('expected management projection');
  assert.deepEqual(book.availableMediaKinds, ['EBOOK', 'AUDIOBOOK']);
  assert.equal(book.statusValue, 'READING');
  assert.equal(book.availableMediaKinds.length, 2);
});

test('management projection rejects a malformed media summary at the API boundary', () => {
  assert.throws(
    () => mapLibraryBookSummary({ id: 'book-1' }, 'management'),
    /LIBRARY_BOOK_SUMMARY_INVALID/
  );
});
