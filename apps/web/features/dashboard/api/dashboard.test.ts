import assert from 'node:assert/strict';
import test from 'node:test';
import {
  fetchDashboardContinueReading,
  fetchDashboardRecentBooks,
  fetchDashboardRecentReading
} from './dashboard';

test('loads the three dashboard capabilities through their canonical endpoints', async () => {
  const requested: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const path = String(input);
    requested.push(path);
    const data = path.endsWith('continue-reading')
      ? { item: null }
      : { books: [] };
    return new Response(JSON.stringify({ ok: true, data }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  };
  try {
    assert.equal(await fetchDashboardContinueReading(), null);
    assert.deepEqual(await fetchDashboardRecentReading(), []);
    assert.deepEqual(await fetchDashboardRecentBooks(), []);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(requested, [
    '/api/dashboard/continue-reading',
    '/api/dashboard/recent-reading?limit=10',
    '/api/dashboard/recent-books?limit=10'
  ]);
});

test('rejects malformed dashboard book projections', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    ok: true,
    data: { books: [{ id: 'book-1', title: 'Book', author: null, progress: '0' }] }
  }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  try {
    await assert.rejects(fetchDashboardRecentBooks(), /Invalid dashboard field/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
