import assert from 'node:assert/strict';
import test from 'node:test';
import exactRequest from '../../../../packages/reader-contracts/fixtures/exact-reflowable-request.json';
import { parsePublicationLocation } from '@shuku/reader-core';
import { MemoryReaderStorage } from './memory-storage';
import { ReaderProgressConflictError, exactProgressKey } from './model';
import { ReaderProgressSyncCoordinator } from './sync-coordinator';

const locator = parsePublicationLocation(exactRequest.locator);
if (!locator) throw new Error('invalid exact fixture');
const input = { serverIdentity: 'https://library.example', userId: 'user-1', bookId: 'book-1', resourceId: 'resource-1', baseRevision: 17, locator, displayPercent: 42 } as const;

test('migrates a fingerprint-keyed local record into the book and resource progress slot', async () => {
  const storage = new MemoryReaderStorage();
  const clientId = await storage.getClientId();
  const identity = { serverIdentity: input.serverIdentity, userId: input.userId, clientId, bookId: input.bookId, resourceId: input.resourceId };
  await storage.putExactProgress({
    ...identity,
    key: 'legacy-fingerprint-key',
    schemaVersion: 1,
    locator,
    displayPercent: 42,
    revision: 17,
    capturedAtEpochMillis: 99
  });

  const migrated = await storage.getExactProgress(identity);

  assert.equal(migrated?.key, exactProgressKey(identity));
  assert.equal(await storage.getExactProgress({ ...identity, bookId: 'another-book' }), null);
});

test('atomically persists the latest exact locator before uploading the canonical request', async () => {
  const storage = new MemoryReaderStorage(); const sent: unknown[] = [];
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (upload) => { sent.push(upload.request); return { schemaVersion: 4, clientId: upload.request.clientId, revision: 18, locator, displayPercent: 42, receivedAtEpochMillis: 100 }; }, { debounceMs: 0, now: () => 99 });
  coordinator.activateUser('user-1'); await coordinator.enqueue(input); await coordinator.flushNow();
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { ...exactRequest, clientId: (sent[0] as { clientId: string }).clientId, mutationId: (sent[0] as { mutationId: string }).mutationId, capturedAtEpochMillis: 99 });
  assert.equal((await storage.listPendingProgress('user-1')).length, 0);
});

test('keeps network failures durable but drops a rejected mutation and raises a session notice', async () => {
  const storage = new MemoryReaderStorage();
  const offline = new ReaderProgressSyncCoordinator(storage, async () => { throw new Error('offline'); }, { debounceMs: 0 });
  offline.activateUser('user-1'); await offline.enqueue(input); await offline.flushNow();
  const [pending] = await storage.listPendingProgress('user-1'); assert.ok(pending);
  const remoteLocator = parsePublicationLocation({
    ...locator,
    engineLocator: locator.kind === 'reflowable' ? {
      ...locator.engineLocator,
      platform: 'ios',
      payload: {
        ...locator.engineLocator.payload,
        locations: { cssSelector: '#remote' },
        text: { highlight: 'remote anchor' }
      }
    } : undefined
  });
  assert.ok(remoteLocator);
  const conflict = { clientId: 'ios-client', revision: 19, locator: remoteLocator, displayPercent: 44, receivedAtEpochMillis: 101 };
  const retry = new ReaderProgressSyncCoordinator(storage, async () => { throw new ReaderProgressConflictError(conflict); }, { debounceMs: 0 });
  const clientId = await storage.getClientId();
  retry.beginSession('resource-1', clientId, { schemaVersion: 4, clientId: 'server-client', revision: 17, locator, displayPercent: 42, receivedAtEpochMillis: 90 }, locator);
  retry.activateUser('user-1');
  await new Promise((resolve) => setTimeout(resolve, 0));
  await retry.flushNow();
  assert.equal(await storage.getPendingProgress(pending.key), null);
  assert.equal(retry.getLatestServerSnapshot('resource-1')?.revision, 19);
});

test('lifecycle checks ignore 304, same client, and the same exact anchor', async () => {
  const storage = new MemoryReaderStorage();
  const clientId = await storage.getClientId();
  const snapshots = [
    { kind: 'unchanged' as const, etag: '"reader-progress-4"' },
    { kind: 'current' as const, etag: '"reader-progress-5"', snapshot: { schemaVersion: 4 as const, clientId, revision: 5, locator, displayPercent: 42, receivedAtEpochMillis: 101 } },
    { kind: 'current' as const, etag: '"reader-progress-6"', snapshot: { schemaVersion: 4 as const, clientId: 'ios-client', revision: 6, locator, displayPercent: 42, receivedAtEpochMillis: 102 } }
  ];
  const coordinator = new ReaderProgressSyncCoordinator(storage, async () => { throw new Error('unused'); }, {
    debounceMs: 0,
    queryTransport: async () => snapshots.shift() ?? { kind: 'unchanged', etag: null }
  });
  coordinator.beginSession('resource-1', clientId, null, locator);
  assert.equal(await coordinator.checkRemoteProgress('resource-1'), null);
  assert.equal(await coordinator.checkRemoteProgress('resource-1'), null);
  assert.equal(await coordinator.checkRemoteProgress('resource-1'), null);
});

test('the next genuinely different exact location rebases onto the remote revision', async () => {
  const storage = new MemoryReaderStorage(); const sent: Array<{ baseRevision: number }> = [];
  const moved = parsePublicationLocation({
    ...locator,
    engineLocator: locator.kind === 'reflowable' ? {
      ...locator.engineLocator,
      payload: { ...locator.engineLocator.payload, locations: { cssSelector: '#next' }, text: { highlight: 'next block' } }
    } : undefined
  });
  assert.ok(moved);
  const remote = parsePublicationLocation({
    ...locator,
    engineLocator: locator.kind === 'reflowable' ? {
      ...locator.engineLocator,
      platform: 'ios',
      payload: { ...locator.engineLocator.payload, locations: { cssSelector: '#remote' }, text: { highlight: 'remote block' } }
    } : undefined
  });
  assert.ok(remote);
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (upload) => {
    sent.push({ baseRevision: upload.request.baseRevision });
    return { schemaVersion: 4, clientId: upload.request.clientId, revision: 10, locator: upload.request.locator, displayPercent: 45, receivedAtEpochMillis: 110 };
  }, {
    debounceMs: 0,
    queryTransport: async () => ({
      kind: 'current', etag: '"reader-progress-9"',
      snapshot: { schemaVersion: 4, clientId: 'ios-client', revision: 9, locator: remote, displayPercent: 44, receivedAtEpochMillis: 100 }
    })
  });
  const clientId = await storage.getClientId();
  coordinator.activateUser('user-1');
  coordinator.beginSession('resource-1', clientId, { schemaVersion: 4, clientId: 'server', revision: 4, locator, displayPercent: 42, receivedAtEpochMillis: 90 }, locator);
  await coordinator.checkRemoteProgress('resource-1');
  await coordinator.enqueue({ ...input, locator: moved, baseRevision: 4 });
  await coordinator.flushNow();
  assert.deepEqual(sent, [{ baseRevision: 9 }]);
});
