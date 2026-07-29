import assert from 'node:assert/strict';
import test from 'node:test';
import { parseImportQueueClearOperation } from './clear-queue';

test('parses a completed import queue clear operation', () => {
  const operation = parseImportQueueClearOperation({
    id: 'queue-clear',
    queueName: 'import',
    action: 'clear',
    status: 'completed',
    messageCode: 'queue.clear.completed',
    requestedAt: '2026-07-29T00:00:00Z',
    startedAt: '2026-07-29T00:00:01Z',
    finishedAt: '2026-07-29T00:00:02Z',
    updatedAt: '2026-07-29T00:00:02Z'
  });

  assert.equal(operation.action, 'clear');
  assert.equal(operation.status, 'completed');
});

test('rejects a restart operation when waiting for queue clear', () => {
  assert.throws(
    () => parseImportQueueClearOperation({
      id: 'queue-restart',
      queueName: 'import',
      action: 'restart',
      status: 'waiting',
      messageCode: 'queue.restart.waiting',
      requestedAt: '2026-07-29T00:00:00Z',
      startedAt: null,
      finishedAt: null,
      updatedAt: '2026-07-29T00:00:00Z'
    }),
    /Invalid import queue clear operation/
  );
});
