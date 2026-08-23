import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clearManagementEvents,
  fetchManagementEvents,
  updateSystemLogLimit
} from './events';

test('uses typed management event and log-setting endpoints', async () => {
  const requested: Array<{ url: string; method: string }> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    requested.push({ url, method });
    const data = method === 'DELETE'
      ? { deleted: 2 }
      : url.includes('log-settings')
        ? { storage: { sizeBytes: 10, maxBytes: 1024 } }
        : {
            events: [],
            total: 0,
            totalPages: 1,
            storage: { sizeBytes: 10, maxBytes: 1024 }
          };
    return new Response(JSON.stringify({ ok: true, data }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  };
  try {
    const page = await fetchManagementEvents(new URLSearchParams({ page: '1' }));
    assert.equal(page.total, 0);
    assert.equal(await clearManagementEvents(), 2);
    assert.equal((await updateSystemLogLimit(1024)).maxBytes, 1024);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(requested, [
    { url: '/api/management/events?page=1', method: 'GET' },
    { url: '/api/management/events', method: 'DELETE' },
    { url: '/api/system/log-settings', method: 'PUT' }
  ]);
});
