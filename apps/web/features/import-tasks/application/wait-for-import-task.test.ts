import assert from 'node:assert/strict';
import test from 'node:test';
import { waitForImportTask } from './wait-for-import-task';

function taskResponse(state: 'RUNNING' | 'SUCCEEDED'): Response {
  return new Response(JSON.stringify({
    ok: true,
    data: {
      task: {
        id: 'task-1',
        kind: 'CONTINUE_SOURCE',
        libraryId: 'library-1',
        sourceNodeId: 'source-1',
        state,
        createdAt: '2026-09-02T00:00:00Z'
      }
    }
  }), { status: 200, headers: { 'content-type': 'application/json' } });
}

test('waits for the canonical scan task to reach a terminal state', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => taskResponse(++calls === 1 ? 'RUNNING' : 'SUCCEEDED');
  try {
    const task = await waitForImportTask('task-1', {
      pollIntervalMs: 0,
      timeoutMs: 1_000
    });
    assert.equal(task?.state, 'SUCCEEDED');
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
