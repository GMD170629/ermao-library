import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchLibraryGroupings, parseLibraryGroupingPage } from './groupings';

test('parses paginated library groupings', () => {
  const page = parseLibraryGroupingPage({
    groups: [{
      id: 'series-1',
      name: '星海丛书',
      bookCount: 2,
      updatedAt: '2026-07-29T00:00:00Z'
    }],
    page: 1,
    pageSize: 48,
    total: 1,
    totalPages: 1
  });

  assert.equal(page.groups[0]?.name, '星海丛书');
  assert.equal(page.groups[0]?.bookCount, 2);
  assert.equal(page.total, 1);
});

test('rejects malformed library grouping counts', () => {
  assert.throws(
    () => parseLibraryGroupingPage({
      groups: [{
        id: 'author-1',
        name: '林川',
        bookCount: '2',
        updatedAt: '2026-07-29T00:00:00Z'
      }],
      page: 1,
      pageSize: 48,
      total: 1,
      totalPages: 1
    }),
    /Invalid library grouping field/
  );
});

test('loads groupings only from the canonical library endpoint', async () => {
  const requested: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    requested.push(String(input));
    return new Response(JSON.stringify({
      ok: true,
      data: {
        groups: [],
        page: 1,
        pageSize: 48,
        total: 0,
        totalPages: 1
      }
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  try {
    await fetchLibraryGroupings({ kind: 'SERIES', page: 1, pageSize: 48 });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(requested, ['/api/library/groupings?kind=SERIES&page=1&pageSize=48']);
  assert.equal(requested.some((url) => url.startsWith('/api/series')), false);
});
