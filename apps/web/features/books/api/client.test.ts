import assert from 'node:assert/strict';
import test from 'node:test';
import {
  applyRecognizedMetadata,
  assetDownloadUrl,
  deleteBookSources,
  fetchBook,
  fetchResourceDetail,
  mapBookView,
  regenerateResourceCover,
  regenerateSourceNodeCover,
  regenerateBookImage,
  removeBookCover,
  replaceBookTags,
  searchSourceNodeMetadata,
  updateBookReadingStatus,
  uploadResourceCover
} from './client';

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
      title: 'Archive',
      resourceId: 'resource-1',
      sourceNodeId: 'asset-source-node',
      role: 'PRIMARY',
      mimeType: 'application/zip',
      sourceFormat: 'ZIP',
      sortOrder: 0,
      sizeBytes: 1024,
      size: '1 KB',
      mtimeMs: 1234,
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
  assert.equal(book.resources[0]?.assets[0]?.sourceFormat, 'ZIP');
  assert.equal(book.resources[0]?.assets[0]?.mtimeMs, 1234);
  assert.equal('path' in (book.resources[0]?.assets[0] ?? {}), false);
});

test('retains every exact MOBI-family resource format', () => {
  const formats = ['MOBI', 'AZW', 'AZW3', 'PRC'] as const;
  const book = mapBookView({
    id: 'book-1',
    sourceNodeId: 'book-source-node',
    title: 'Book',
    resources: formats.map((format) => ({
      ...resource(`resource-${format.toLowerCase()}`),
      format,
      readerType: 'reflowable'
    }))
  });

  assert.deepEqual(book.resources.map((item) => item.format), formats);
});

test('rejects the removed generic KINDLE resource format', () => {
  assert.throws(
    () => mapBookView({
      id: 'book-1',
      sourceNodeId: 'book-source-node',
      title: 'Book',
      resources: [{ ...resource('resource-kindle'), format: 'KINDLE' }]
    }),
    /Unsupported resource format: KINDLE/
  );
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

test('regenerates a Resource cover synchronously and returns the actual update result', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  let requestedMethod = '';
  globalThis.fetch = async (input, init) => {
    requestedUrl = String(input);
    requestedMethod = init?.method ?? '';
    return new Response(JSON.stringify({ ok: true, data: {
      targetType: 'RESOURCE', targetId: 'resource/3', updatedResourceIds: ['resource/3'],
      skipped: [], sourceNodeUpdated: false, bookUpdated: false
    } }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    });
  };
  try {
    const result = await regenerateResourceCover('book/1', 'resource/3');
    assert.deepEqual(result.updatedResourceIds, ['resource/3']);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, '/api/books/book%2F1/resources/resource%2F3/cover/regenerate');
  assert.equal(requestedMethod, 'POST');
});

test('regenerates a SourceNode cover through the SourceNode endpoint without a representative Resource', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  globalThis.fetch = async (input) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({ ok: true, data: {
      targetType: 'SOURCE_NODE', targetId: 'source/1', updatedResourceIds: ['resource/1'],
      skipped: [{ resourceId: 'resource/2', reason: 'LOCAL_COVER_NOT_FOUND' }],
      sourceNodeUpdated: true, bookUpdated: false
    } }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    });
  };
  try {
    const result = await regenerateSourceNodeCover('book/1', 'source/1');
    assert.equal(result.sourceNodeUpdated, true);
    assert.deepEqual(result.updatedResourceIds, ['resource/1']);
    assert.deepEqual(result.skipped, [{ resourceId: 'resource/2', reason: 'LOCAL_COVER_NOT_FOUND' }]);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, '/api/books/book%2F1/source-nodes/source%2F1/cover/regenerate');
});

test('replaces Book tags through a one-book metadata operation', async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: unknown = null;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({ ok: true, data: { updated: 1 } }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    await replaceBookTags('book-1', ['Fantasy', 'Old'], ['fantasy', 'New']);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(requestBody, { ids: ['book-1'], fields: {}, addTags: ['New'], removeTags: ['Old'] });
});

test('uses aggregate Book operations for reading status and source deletion', async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; body: unknown }> = [];
  globalThis.fetch = async (input, init) => {
    requests.push({ url: String(input), body: JSON.parse(String(init?.body)) });
    return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    await updateBookReadingStatus('book-1', 'FINISHED');
    await deleteBookSources('book-1');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(requests, [
    { url: '/api/library/operations/books/reading-status', body: { ids: ['book-1'], status: 'FINISHED' } },
    { url: '/api/library/operations/books/delete-sources', body: { ids: ['book-1'], confirmation: 'DELETE_SOURCE_FILES' } }
  ]);
});

test('regenerates the Book image through a one-book cover operation', async () => {
  const originalFetch = globalThis.fetch;
  const requestedFields: Record<string, string> = {};
  globalThis.fetch = async (_input, init) => {
    assert.ok(init?.body instanceof FormData);
    init.body.forEach((value, key) => { requestedFields[key] = String(value); });
    return new Response(JSON.stringify({ ok: true, data: { updated: 1, skipped: [], operation: { id: 'op-cover' } } }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const result = await regenerateBookImage('book-1');
    assert.equal(result.updated, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedFields.ids, '["book-1"]');
  assert.equal(requestedFields.action, 'regenerate');
});

test('removes the custom Book cover through the Book source presentation contract', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  const requestedFields: Record<string, string> = {};
  globalThis.fetch = async (input, init) => {
    requestedUrl = String(input);
    assert.ok(init?.body instanceof FormData);
    init.body.forEach((value, key) => { requestedFields[key] = String(value); });
    return new Response(JSON.stringify({ ok: true, data: {} }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    await removeBookCover({ id: 'book/1', sourceNodeId: 'source/1', title: 'Updated', description: 'Description' });
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, '/api/books/book%2F1/source-nodes/source%2F1');
  assert.equal(requestedFields.removeCover, 'true');
  assert.equal(requestedFields.title, 'Updated');
});

test('maps complete recognized metadata candidates without truncating optional fields', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ ok: true, data: {
    message: null,
    candidates: [{
      id: 'subject-1', source: 'douban', title: '标题', author: '作者', description: '简介',
      tags: ['漫画'], seriesName: '系列', seriesIndex: 2, publisher: '出版社',
      publishedAt: '2026-08-26T00:00:00Z', language: 'zh-CN', isbn: '9780000000001',
      identifier: 'subject:1', narrator: '朗读者', abridged: false, resourceIndex: 3,
      coverUrl: 'https://example.test/cover.jpg', confidence: 0.91
    }]
  } }), { status: 200, headers: { 'content-type': 'application/json' } });
  try {
    const result = await searchSourceNodeMetadata('book-1', 'node-1', 'douban', '标题');
    assert.deepEqual(result.candidates[0], {
      id: 'subject-1', source: 'douban', title: '标题', author: '作者', description: '简介',
      tags: ['漫画'], seriesName: '系列', seriesIndex: 2, publisher: '出版社',
      publishedAt: '2026-08-26T00:00:00Z', language: 'zh-CN', isbn: '9780000000001',
      identifier: 'subject:1', narrator: '朗读者', abridged: false, resourceIndex: 3,
      coverUrl: 'https://example.test/cover.jpg', confidence: 0.91
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sends explicit recognized metadata fields and parses partial cover failure', async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: unknown = null;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({ ok: true, data: {
      appliedFields: ['book.author'], skippedFields: [], coverStatus: 'failed'
    } }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const result = await applyRecognizedMetadata('book-1', {
      scope: 'book', resourceId: null,
      candidate: {
        id: 'subject-1', source: 'douban', title: null, author: '作者', description: null,
        tags: [], seriesName: null, seriesIndex: null, publisher: null, publishedAt: null,
        language: null, isbn: null, identifier: null, narrator: null, abridged: null,
        resourceIndex: null, coverUrl: 'https://example.test/cover.jpg', confidence: 0.9
      },
      fields: ['book.author', 'book.cover']
    });
    assert.equal(result.coverStatus, 'failed');
    assert.deepEqual(result.appliedFields, ['book.author']);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(requestBody, {
    scope: 'book', resourceId: null,
    candidate: {
      id: 'subject-1', source: 'douban', title: null, author: '作者', description: null,
      tags: [], seriesName: null, seriesIndex: null, publisher: null, publishedAt: null,
      language: null, isbn: null, identifier: null, narrator: null, abridged: null,
      resourceIndex: null, coverUrl: 'https://example.test/cover.jpg', confidence: 0.9
    },
    fields: ['book.author', 'book.cover']
  });
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
