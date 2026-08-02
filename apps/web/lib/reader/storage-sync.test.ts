import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeReaderPreferences } from '@shuku/reader-core';
import { MemoryReaderStorage } from './memory-storage';
import { migrateLegacyBrowserReaderState } from './browser-migration';
import { migrateLegacyPreferenceCandidate, migrateLegacyProgressCandidate } from './migrations';
import { ReaderPreferenceRepository } from './preferences';
import { readStoredPreferenceSnapshot } from './storage';
import { ReaderProgressSyncCoordinator } from './sync-coordinator';
import { toProgressPutBody, type ProgressMutation, type ProgressMutationInput, type ProgressSyncTransport } from './model';

function progress(overrides: Partial<ProgressMutationInput> = {}): ProgressMutationInput {
  return {
    userId: 'user-1',
    workId: 'work-1',
    volumeId: 'volume-1',
    contentFingerprint: 'sha256:content',
    location: { kind: 'comic', volumeId: 'volume-1', pageIndex: 1 },
    percent: 0,
    ...overrides
  };
}

test('preference snapshots are isolated by user/work and reset to server inheritance', async () => {
  const storage = new MemoryReaderStorage();
  const repository = new ReaderPreferenceRepository(storage);
  const serverDefault = normalizeReaderPreferences({ theme: 'day', epub: { fontSize: 20 } });

  const inherited = await repository.resolve('user-1', 'work-1', serverDefault);
  assert.equal(inherited.source, 'inherited');
  assert.equal(inherited.preferences.appearance.theme, 'day');

  await repository.save('user-1', 'work-1', normalizeReaderPreferences({ appearance: { theme: 'black' } }, serverDefault), serverDefault);
  const local = await repository.resolve('user-1', 'work-1', serverDefault);
  assert.equal(local.source, 'local');
  assert.equal(local.preferences.appearance.theme, 'black');
  assert.equal(local.preferences.epub.fontSize, 20);
  assert.equal((await repository.resolve('user-2', 'work-1', serverDefault)).source, 'inherited');

  const reset = await repository.reset('user-1', 'work-1', serverDefault);
  assert.equal(reset.appearance.theme, 'day');
  assert.equal((await repository.resolve('user-1', 'work-1', serverDefault)).source, 'inherited');
});

test('IndexedDB preference reads lazily rewrite V2 and malformed snapshots to one complete V3 snapshot', async () => {
  const legacy = {
    key: 'user-1::work-1',
    userId: 'user-1',
    workId: 'work-1',
    schemaVersion: 2,
    preferences: {
      schemaVersion: 2,
      appearance: { theme: 'night' },
      epub: { fontSize: 22, pageTurnAnimation: 'kindle' },
      comic: { mode: 'double' }
    },
    updatedAt: 123
  };
  const rewrites: unknown[] = [];
  const migrated = await readStoredPreferenceSnapshot(
    legacy,
    'user-1',
    'work-1',
    async (snapshot) => rewrites.push(snapshot),
    999
  );

  assert.ok(migrated);
  assert.equal(migrated.schemaVersion, 3);
  assert.equal(migrated.updatedAt, 123);
  assert.equal(migrated.preferences.schemaVersion, 3);
  assert.equal(migrated.preferences.appearance.theme, 'night');
  assert.equal(migrated.preferences.epub.fontSize, 22);
  assert.equal(migrated.preferences.epub.spreadMode, 'single');
  assert.equal(migrated.preferences.epub.pageTurnAnimation, 'slide');
  assert.equal(migrated.preferences.comic.mode, 'double');
  assert.equal(migrated.preferences.comic.pageTurnAnimation, 'slide');
  assert.deepEqual(rewrites, [migrated]);

  const canonicalRewrites: unknown[] = [];
  const canonical = await readStoredPreferenceSnapshot(
    migrated,
    'user-1',
    'work-1',
    async (snapshot) => canonicalRewrites.push(snapshot)
  );
  assert.deepEqual(canonical, migrated);
  assert.deepEqual(canonicalRewrites, []);

  const malformedRewrites: unknown[] = [];
  const malformed = await readStoredPreferenceSnapshot(
    { preferences: { epub: { spreadMode: 'invalid' } }, updatedAt: 'invalid' },
    'user-2',
    'work-2',
    async (snapshot) => malformedRewrites.push(snapshot),
    777
  );
  assert.equal(malformed?.updatedAt, 777);
  assert.equal(malformed?.preferences.epub.spreadMode, 'single');
  assert.equal(malformedRewrites.length, 1);
  assert.equal(await readStoredPreferenceSnapshot(undefined, 'user-3', 'work-3', async () => undefined), null);
});

test('outbox allocates strict sequences, coalesces a slot, and compare-deletes by mutation id', async () => {
  const storage = new MemoryReaderStorage();
  const first = await storage.enqueueProgress(progress(), 10);
  const replacement = await storage.enqueueProgress(progress({
    location: { kind: 'comic', volumeId: 'volume-1', pageIndex: 2 },
    percent: 10
  }), 20);
  const secondVolume = await storage.enqueueProgress(progress({
    volumeId: 'volume-2',
    location: { kind: 'comic', volumeId: 'volume-2', pageIndex: 1 }
  }), 30);

  assert.equal(first.clientId, replacement.clientId);
  assert.equal(replacement.userId, 'user-1');
  assert.equal(toProgressPutBody(replacement).schemaVersion, 3);
  assert.deepEqual((await storage.listProgress()).map((item) => item.clientSequence), [2, 3]);
  assert.equal(await storage.compareDeleteProgress(first.mutationId), false);
  assert.equal(await storage.compareDeleteProgress(replacement.mutationId), true);
  assert.deepEqual((await storage.listProgress()).map((item) => item.mutationId), [secondVolume.mutationId]);
});

test('lease is single-owner until expiry and clearAll removes private state', async () => {
  const storage = new MemoryReaderStorage();
  assert.equal(await storage.acquireProgressLease('tab-a', 100, 1_000), true);
  assert.equal(await storage.acquireProgressLease('tab-b', 100, 1_050), false);
  assert.equal(await storage.acquireProgressLease('tab-b', 100, 1_101), true);
  await storage.putPreference('user', 'work', normalizeReaderPreferences(null));
  await storage.enqueueProgress(progress());
  await storage.addDiagnostic({ level: 'warning', code: 'test', message: 'test' });
  await storage.clearAll();
  assert.equal(await storage.getPreference('user', 'work'), null);
  assert.deepEqual(await storage.listProgress(), []);
  assert.deepEqual(await storage.listDiagnostics(), []);
  assert.equal(await storage.getProgressLease(), null);
});

test('coordinator preserves a newer mutation queued while the old mutation is in flight', async () => {
  const storage = new MemoryReaderStorage();
  const sent: ProgressMutation[] = [];
  let releaseFirst: (() => void) | undefined;
  const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
  const transport: ProgressSyncTransport = async (mutation) => {
    sent.push(mutation);
    if (sent.length === 1) await firstGate;
    return { outcome: 'accepted' };
  };
  const coordinator = new ReaderProgressSyncCoordinator(storage, transport, { debounceMs: 60_000 });
  await coordinator.enqueue(progress({ location: { kind: 'comic', volumeId: 'volume-1', pageIndex: 1 } }));
  const flushing = coordinator.flushNow();
  while (sent.length === 0) await new Promise((resolve) => setTimeout(resolve, 0));
  const newer = await coordinator.enqueue(progress({
    location: { kind: 'comic', volumeId: 'volume-1', pageIndex: 9 },
    percent: 50
  }));
  releaseFirst?.();
  await flushing;
  coordinator.stop();

  assert.equal(sent.length, 2);
  assert.equal(sent[1].mutationId, newer.mutationId);
  assert.deepEqual(await storage.listProgress(), []);
});

test('a failed superseded request does not delay its newer replacement', async () => {
  const storage = new MemoryReaderStorage();
  const sent: ProgressMutation[] = [];
  let releaseFirst: (() => void) | undefined;
  const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (mutation) => {
    sent.push(mutation);
    if (sent.length === 1) {
      await firstGate;
      throw new Error('superseded request failed');
    }
    return { outcome: 'accepted' };
  }, { debounceMs: 60_000, retryBaseMs: 60_000 });
  await coordinator.enqueue(progress());
  const flushing = coordinator.flushNow();
  while (sent.length === 0) await new Promise((resolve) => setTimeout(resolve, 0));
  const newer = await coordinator.enqueue(progress({
    location: { kind: 'comic', volumeId: 'volume-1', pageIndex: 10 },
    percent: 60
  }));
  releaseFirst?.();
  await flushing;
  coordinator.stop();
  assert.equal(sent[1].mutationId, newer.mutationId);
  assert.deepEqual(await storage.listProgress(), []);
});

test('retry blocks later sequence, then resumes in order', async () => {
  const storage = new MemoryReaderStorage();
  let now = 1_000;
  const sent: number[] = [];
  let failOnce = true;
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (mutation) => {
    sent.push(mutation.clientSequence);
    if (failOnce) {
      failOnce = false;
      throw new Error('offline');
    }
    return { outcome: 'accepted' };
  }, { debounceMs: 60_000, retryBaseMs: 10, now: () => now });

  await coordinator.enqueue(progress({ volumeId: 'volume-a', location: { kind: 'comic', volumeId: 'volume-a', pageIndex: 1 } }));
  await coordinator.enqueue(progress({ volumeId: 'volume-b', location: { kind: 'comic', volumeId: 'volume-b', pageIndex: 1 } }));
  await coordinator.flushNow();
  assert.deepEqual(sent, [1]);
  assert.equal((await storage.listProgress())[0].retryCount, 1);

  now += 20;
  await coordinator.flushNow();
  coordinator.stop();
  assert.deepEqual(sent, [1, 1, 2]);
  assert.deepEqual(await storage.listProgress(), []);
});

test('fingerprint conflicts are quarantined and do not block later progress', async () => {
  const storage = new MemoryReaderStorage();
  let call = 0;
  const coordinator = new ReaderProgressSyncCoordinator(storage, async () => {
    call += 1;
    return call === 1 ? { outcome: 'fingerprint-conflict' } : { outcome: 'accepted' };
  }, { debounceMs: 60_000 });
  await coordinator.enqueue(progress({ volumeId: 'volume-a', location: { kind: 'comic', volumeId: 'volume-a', pageIndex: 1 } }));
  await coordinator.enqueue(progress({ volumeId: 'volume-b', location: { kind: 'comic', volumeId: 'volume-b', pageIndex: 1 } }));
  await coordinator.flushNow();
  coordinator.stop();
  assert.deepEqual(await storage.listProgress(), []);
  assert.equal((await storage.listQuarantine())[0].reason, 'fingerprint-conflict');
  assert.equal((await storage.listDiagnostics())[0].code, 'fingerprint-conflict');
});

test('coordinator never flushes another user through the active authenticated session', async () => {
  const storage = new MemoryReaderStorage();
  await storage.enqueueProgress(progress({ userId: 'user-a', volumeId: 'volume-a', location: { kind: 'comic', volumeId: 'volume-a', pageIndex: 1 } }));
  await storage.enqueueProgress(progress({ userId: 'user-b', volumeId: 'volume-b', location: { kind: 'comic', volumeId: 'volume-b', pageIndex: 1 } }));
  const sent: string[] = [];
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (mutation) => {
    sent.push(mutation.userId);
    return { outcome: 'accepted' };
  }, { debounceMs: 60_000 });
  coordinator.activateUser('user-b');
  await coordinator.flushNow();
  coordinator.stop();
  assert.deepEqual(sent, ['user-b']);
  assert.deepEqual((await storage.listProgress()).map((item) => item.userId), ['user-a']);
});

test('legacy hooks migrate only explicitly identified state', async () => {
  const storage = new MemoryReaderStorage();
  const repository = new ReaderPreferenceRepository(storage);
  const unsafe = await migrateLegacyPreferenceCandidate({ settings: { theme: 'day' }, sourceKey: 'legacy' }, repository, storage);
  assert.equal(unsafe.status, 'quarantined');

  const safe = await migrateLegacyPreferenceCandidate({
    userId: 'user-1',
    workId: 'work-1',
    settings: { theme: 'warm' }
  }, repository, storage);
  assert.equal(safe.status, 'migrated');
  assert.equal((await repository.resolve('user-1', 'work-1', null)).preferences.appearance.theme, 'warm');

  const enqueued: ProgressMutationInput[] = [];
  const progressResult = await migrateLegacyProgressCandidate({
    userId: 'user-1',
    workId: 'work-1',
    editionId: 'edition-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint',
    readerType: 'ebook',
    progress: { position: 'epubcfi(/6/2)', percent: 12 }
  }, { enqueue: async (input) => {
    enqueued.push(input);
    return storage.enqueueProgress(input);
  } }, storage);
  assert.equal(progressResult.status, 'migrated');
  assert.deepEqual(enqueued[0].location, { kind: 'reflowable', format: 'epub', cfi: 'epubcfi(/6/2)', href: undefined, progression: undefined });

  await migrateLegacyProgressCandidate({
    userId: 'user-1',
    workId: 'work-1',
    editionId: 'edition-2',
    volumeId: 'volume-2',
    contentFingerprint: 'fingerprint-2',
    readerType: 'ebook',
    progress: { percent: 25, extra: { percentage: 25 } }
  }, { enqueue: async (input) => {
    enqueued.push(input);
    return storage.enqueueProgress(input);
  } }, storage);
  assert.deepEqual(enqueued[1].location, { kind: 'reflowable', format: 'epub', cfi: undefined, href: undefined, progression: 0.25 });
});

test('browser migration quarantines unowned cache, migrates exact owner once, and removes legacy keys', async () => {
  const values = new Map<string, string>();
  const localStorage = {
    get length() { return values.size; },
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
    key: (index: number) => [...values.keys()][index] ?? null,
    clear: () => values.clear()
  };
  values.set('shuku:reader:preferences:ebook', JSON.stringify({ theme: 'day' }));
  values.set('shuku:reader:progress:edition-1', JSON.stringify({
    userId: 'user-1',
    workId: 'work-1',
    contentFingerprint: 'fingerprint',
    progress: { readerType: 'ebook', position: 'epubcfi(/6/4)', percent: 25 }
  }));
  const originalWindow = (globalThis as { window?: unknown }).window;
  (globalThis as { window?: unknown }).window = { localStorage, dispatchEvent: () => true };
  const storage = new MemoryReaderStorage();
  try {
    const first = await migrateLegacyBrowserReaderState({
      currentUserId: 'user-1',
      currentWorkId: 'work-1',
      legacyEditionId: 'edition-1',
      volumeId: 'volume-1',
      contentFingerprint: 'fingerprint',
      readerKind: 'reflowable'
    }, { storage, repository: new ReaderPreferenceRepository(storage) });
    assert.deepEqual(first, { status: 'migrated', migrated: 1, quarantined: 1 });
    assert.equal(values.has('shuku:reader:preferences:ebook'), false);
    assert.equal(values.has('shuku:reader:progress:edition-1'), false);
    assert.equal((await storage.listProgress()).length, 1);
    assert.equal((await storage.listDiagnostics())[0].code, 'unsafe-legacy');

    const second = await migrateLegacyBrowserReaderState({
      currentUserId: 'user-1',
      currentWorkId: 'work-1',
      legacyEditionId: 'edition-1',
      volumeId: 'volume-1',
      contentFingerprint: 'fingerprint',
      readerKind: 'reflowable'
    }, { storage });
    assert.deepEqual(second, { status: 'skipped', migrated: 0, quarantined: 0 });
  } finally {
    if (typeof originalWindow === 'undefined') delete (globalThis as { window?: unknown }).window;
    else (globalThis as { window?: unknown }).window = originalWindow;
  }
});
