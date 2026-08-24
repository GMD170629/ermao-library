import assert from 'node:assert/strict';
import test from 'node:test';
import { assetDownloadUrl, fetchBook, fetchResourceDetail, mapBookView, uploadResourceCover } from './client';

const resource = (id: string, bookId = 'book-1') => ({
  id,
  bookId,
  sourceNodeId: `${id}-source-node`,
  title: 'Resource',
  description: '',
  resourceIndex: null,
  sortOrder: 0,
  format: 'COMIC',
  readerType: 'comic',
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

test('maps a direct book resource collection with physical identities', () => {
  const mappedResource = {
    ...resource('resource-1'),
    assets: [{
      id: 'asset-1',
      resourceId: 'resource-1',
      sourceNodeId: 'asset-source-node',
      role: 'PRIMARY',
      mimeType: 'application/zip',
      sortOrder: 0,
      sizeBytes: 1024,
      size: '1 KB',
      url: '/api/assets/asset-1',
      downloadUrl: '/api/assets/asset-1?download=true'
    }]
  };
  const book = mapBookView({ id: 'book-1', sourceNodeId: 'book-source-node', title: 'Book', resources: [mappedResource] });
  assert.equal(book.sourceNodeId, 'book-source-node');
  assert.equal(book.resources.length, 1);
  assert.equal(book.resources[0]?.readable, true);
  assert.equal(book.resources[0]?.bookId, 'book-1');
  assert.equal(book.resources[0]?.assets[0]?.downloadUrl, '/api/assets/asset-1?download=true');
  assert.equal('path' in (book.resources[0]?.assets[0] ?? {}), false);
});

test('requests book detail with an optional resource selector', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  globalThis.fetch = async (input) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({ ok: true, data: { book: { id: 'book-1', sourceNodeId: 'book-source-node', resources: [] } } }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    await fetchBook('book/1', undefined, 'resource/3');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, '/api/books/book%2F1?resourceId=resource%2F3');
});

test('uploads a custom cover to the selected readable resource', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  let requestedMethod = '';
  let requestedCover: FormDataEntryValue | null = null;
  globalThis.fetch = async (input, init) => {
    requestedUrl = String(input);
    requestedMethod = init?.method ?? '';
    const body = init?.body;
    assert.ok(body instanceof FormData);
    requestedCover = body.get('cover');
    return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const cover = new File(['cover'], 'volume.png', { type: 'image/png' });
    await uploadResourceCover('book/1', 'resource/3', cover);
    assert.equal(requestedCover, cover);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, '/api/books/book%2F1/resources/resource%2F3/cover');
  assert.equal(requestedMethod, 'PUT');
});

test('validates and maps a unified paginated resource detail response', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  globalThis.fetch = async (input) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({ ok: true, data: {
      bookId: 'book-1', resourceId: 'resource-1',
      units: [
        { id: 'chapter-1', unitType: 'chapter', title: 'Chapter', href: 'one.xhtml', sortOrder: 0, assetId: null, mediaType: 'application/xhtml+xml', level: 1 },
        { id: 'page-2', unitType: 'page', title: '', sortOrder: 1, assetId: null, mediaType: 'image/webp', pageNumber: 2, previewUrl: '/api/resources/resource-1/previews/1' },
        { id: 'track-1', unitType: 'track', title: 'Track', sortOrder: 2, assetId: 'asset-1', mediaType: 'audio/mpeg', durationMs: 20_000, discNumber: 1, trackNumber: 2 }
      ],
      page: { page: 2, pageSize: 24, total: 27, totalPages: 2 },
      currentHref: 'one.xhtml', currentPageNumber: null, progress: 25
    } }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const detail = await fetchResourceDetail('book-1', 'resource-1', 2, 24);
    assert.equal(detail.units[0]?.unitType, 'chapter');
    assert.equal(detail.units[1]?.unitType, 'page');
    assert.equal(detail.units[2]?.unitType, 'track');
    assert.deepEqual(detail.page, { page: 2, pageSize: 24, total: 27, totalPages: 2 });
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, '/api/books/book-1/resources/resource-1/reading-units?page=2&pageSize=24');
});
