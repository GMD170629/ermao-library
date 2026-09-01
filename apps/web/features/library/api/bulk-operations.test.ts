import assert from 'node:assert/strict';
import test from 'node:test';
import {
  applyBulkBookFindReplace,
  parseBulkFindReplacePreview,
  updateBulkBookCovers,
  updateBulkBookMetadata,
  updateBulkBookReadingStatus
} from './bulk-operations';

test('parses Book and Resource find-replace preview items', () => {
  const preview = parseBulkFindReplacePreview({
    changedBooks: 1,
    changedValues: 2,
    items: [
      { bookId: 'book-1', title: '图书', before: '卷一', after: '册一', resourceId: 'resource-1' },
      { bookId: 'book-1', title: '图书', before: ['临时'], after: ['精选'], resourceId: null }
    ]
  });

  assert.equal(preview.changedValues, 2);
  assert.equal(preview.items[0]?.resourceId, 'resource-1');
  assert.deepEqual(preview.items[1]?.after, ['精选']);
});

test('uploads covers through the canonical Book operation endpoint', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  let requestedBody: FormData | undefined;
  globalThis.fetch = async (input: string | URL | Request, init?: RequestInit) => {
    requestedUrl = String(input);
    requestedBody = init?.body instanceof FormData ? init.body : undefined;
    return new Response(JSON.stringify({
      ok: true,
      data: { updated: 1, skipped: [], operation: { id: 'op-cover' } }
    }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const result = await updateBulkBookCovers({
      ids: ['book-1'],
      action: 'compress',
      ratio: '2:3',
      quality: 82,
      maxDimension: 1600
    });
    assert.equal(requestedUrl, '/api/library/operations/books/covers');
    assert.equal(requestedBody?.get('ids'), '["book-1"]');
    assert.equal(requestedBody?.get('action'), 'compress');
    assert.equal(result.operationId, 'op-cover');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('returns completed cover regeneration counts and skip reasons without task fields', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    ok: true,
    data: {
      updated: 1,
      skipped: [{ bookId: 'book-2', reason: 'NO_LOCAL_COVER' }],
      operation: { id: 'op-cover' }
    }
  }), { status: 200, headers: { 'content-type': 'application/json' } });
  try {
    const result = await updateBulkBookCovers({
      ids: ['book-1', 'book-2'],
      action: 'regenerate',
      ratio: '2:3',
      quality: 82,
      maxDimension: 1600
    });
    assert.equal(result.updated, 1);
    assert.deepEqual(result.skipped, [{ bookId: 'book-2', reason: 'NO_LOCAL_COVER' }]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('uses only canonical auditable bulk operation endpoints', async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; body: unknown }> = [];
  globalThis.fetch = async (input: string | URL | Request, init?: RequestInit) => {
    requests.push({ url: String(input), body: JSON.parse(String(init?.body)) });
    return new Response(JSON.stringify({
      ok: true,
      data: { updated: 2, changedValues: 2, operation: { id: 'op-1' } }
    }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    await updateBulkBookMetadata({
      ids: ['book-1', 'book-2'],
      fields: { author: '新作者' },
      addTags: ['历史'],
      removeTags: ['历史']
    });
    await applyBulkBookFindReplace({
      ids: ['book-1'],
      field: 'title',
      find: '旧',
      replacement: '新',
      regex: false,
      caseSensitive: false,
      startNumber: 1
    });
    await updateBulkBookReadingStatus({ ids: ['book-1'], status: 'FINISHED' });

    assert.deepEqual(requests.map((request) => request.url), [
      '/api/library/operations/books/metadata',
      '/api/library/operations/books/find-replace',
      '/api/library/operations/books/reading-status'
    ]);
    assert.deepEqual(requests[0]?.body, {
      ids: ['book-1', 'book-2'],
      fields: { author: '新作者' },
      addTags: ['历史'],
      removeTags: ['历史']
    });
    assert.equal(requests.some((request) => request.url.includes('/api/books/bulk')), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
