import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchShelf, fetchShelfNavigation, writeShelf } from './client';

test('shelf browsing and writes request a page without the complete membership', async () => {
  const original = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    return Response.json({ ok: true, data: { shelf: {
      id: 'smart', name: 'EPUB', kind: 'SMART', bookCount: 15000, books: [],
      createdAt: '1970-01-01T00:00:00Z', updatedAt: '1970-01-01T00:00:00Z'
    } } });
  };
  try {
    const input = { name: 'EPUB', kind: 'SMART' as const, rules: { conditions: [] } };
    assert.equal((await writeShelf(null, input)).bookIds, undefined);
    await writeShelf('smart', input);
    await fetchShelf('smart', { page: 2, pageSize: 24, includeIds: false });
    assert.deepEqual(requests.map((request) => request.url), [
      '/api/shelves?includeBookIds=false',
      '/api/shelves/smart?includeBookIds=false',
      '/api/shelves/smart?page=2&pageSize=24&includeBookIds=false'
    ]);
    assert.deepEqual(JSON.parse(String(requests[0].init?.body)), input);
    // Membership editors retain the explicit complete-selection request.
    await fetchShelf('static', { page: 1, pageSize: 24, includeIds: true });
    assert.equal(requests[3].url, '/api/shelves/static?page=1&pageSize=24&includeBookIds=true');
  } finally { globalThis.fetch = original; }
});


test('sidebar shelf navigation does not request book counts, previews, or rules', async () => {
  const original = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async (url) => {
    requests.push(String(url));
    return Response.json({ ok: true, data: { shelves: [{
      id: 'smart', name: 'EPUB', kind: 'SMART', collectionIds: ['collection']
    }] } });
  };
  try {
    assert.deepEqual(await fetchShelfNavigation(), [{
      id: 'smart', name: 'EPUB', kind: 'SMART', collectionIds: ['collection']
    }]);
    assert.deepEqual(requests, ['/api/shelves/navigation']);
  } finally { globalThis.fetch = original; }
});
