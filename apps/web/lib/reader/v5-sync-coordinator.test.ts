import assert from 'node:assert/strict';
import test from 'node:test';
import { READER_PREFERENCES_VERSION, type ReaderPreferences } from '@shuku/reader-core';
import { ReaderV5ProgressSyncCoordinator } from './v5-sync-coordinator';
import {
  readerV5PendingKey,
  readerV5PreferenceKey,
  readerV5ProgressKey,
  type ReaderV5PreferenceSnapshot,
  type ReaderV5Storage,
  type ReaderV5SyncDiagnostic
} from './v5-storage';
import type {
  ReaderV5PendingMutation,
  ReaderV5ProgressIdentity,
  ReaderV5ProgressRecord,
  ReaderV5ProgressSnapshot,
  ReaderV5ProgressUpload
} from './v5-wire';

class TestV5Storage implements ReaderV5Storage {
  private readonly progress = new Map<string, ReaderV5ProgressRecord>();
  private readonly pending = new Map<string, ReaderV5PendingMutation>();
  private readonly preferences = new Map<string, ReaderV5PreferenceSnapshot>();
  private readonly diagnostics: ReaderV5SyncDiagnostic[] = [];
  private readonly clientId = 'web-test-client';

  async getClientId() { return this.clientId; }
  async getV5Progress(identity: ReaderV5ProgressIdentity) { return this.progress.get(readerV5ProgressKey(identity)) ?? null; }
  async putV5Progress(value: ReaderV5ProgressRecord) { this.progress.set(value.key, value); return value; }
  async putV5ExactAndPending(value: ReaderV5ProgressRecord, mutation: ReaderV5PendingMutation) {
    this.progress.set(value.key, value);
    this.pending.set(mutation.key, mutation);
  }
  async putV5PendingProgress(mutation: ReaderV5PendingMutation) { this.pending.set(mutation.key, mutation); }
  async getV5PendingProgress(key: string) { return this.pending.get(key) ?? null; }
  async getV5PendingProgressForIdentity(identity: ReaderV5ProgressIdentity) {
    const value = this.pending.get(readerV5PendingKey(identity));
    return value && value.serverIdentity === identity.serverIdentity
      && value.userId === identity.userId && value.clientId === identity.clientId
      && value.bookId === identity.bookId && value.resourceId === identity.resourceId ? value : null;
  }
  async listV5PendingProgress(userId: string) {
    return [...this.pending.values()].filter((value) => value.userId === userId);
  }
  async deleteV5PendingProgress(key: string, mutationId?: string) {
    const current = this.pending.get(key);
    if (!mutationId || current?.mutationId === mutationId) this.pending.delete(key);
  }
  async putV5ExactAndDeletePending(value: ReaderV5ProgressRecord, key: string, mutationId: string) {
    const current = this.pending.get(key);
    if (!current || current.mutationId !== mutationId) return false;
    this.progress.set(value.key, value);
    this.pending.delete(key);
    return true;
  }
  async getPreference(userId: string, bookId: string) { return this.preferences.get(readerV5PreferenceKey(userId, bookId)) ?? null; }
  async putPreference(userId: string, bookId: string, preferences: ReaderPreferences, updatedAt = Date.now()) {
    const value: ReaderV5PreferenceSnapshot = {
      key: readerV5PreferenceKey(userId, bookId), userId, bookId,
      schemaVersion: READER_PREFERENCES_VERSION, preferences, updatedAt
    };
    this.preferences.set(value.key, value);
    return value;
  }
  async deletePreference(userId: string, bookId: string) { this.preferences.delete(readerV5PreferenceKey(userId, bookId)); }
  async addDiagnostic(diagnostic: Omit<ReaderV5SyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) {
    const value: ReaderV5SyncDiagnostic = { ...diagnostic, id: `diagnostic-${this.diagnostics.length + 1}`, createdAt: now };
    this.diagnostics.push(value);
    return value;
  }
  async listDiagnostics(limit = 100) { return this.diagnostics.slice(-limit).reverse(); }
  async clearAll() {
    this.progress.clear(); this.pending.clear(); this.preferences.clear(); this.diagnostics.splice(0);
  }
}

const position = {
  locator: { href: 'chapter.xhtml', locations: { progression: 0.25 } },
  presentation: {
    displayPercent: 25,
    totalProgression: 0.25,
    currentHref: 'chapter.xhtml',
    chapter: { navigationKey: null, href: 'chapter.xhtml', title: 'Chapter', index: 0 },
    page: null,
    playback: null
  }
} as const;

const identity = {
  serverIdentity: 'https://library.example',
  userId: 'user-1',
  bookId: 'book-1',
  resourceId: 'resource-1'
} as const;

function snapshot(upload: ReaderV5ProgressUpload, revision: number, mutationId = upload.request.mutationId): ReaderV5ProgressSnapshot {
  return {
    schemaVersion: 5,
    revision,
    clientId: upload.request.clientId,
    mutationId,
    capturedAtEpochMillis: upload.request.capturedAtEpochMillis,
    receivedAtEpochMillis: 100,
    position: upload.request.position
  };
}

test('v5 coalesces latest full position and sends no baseRevision', async () => {
  const storage = new TestV5Storage();
  const sent: ReaderV5ProgressUpload[] = [];
  const coordinator = new ReaderV5ProgressSyncCoordinator(storage, async (upload) => {
    sent.push(upload);
    return { acceptedMutationId: upload.request.mutationId, acceptedRevision: 1, currentSnapshot: snapshot(upload, 1) };
  }, { debounceMs: 0, now: () => 99 });
  const nextPosition = { ...position, presentation: { ...position.presentation, displayPercent: 99, totalProgression: 0.99 } };
  const first = coordinator.enqueue({ ...identity, position });
  const second = coordinator.enqueue({ ...identity, position: nextPosition });
  await coordinator.flushNow();
  await Promise.all([first, second]);
  assert.equal(sent.length, 1);
  assert.equal('baseRevision' in sent[0].request, false);
  assert.equal(sent[0].request.position.presentation.displayPercent, 99);
  assert.equal(await storage.getV5PendingProgressForIdentity({ ...identity, clientId: await storage.getClientId() }), null);
});

test('immediate save commits exact position and outbox before a held network acknowledgment', async () => {
  const storage = new TestV5Storage();
  let releaseUpload: () => void = () => { throw new Error('upload gate was not initialized'); };
  const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve; });
  const coordinator = new ReaderV5ProgressSyncCoordinator(storage, async (upload) => {
    await uploadGate;
    return { acceptedMutationId: upload.request.mutationId, acceptedRevision: 1, currentSnapshot: snapshot(upload, 1) };
  }, { debounceMs: 10_000, now: () => 123 });
  try {
    const exact = await coordinator.saveNow({ ...identity, position });
    assert.equal(exact.capturedAtEpochMillis, 123);
    assert.deepEqual(exact.position, position);
    assert.deepEqual((await storage.getV5Progress(exact))?.position, position);
    assert.deepEqual((await storage.getV5PendingProgressForIdentity(exact))?.position, position);
    assert.equal(exact.revision, 0, 'local durability must not claim an unreceived server ACK');
  } finally {
    releaseUpload();
    await coordinator.flushNow();
  }
});

test('immediate save reports local transaction failure and never uploads it', async () => {
  const failure = new Error('fixture local transaction unavailable');
  class FailingStorage extends TestV5Storage {
    override async putV5ExactAndPending(): Promise<void> { throw failure; }
  }
  let uploads = 0;
  const coordinator = new ReaderV5ProgressSyncCoordinator(new FailingStorage(), async (upload) => {
    uploads += 1;
    return { acceptedMutationId: upload.request.mutationId, acceptedRevision: 1, currentSnapshot: snapshot(upload, 1) };
  });
  await assert.rejects(coordinator.saveNow({ ...identity, position }), (reason) => reason === failure);
  assert.equal(uploads, 0);
});

test('an old or out-of-order ack cannot clear a newer pending mutation', async () => {
  const storage = new TestV5Storage();
  let call = 0;
  const sent: ReaderV5ProgressUpload[] = [];
  const coordinator = new ReaderV5ProgressSyncCoordinator(storage, async (upload) => {
    call += 1;
    sent.push(upload);
    return {
      acceptedMutationId: call === 1 ? '11111111-1111-4111-8111-111111111111' : upload.request.mutationId,
      acceptedRevision: call,
      currentSnapshot: snapshot(upload, call, call === 1 ? '11111111-1111-4111-8111-111111111111' : upload.request.mutationId)
    };
  }, { debounceMs: 0 });
  const first = coordinator.enqueue({ ...identity, position });
  await coordinator.flushNow();
  await first;
  const clientId = await storage.getClientId();
  const pendingAfterMismatch = await storage.getV5PendingProgressForIdentity({ ...identity, clientId });
  assert.ok(pendingAfterMismatch);
  const pendingBody = pendingAfterMismatch.position;
  coordinator.activateUser(identity.userId);
  await coordinator.flushNow();
  assert.equal(sent[0].request.mutationId, sent[1].request.mutationId);
  assert.deepEqual(sent[0].request.position, pendingBody);
  assert.equal(await storage.getV5PendingProgress(readerV5PendingKey({ ...identity, clientId })), null);
  assert.equal((await storage.getV5Progress({ ...identity, clientId }))?.key, readerV5ProgressKey({ ...identity, clientId }));
});

test('an idempotent replay keeps the local position when the server snapshot is from another device', async () => {
  const storage = new TestV5Storage();
  const localPosition = { ...position, presentation: { ...position.presentation, displayPercent: 99, totalProgression: 0.99 } };
  const remotePosition = { ...position, presentation: { ...position.presentation, displayPercent: 10, totalProgression: 0.1 } };
  const otherMutationId = '22222222-2222-4222-8222-222222222222';
  const coordinator = new ReaderV5ProgressSyncCoordinator(storage, async (upload) => ({
    acceptedMutationId: upload.request.mutationId,
    acceptedRevision: 7,
    currentSnapshot: {
      ...snapshot(upload, 7, otherMutationId),
      position: remotePosition
    }
  }), { debounceMs: 0 });

  await coordinator.enqueue({ ...identity, position: localPosition });
  await coordinator.flushNow();
  const clientId = await storage.getClientId();
  const stored = await storage.getV5Progress({ ...identity, clientId });
  assert.equal(stored?.position.presentation.displayPercent, 99);
  assert.notEqual(stored?.mutationId, otherMutationId);
  assert.equal(await storage.getV5PendingProgressForIdentity({ ...identity, clientId }), null);
  assert.equal(coordinator.getLatestServerSnapshot(identity.resourceId)?.position.presentation.displayPercent, 10);
});

for (const saveMode of ['enqueue', 'saveNow'] as const) {
  test(`a ${saveMode} during the atomic local commit is serialized and eventually uploaded`, async () => {
    class SlowStorage extends TestV5Storage {
      private readonly commitGate: Promise<void>;
      private releaseCommit: (() => void) | null = null;
      private markStarted: (() => void) | null = null;
      readonly commitStarted: Promise<void>;
      constructor() {
        super();
        this.commitGate = new Promise<void>((resolve) => { this.releaseCommit = resolve; });
        this.commitStarted = new Promise<void>((resolve) => { this.markStarted = resolve; });
      }
      async putV5ExactAndPending(...args: Parameters<TestV5Storage['putV5ExactAndPending']>) {
        this.markStarted?.();
        this.markStarted = null;
        await this.commitGate;
        return super.putV5ExactAndPending(...args);
      }
      release() {
        this.releaseCommit?.();
        this.releaseCommit = null;
      }
    }

    const storage = new SlowStorage();
    const sent: ReaderV5ProgressUpload[] = [];
    const coordinator = new ReaderV5ProgressSyncCoordinator(storage, async (upload) => {
      sent.push(upload);
      return { acceptedMutationId: upload.request.mutationId, acceptedRevision: sent.length, currentSnapshot: snapshot(upload, sent.length) };
    }, { debounceMs: 0 });
    const first = coordinator.enqueue({ ...identity, position });
    await storage.commitStarted;
    const secondPosition = { ...position, presentation: { ...position.presentation, displayPercent: 99, totalProgression: 0.99 } };
    const second = coordinator[saveMode]({ ...identity, position: secondPosition });
    const flushed = coordinator.flushNow();
    storage.release();
    await flushed;
    await Promise.all([first, second]);

    assert.equal(sent.length, 2);
    assert.equal(sent[1]?.request.position.presentation.displayPercent, 99);
    const clientId = await storage.getClientId();
    assert.equal(await storage.getV5PendingProgressForIdentity({ ...identity, clientId }), null);
  });
}

const startupSnapshot: ReaderV5ProgressSnapshot = {
  schemaVersion: 5, revision: 1, clientId: 'web-test-client',
  mutationId: '11111111-1111-4111-8111-111111111111',
  capturedAtEpochMillis: 1, receivedAtEpochMillis: 2, position
};
const startupInput = () => ({
  identity, directPosition: null, serverSnapshot: startupSnapshot,
  signal: new AbortController().signal
});

test('startup queries after an ACK clears pending and keeps the complete fresh locator', async () => {
  let allowRead = () => {};
  let readStarted = () => {};
  const readGate = new Promise<void>((resolve) => { allowRead = resolve; });
  const started = new Promise<void>((resolve) => { readStarted = resolve; });
  class GatedStorage extends TestV5Storage {
    override async getV5PendingProgressForIdentity(value: ReaderV5ProgressIdentity) {
      readStarted();
      await readGate;
      return super.getV5PendingProgressForIdentity(value);
    }
  }
  let allowAck = () => {};
  const ackGate = new Promise<void>((resolve) => { allowAck = resolve; });
  let server = startupSnapshot;
  const storage = new GatedStorage();
  const opaquePosition = {
    ...position,
    locator: { href: 'future.bin', type: 'application/x-future', locations: { progression: 0.75, futureAnchor: { offset: 73 } } },
    presentation: { ...position.presentation, displayPercent: 75, totalProgression: 0.75 }
  };
  const coordinator = new ReaderV5ProgressSyncCoordinator(storage, async (upload) => {
    await ackGate;
    server = snapshot(upload, 2);
    return { acceptedMutationId: upload.request.mutationId, acceptedRevision: 2, currentSnapshot: server };
  }, { queryTransport: async (resourceId, etag) => {
    assert.equal(resourceId, identity.resourceId);
    assert.equal(etag, '"reader-v5-progress-1"');
    assert.equal(await storage.getV5PendingProgressForIdentity({ ...identity, clientId: await storage.getClientId() }), null);
    return { kind: 'current', snapshot: server, etag: '"reader-v5-progress-2"' };
  } });
  try {
    await coordinator.saveNow({ ...identity, position: opaquePosition });
    const resumed = coordinator.resolveStartupProgress(startupInput());
    await started;
    allowAck();
    await coordinator.flushNow();
    allowRead();
    const decision = await resumed;
    assert.equal(decision.source, 'server');
    assert.deepEqual(decision.position, opaquePosition);
    assert.equal(decision.serverSnapshot, server);
  } finally { allowAck(); allowRead(); await coordinator.flushNow(); }
});

test('startup uses a pending position without waiting for its held upload or querying', async () => {
  let allowAck = () => {};
  const ackGate = new Promise<void>((resolve) => { allowAck = resolve; });
  const storage = new TestV5Storage();
  const coordinator = new ReaderV5ProgressSyncCoordinator(storage, async (upload) => {
    await ackGate;
    return { acceptedMutationId: upload.request.mutationId, acceptedRevision: 2, currentSnapshot: snapshot(upload, 2) };
  }, { queryTransport: async () => { throw new Error('pending must not query'); } });
  try {
    const exact = await coordinator.saveNow({ ...identity, position });
    const decision = await coordinator.resolveStartupProgress(startupInput());
    assert.equal(decision.source, 'local-pending');
    assert.deepEqual(decision.position, exact.position);
    assert.equal(decision.serverSnapshot, startupSnapshot);
    assert.ok(await storage.getV5PendingProgressForIdentity(exact));
  } finally { allowAck(); await coordinator.flushNow(); }
});

for (const response of ['null', 'unchanged'] as const) {
  test(`startup respects a ${response} server response without consulting local exact`, async () => {
    class NoExactStorage extends TestV5Storage {
      override async getV5Progress(): Promise<ReaderV5ProgressRecord | null> { throw new Error('startup must not read local exact'); }
    }
    const coordinator = new ReaderV5ProgressSyncCoordinator(new NoExactStorage(), async () => { throw new Error('must not upload'); }, {
      queryTransport: async () => response === 'null'
        ? { kind: 'current', snapshot: null, etag: '"reader-v5-progress-0"' }
        : { kind: 'unchanged', etag: '"reader-v5-progress-1"' }
    });
    const decision = await coordinator.resolveStartupProgress(startupInput());
    assert.equal(decision.source, response === 'null' ? 'start' : 'server');
    assert.equal(decision.position, response === 'null' ? null : position);
    assert.equal(decision.serverSnapshot, response === 'null' ? null : startupSnapshot);
  });
}

test('startup explicit chapter/page target outranks pending and server without storage or query', async () => {
  class UnavailableStorage extends TestV5Storage {
    override async getClientId(): Promise<string> { throw new Error('direct target needs no storage'); }
  }
  const coordinator = new ReaderV5ProgressSyncCoordinator(new UnavailableStorage(), async () => { throw new Error('must not upload'); });
  for (const directPosition of [null, position]) {
    const decision = await coordinator.resolveStartupProgress({ ...startupInput(), hasDirectTarget: true, directPosition });
    assert.equal(decision.source, 'direct-target');
    assert.equal(decision.position, directPosition);
  }
});

for (const stage of ['storage', 'query', 'missing-query'] as const) {
  test(`startup propagates ${stage} failure instead of restoring an old snapshot`, async () => {
    const failure = new Error(`startup ${stage} failed`);
    class FailingStorage extends TestV5Storage {
      override async getV5PendingProgressForIdentity(value: ReaderV5ProgressIdentity) {
        if (stage === 'storage') throw failure;
        return super.getV5PendingProgressForIdentity(value);
      }
    }
    const coordinator = new ReaderV5ProgressSyncCoordinator(new FailingStorage(), async () => { throw new Error('must not upload'); }, stage === 'missing-query' ? {} : {
      queryTransport: async () => { throw failure; }
    });
    await assert.rejects(coordinator.resolveStartupProgress(startupInput()), stage === 'missing-query'
      ? /READER_PROGRESS_QUERY_UNAVAILABLE/
      : (reason: unknown) => reason === failure);
  });
}

for (const stage of ['before', 'storage', 'query'] as const) {
  test(`startup rejects cancellation ${stage} without applying a late result`, async () => {
    const controller = new AbortController();
    const reason = new Error('startup canceled');
    if (stage === 'before') controller.abort(reason);
    class CancelingStorage extends TestV5Storage {
      override async getV5PendingProgressForIdentity(value: ReaderV5ProgressIdentity) {
        if (stage === 'storage') controller.abort(reason);
        return super.getV5PendingProgressForIdentity(value);
      }
    }
    let queried = false;
    const coordinator = new ReaderV5ProgressSyncCoordinator(new CancelingStorage(), async () => { throw new Error('must not upload'); }, {
      queryTransport: async (_resourceId, _etag, signal) => {
        queried = true;
        assert.equal(signal, controller.signal);
        controller.abort(reason);
        return { kind: 'current', snapshot: null, etag: null };
      }
    });
    await assert.rejects(coordinator.resolveStartupProgress({ ...startupInput(), signal: controller.signal }), (error) => error === reason);
    assert.equal(queried, stage === 'query');
  });
}
