import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clearManagementEvents,
  fetchManagementEventDetail,
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

test('loads one event detail with a full diagnostic stack', async () => {
  const requested: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    requested.push(`${init?.method ?? 'GET'} ${String(input)}`);
    const data = {
      id: 'diag_1',
      level: 'error',
      source: 'import',
      actorType: 'system',
      action: 'api.request_failed',
      targetType: 'importTask',
      targetId: 'task-1',
      message: 'boom',
      metadata: {
        stage: 'scan',
        diagnostics: {
          exceptionType: 'builtins.RuntimeError',
          traceback: 'Traceback (most recent call last):\nRuntimeError: boom'
        }
      },
      createdAt: '2026-01-01T00:00:00.000Z'
    };
    return new Response(JSON.stringify({ ok: true, data }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  };
  try {
    const detail = await fetchManagementEventDetail('diag_1');
    assert.equal(detail.id, 'diag_1');
    const diagnostics = detail.metadata.diagnostics as { exceptionType: string };
    assert.equal(diagnostics.exceptionType, 'builtins.RuntimeError');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(requested, ['GET /api/management/events/diag_1']);
});
