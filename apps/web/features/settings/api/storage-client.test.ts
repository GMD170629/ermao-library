import assert from 'node:assert/strict';
import test from 'node:test';
import { parseStorageUsage, getStorageUsage, clearStorage } from './storage-client';

test('storage validates category totals and rejects malformed wire data', () => {
  assert.deepEqual(parseStorageUsage({ ok: true, data: { root: '/storage', categories: [{ id: 'cache', sizeBytes: 4, clearable: true }] } }).categories[0], { id: 'cache', sizeBytes: 4, clearable: true });
  for (const row of [{ id: 'disk', sizeBytes: 1, clearable: false }, { id: 'cache', sizeBytes: -1, clearable: true }, { id: 'cache', sizeBytes: 1 }]) {
    assert.throws(() => parseStorageUsage({ ok: true, data: { root: '/storage', categories: [row] } }));
  }
});

test('cleanup uses one category and follow-up reads only the affected category', async () => {
  const previous = globalThis.fetch;
  const calls: Array<{ path: string; method?: string }> = [];
  globalThis.fetch = async (path, options) => {
    calls.push({ path: String(path), method: options?.method });
    return Response.json({ ok: true, data: { root: '/storage', categories: [{ id: 'cache', sizeBytes: 0, clearable: true }] } });
  };
  try {
    await clearStorage('cache', new AbortController().signal);
    await getStorageUsage(new AbortController().signal, 'cache');
    assert.deepEqual(calls, [{ path: '/api/system/storage/cache', method: 'DELETE' }, { path: '/api/system/storage?category=cache', method: 'GET' }]);
  } finally {
    globalThis.fetch = previous;
  }
});
