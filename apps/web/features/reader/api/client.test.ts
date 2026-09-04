import assert from 'node:assert/strict';
import test from 'node:test';
import reflowableFixture from '../../../../../packages/reader-contracts/fixtures/reader-v5/reflowable-empty-highlight.json';
import {
  readerV5ProgressQueryTransport,
  readerV5ProgressTransport
} from './client';

function snapshot() {
  return {
    schemaVersion: 5 as const,
    revision: 1,
    clientId: 'web-test',
    mutationId: '00000000-0000-4000-8000-000000000001',
    capturedAtEpochMillis: 100,
    receivedAtEpochMillis: 101,
    position: reflowableFixture.position
  };
}

test('v5 progress GET rejects a legacy or malformed non-null snapshot', async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const progressSnapshot of [{ schemaVersion: 4, locator: {} }, { schemaVersion: 5, position: {} }]) {
      globalThis.fetch = async () => Response.json({ ok: true, data: { schemaVersion: 5, progressSnapshot } });
      await assert.rejects(
        readerV5ProgressQueryTransport('resource-1', null, new AbortController().signal),
        (reason: unknown) => reason instanceof Error && reason.message === 'READER_PROGRESS_RESPONSE_INVALID'
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('v5 progress GET preserves a valid opaque snapshot and PUT validates the v5 response', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ ok: true, data: { schemaVersion: 5, progressSnapshot: snapshot() } });
    const queried = await readerV5ProgressQueryTransport('resource-1', null, new AbortController().signal);
    assert.equal(queried.kind, 'current');
    if (queried.kind !== 'current' || !queried.snapshot) throw new Error('VALID_V5_QUERY_EXPECTED');
    assert.deepEqual(queried.snapshot.position, reflowableFixture.position);

    const upload = {
      resourceId: 'resource-1',
      request: {
        schemaVersion: 5 as const,
        clientId: 'web-test',
        mutationId: '00000000-0000-4000-8000-000000000001',
        capturedAtEpochMillis: 100,
        position: reflowableFixture.position
      }
    };
    const requestBodies: unknown[] = [];
    globalThis.fetch = async (_input, init) => {
      requestBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      return Response.json({ ok: true, data: {
        acceptedMutationId: upload.request.mutationId,
        acceptedRevision: 1,
        currentSnapshot: snapshot()
      } });
    };
    await readerV5ProgressTransport(upload, new AbortController().signal);
    assert.deepEqual(requestBodies, [upload.request]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
