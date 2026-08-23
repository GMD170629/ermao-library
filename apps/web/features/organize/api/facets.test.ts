import assert from 'node:assert/strict';
import test from 'node:test';
import {
  fetchLibraryFacets,
  mergeLibraryFacets,
  parseLibraryFacetPage,
  renameLibraryFacet
} from './facets';

test('parses the canonical facet page', () => {
  const page = parseLibraryFacetPage({
    facets: [{
      id: 'facet-author',
      kind: 'AUTHOR',
      name: '林川',
      normalizedName: '林川',
      aliases: ['林 川'],
      bookCount: 3,
      updatedAt: '2026-08-22T00:00:00Z'
    }],
    page: 1,
    pageSize: 20,
    total: 1,
    totalPages: 1
  });

  assert.equal(page.facets[0]?.kind, 'AUTHOR');
  assert.equal(page.facets[0]?.bookCount, 3);
});

test('rejects unsupported facet kinds', () => {
  assert.throws(() => parseLibraryFacetPage({
    facets: [{
      id: 'publisher',
      kind: 'PUBLISHER',
      name: '出版社',
      normalizedName: '出版社',
      aliases: [],
      bookCount: 1,
      updatedAt: '2026-08-22T00:00:00Z'
    }],
    page: 1,
    pageSize: 20,
    total: 1,
    totalPages: 1
  }), /Invalid library facet kind/);
});

test('uses only canonical facet endpoints for list, rename and merge', async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input: string | URL | Request, init?: RequestInit) => {
    requests.push({ url: String(input), init });
    const data = String(input).includes('?')
      ? { facets: [], page: 1, pageSize: 20, total: 0, totalPages: 1 }
      : { operation: { id: 'op-1' } };
    return new Response(JSON.stringify({ ok: true, data }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    });
  };
  try {
    await fetchLibraryFacets({ kind: 'TAG', page: 1, pageSize: 20, search: '科幻' });
    await renameLibraryFacet('facet/author', '新作者');
    await mergeLibraryFacets({
      kind: 'TAG',
      targetId: 'tag-target',
      sourceIds: ['tag-source']
    });

    assert.match(requests[0]?.url ?? '', /^\/api\/library\/facets\?/);
    assert.match(requests[0]?.url ?? '', /search=%E7%A7%91%E5%B9%BB/);
    assert.equal(requests[1]?.url, '/api/library/facets/facet%2Fauthor');
    assert.equal(requests[1]?.init?.method, 'PATCH');
    assert.equal(requests[2]?.url, '/api/library/facets/merge');
    assert.equal(requests[2]?.init?.method, 'POST');
    assert.deepEqual(JSON.parse(String(requests[2]?.init?.body)), {
      kind: 'TAG',
      targetId: 'tag-target',
      sourceIds: ['tag-source']
    });
    assert.equal(requests.some((request) => request.url.includes('/categories')), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
