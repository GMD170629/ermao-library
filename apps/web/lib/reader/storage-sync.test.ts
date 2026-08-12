import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeReaderPreferences } from '@shuku/reader-core';
import { MemoryReaderStorage } from './memory-storage';
import { migrateLegacyProgressCandidate } from './migrations';
import { ReaderPreferenceRepository } from './preferences';
import { readStoredPreferenceSnapshot } from './storage';
import { ReaderProgressSyncCoordinator } from './sync-coordinator';
import { READER_PROGRESS_DEBOUNCE_MS, exactProgressKey, type ProgressSaveInput } from './model';

function progress(overrides: Partial<ProgressSaveInput> = {}): ProgressSaveInput {
  return {
    serverIdentity: 'https://library.example',
    userId: 'user-1',
    workId: 'work-1',
    volumeId: 'volume-1',
    localContentFingerprint: 'sha256:local-volume-1',
    contentFingerprint: 'volume-version-1',
    location: { kind: 'comic', volumeId: 'volume-1', pageIndex: 1 },
    percent: 0,
    ...overrides
  };
}

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

test('preference snapshots remain isolated by user and work', async () => {
  const storage = new MemoryReaderStorage();
  const repository = new ReaderPreferenceRepository(storage);
  const serverDefault = normalizeReaderPreferences({ theme: 'day', epub: { fontSize: 20 } });
  await repository.save('user-1', 'work-1', normalizeReaderPreferences({ appearance: { theme: 'black' } }, serverDefault), serverDefault);
  assert.equal((await repository.resolve('user-1', 'work-1', serverDefault)).preferences.appearance.theme, 'black');
  assert.equal((await repository.resolve('user-2', 'work-1', serverDefault)).source, 'inherited');
});

test('legacy preference reads rewrite one complete v4 preference snapshot', async () => {
  const rewrites: unknown[] = [];
  const migrated = await readStoredPreferenceSnapshot({
    schemaVersion: 2,
    preferences: { appearance: { theme: 'night' }, epub: { fontSize: 22 } },
    updatedAt: 123
  }, 'user-1', 'work-1', async (snapshot) => rewrites.push(snapshot));
  assert.ok(migrated);
  assert.equal(migrated.schemaVersion, 4);
  assert.equal(migrated.preferences.appearance.theme, 'night');
  assert.deepEqual(rewrites, [migrated]);
});

test('exact progress identity is stable and excludes authorization version', async () => {
  const storage = new MemoryReaderStorage();
  const clientId = await storage.getClientId();
  const identity = {
    serverIdentity: 'https://library.example',
    userId: 'user-1',
    clientId,
    volumeId: 'volume-1',
    localContentFingerprint: 'volume-version-1'
  };
  const exact = {
    ...identity,
    key: exactProgressKey(identity),
    schemaVersion: 1 as const,
    workId: 'work-1',
    location: { kind: 'pdf' as const, pageNumber: 12 },
    percent: 30,
    updatedAtEpochMillis: 100
  };
  await storage.putExactProgress(exact);
  assert.deepEqual(await storage.getExactProgress(identity), exact);
  assert.equal('listProgress' in storage, false);
  assert.equal('getProgressLease' in storage, false);
});

test('500ms is the production trailing debounce and a burst saves/uploads only the latest position', async () => {
  assert.equal(READER_PROGRESS_DEBOUNCE_MS, 500);
  const storage = new MemoryReaderStorage();
  const sent: number[] = [];
  let now = 100;
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (upload) => {
    sent.push(upload.snapshot.percent);
    return upload.snapshot;
  }, { debounceMs: 10, now: () => now });
  coordinator.activateUser('user-1');
  const first = coordinator.enqueue(progress({ percent: 10 }));
  now = 200;
  const second = coordinator.enqueue(progress({
    percent: 20,
    location: { kind: 'comic', volumeId: 'volume-1', pageIndex: 2 }
  }));
  await coordinator.flushNow();
  const [firstExact, secondExact] = await Promise.all([first, second]);
  assert.equal(firstExact.location.kind === 'comic' ? firstExact.location.pageIndex : 0, 2);
  assert.deepEqual(firstExact, secondExact);
  assert.deepEqual(sent, [20]);
});

test('a slow upload keeps only one latest in-memory slot', async () => {
  const storage = new MemoryReaderStorage();
  const sent: number[] = [];
  let releaseFirst: () => void = () => {};
  const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (upload) => {
    sent.push(upload.snapshot.percent);
    if (sent.length === 1) await firstGate;
    return upload.snapshot;
  }, { debounceMs: 5 });
  coordinator.activateUser('user-1');

  const firstSaved = coordinator.enqueue(progress({ percent: 10 }));
  void coordinator.flushNow();
  await firstSaved;
  const middleSaved = coordinator.enqueue(progress({ percent: 20 }));
  const latestSaved = coordinator.enqueue(progress({ percent: 30 }));
  await wait(15);
  await Promise.all([middleSaved, latestSaved]);
  assert.deepEqual(sent, [10]);
  releaseFirst();
  await coordinator.flushNow();
  assert.deepEqual(sent, [10, 30]);
});

test('a lifecycle upload timeout aborts the in-flight request and drops the memory slot', async () => {
  const storage = new MemoryReaderStorage();
  let aborted = false;
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (_upload, signal) => {
    await new Promise<void>((resolve) => {
      signal.addEventListener('abort', () => {
        aborted = true;
        resolve();
      }, { once: true });
    });
    throw new DOMException('aborted', 'AbortError');
  }, { debounceMs: 0 });
  coordinator.activateUser('user-1');
  await coordinator.enqueue(progress({ percent: 10 }));
  await coordinator.flushNow({ timeoutMs: 5 });
  await wait(5);
  assert.equal(aborted, true);
});

test('network failure is discarded without retry while local exact progress remains', async () => {
  const storage = new MemoryReaderStorage();
  let attempts = 0;
  const coordinator = new ReaderProgressSyncCoordinator(storage, async () => {
    attempts += 1;
    throw new Error('offline');
  }, { debounceMs: 5 });
  coordinator.activateUser('user-1');
  const saved = await coordinator.enqueue(progress({ percent: 40 }));
  await coordinator.flushNow();
  await wait(15);
  assert.equal(attempts, 1);
  assert.deepEqual(await storage.getExactProgress(saved), saved);

  await coordinator.enqueue(progress({ percent: 41 }));
  await coordinator.flushNow();
  assert.equal(attempts, 2);
});

test('untrusted percent saves exact location locally but does not upload', async () => {
  const storage = new MemoryReaderStorage();
  let attempts = 0;
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (upload) => {
    attempts += 1;
    return upload.snapshot;
  }, { debounceMs: 5 });
  coordinator.activateUser('user-1');
  const exact = await coordinator.enqueue(progress({ percent: null }));
  await coordinator.flushNow();
  assert.equal(exact.percent, null);
  assert.equal(attempts, 0);
});

test('legacy progress migration commits exact data without creating a sync queue', async () => {
  const storage = new MemoryReaderStorage();
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (upload) => upload.snapshot);
  const result = await migrateLegacyProgressCandidate({
    userId: 'user-1',
    workId: 'work-1',
    volumeId: 'volume-1',
    contentFingerprint: 'volume-version-1',
    readerType: 'pdf',
    progress: { page: 8, percent: 25 }
  }, coordinator, storage);
  assert.equal(result.status, 'migrated');
  const clientId = await storage.getClientId();
  const exact = await storage.getExactProgress({
    serverIdentity: 'same-origin',
    userId: 'user-1',
    clientId,
    volumeId: 'volume-1',
    localContentFingerprint: 'volume-version-1'
  });
  assert.equal(exact?.location.kind, 'pdf');
  assert.equal(exact?.percent, 25);
});
