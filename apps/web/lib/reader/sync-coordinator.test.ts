import assert from 'node:assert/strict';
import test from 'node:test';
import exactRequest from '../../../../packages/reader-contracts/fixtures/exact-reflowable-request.json';
import { parsePublicationLocation } from '@shuku/reader-core';
import { MemoryReaderStorage } from './memory-storage';
import { ReaderProgressConflictError } from './model';
import { ReaderProgressSyncCoordinator } from './sync-coordinator';

const locator = parsePublicationLocation(exactRequest.locator);
if (!locator) throw new Error('invalid exact fixture');
const input = { serverIdentity: 'https://library.example', userId: 'user-1', workId: 'work-1', volumeId: 'volume-1', baseRevision: 17, locator, displayPercent: 42 } as const;

test('atomically persists the latest exact locator before uploading the canonical request', async () => {
  const storage = new MemoryReaderStorage(); const sent: unknown[] = [];
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (upload) => { sent.push(upload.request); return { schemaVersion: 4, revision: 18, locator, displayPercent: 42, receivedAtEpochMillis: 100 }; }, { debounceMs: 0, now: () => 99 });
  coordinator.activateUser('user-1'); await coordinator.enqueue(input); await coordinator.flushNow();
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { ...exactRequest, clientId: (sent[0] as { clientId: string }).clientId, mutationId: (sent[0] as { mutationId: string }).mutationId, capturedAtEpochMillis: 99 });
  assert.equal((await storage.listPendingProgress('user-1')).length, 0);
});

test('keeps network failures durable and persists revision conflicts without overwriting', async () => {
  const storage = new MemoryReaderStorage();
  const offline = new ReaderProgressSyncCoordinator(storage, async () => { throw new Error('offline'); }, { debounceMs: 0 });
  offline.activateUser('user-1'); await offline.enqueue(input); await offline.flushNow();
  const [pending] = await storage.listPendingProgress('user-1'); assert.ok(pending);
  const conflict = { revision: 19, locator, displayPercent: 44, receivedAtEpochMillis: 101 };
  const retry = new ReaderProgressSyncCoordinator(storage, async () => { throw new ReaderProgressConflictError(conflict); }, { debounceMs: 0 });
  retry.activateUser('user-1'); await retry.flushNow();
  assert.ok(await storage.getProgressConflict(pending.key));
  assert.ok(await storage.getPendingProgress(pending.key));
});
