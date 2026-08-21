import assert from 'node:assert/strict';
import test from 'node:test';
import { assetDownloadUrl, fetchBook, mapBookView } from './client';

const resource = (id: string, bookId = 'book-1') => ({
  id,
  bookId,
  title: 'Resource',
  resourceIndex: null,
  sortOrder: 0,
  format: 'COMIC',
  readerType: 'comic',
  classification: { source: 'AUTO', reason: 'FORMAT_DEFAULT', suggestedMediaKind: null },
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
  sizeBytes: 1024,
  pageCount: 1,
  chapterCount: null,
  durationMs: null,
  trackCount: null,
  progress: 0,
  lastReadAt: null,
  hidden: false,
  readable: true,
  kindleSendAvailable: false,
  assets: []
});

test('builds an explicit attachment URL for a single resource asset download', () => {
  assert.equal(assetDownloadUrl('asset/id with spaces'), '/api/assets/asset%2Fid%20with%20spaces?download=true');
});

test('full book responses reject summary projections before reaching detail UI', () => {
  assert.throws(() => mapBookView({ id: 'book-1', title: 'Summary only' }), /资源结构/);
});

test('maps a direct book resource collection', () => {
  const book = mapBookView({ id: 'book-1', title: 'Book', resources: [resource('resource-1')] });
  assert.equal(book.resources.length, 1);
  assert.equal(book.resources[0]?.readable, true);
  assert.equal(book.resources[0]?.bookId, 'book-1');
});

test('requests book detail with an optional resource selector', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  globalThis.fetch = async (input) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({ ok: true, data: { book: { id: 'book-1', resources: [] } } }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    await fetchBook('book/1', undefined, 'resource/3');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, '/api/books/book%2F1?resourceId=resource%2F3');
});
