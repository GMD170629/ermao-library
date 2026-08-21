import { isExactPublicationLocation, parsePublicationLocation, type PublicationLocation } from '@shuku/reader-core';
import { emitReaderDebug } from './debug';
import {
  READER_PROGRESS_DEBOUNCE_MS,
  ReaderProgressConflictError,
  exactProgressKey,
  normalizedPercent,
  progressLocationsMatch,
  syncStateKey,
  type ExactProgressRecord,
  type ExactProgressSaveInput,
  type PendingProgressMutation,
  type ProgressSaveInput,
  type ProgressQueryTransport,
  type ProgressSyncTransport,
  type ProgressUpload,
  type RemoteProgressNotice,
  type ReaderProgressSnapshot
} from './model';
import type { ReaderStorage } from './storage';

type Options = { debounceMs?: number; now?: () => number; exitUploadTimeoutMs?: number; queryTransport?: ProgressQueryTransport };
type Waiter = { resolve: (record: ExactProgressRecord) => void; reject: (reason: unknown) => void };
type SessionProgressState = {
  revision: number;
  clientId: string;
  current: PublicationLocation | null;
  etag: string | null;
  notice: RemoteProgressNotice | null;
};
type NoticeListener = (resourceId: string, notice: RemoteProgressNotice | null) => void;
export const READER_PROGRESS_CHANGED_EVENT = 'shuku:reader-progress-changed';

function id() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : '00000000-0000-4000-8000-'.concat(Math.random().toString(16).slice(2).padEnd(12, '0').slice(0, 12));
}

/** Durable latest-only progress synchronization with explicit revision conflicts. */
export class ReaderProgressSyncCoordinator {
  private readonly debounceMs: number;
  private readonly now: () => number;
  private readonly exitUploadTimeoutMs: number;
  private readonly queryTransport: ProgressQueryTransport | null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pendingInput: ExactProgressSaveInput | null = null;
  private waiters: Waiter[] = [];
  private commitPromise: Promise<ExactProgressRecord | null> | null = null;
  private readonly uploadSlots = new Map<string, PendingProgressMutation>();
  private uploadPromise: Promise<void> | null = null;
  private abort: AbortController | null = null;
  private activeUploadKey: string | null = null;
  private activeUserId: string | null = null;
  private started = false;
  private readonly latest = new Map<string, ReaderProgressSnapshot>();
  private readonly sessions = new Map<string, SessionProgressState>();
  private readonly noticeListeners = new Set<NoticeListener>();

  constructor(private readonly storage: ReaderStorage, private readonly transport: ProgressSyncTransport, options: Options = {}) {
    this.debounceMs = options.debounceMs ?? READER_PROGRESS_DEBOUNCE_MS;
    this.now = options.now ?? Date.now;
    this.exitUploadTimeoutMs = options.exitUploadTimeoutMs ?? 2_500;
    this.queryTransport = options.queryTransport ?? null;
  }

  start() { if (this.started) return; this.started = true; if (typeof window !== 'undefined') { window.addEventListener('online', this.handleOnline); window.addEventListener('pagehide', this.handleExit); document.addEventListener('visibilitychange', this.handleVisibility); } }
  stop() { if (typeof window !== 'undefined' && this.started) { window.removeEventListener('online', this.handleOnline); window.removeEventListener('pagehide', this.handleExit); document.removeEventListener('visibilitychange', this.handleVisibility); } this.started = false; void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs }); }
  activateUser(userId: string) { if (!userId) return; this.activeUserId = userId; void this.storage.listPendingProgress(userId).then((items) => items.forEach((item) => this.queueUpload(item))); }
  deactivateUser() { void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs }); this.activeUserId = null; }

  enqueue(input: ProgressSaveInput) {
    const locator = parsePublicationLocation(input.locator);
    if (!locator || !isExactPublicationLocation(locator)) return Promise.reject(new Error('READER_LOCATOR_NOT_EXACT'));
    if (this.activeUserId && this.activeUserId !== input.userId) return Promise.reject(new Error('Progress owner does not match active user'));
    this.activeUserId = input.userId; this.pendingInput = { ...input, locator }; this.clearTimer();
    this.timer = setTimeout(() => { this.timer = null; void this.commitPending(); }, Math.max(0, this.debounceMs));
    return new Promise<ExactProgressRecord>((resolve, reject) => this.waiters.push({ resolve, reject }));
  }

  async flushNow(options: { timeoutMs?: number } = {}) {
    this.clearTimer(); do { await this.commitPending(); } while (this.pendingInput);
    if (!this.uploadPromise) return;
    if (options.timeoutMs === undefined) return this.uploadPromise;
    await Promise.race([this.uploadPromise, new Promise<void>((resolve) => setTimeout(resolve, options.timeoutMs))]);
  }
  getLatestServerSnapshot(resourceId: string) { return this.latest.get(resourceId) ?? null; }

  subscribeRemoteProgress(listener: NoticeListener) {
    this.noticeListeners.add(listener);
    return () => { this.noticeListeners.delete(listener); };
  }

  beginSession(resourceId: string, clientId: string, snapshot: ReaderProgressSnapshot | null, current: PublicationLocation | null) {
    if (snapshot) this.latest.set(resourceId, snapshot);
    this.sessions.set(resourceId, {
      revision: snapshot?.revision ?? 0,
      clientId,
      current,
      etag: snapshot ? `"reader-progress-${snapshot.revision}"` : '"reader-progress-0"',
      notice: null
    });
    this.emitNotice(resourceId, null);
  }

  endSession(resourceId: string) { this.sessions.delete(resourceId); }

  dismissRemoteProgress(resourceId: string) {
    const session = this.sessions.get(resourceId);
    if (!session) return;
    session.notice = null;
    this.emitNotice(resourceId, null);
  }

  async checkRemoteProgress(resourceId: string) {
    const session = this.sessions.get(resourceId);
    if (!session || !this.queryTransport) return null;
    const controller = new AbortController();
    const result = await this.queryTransport(resourceId, session.etag, controller.signal);
    session.etag = result.etag ?? session.etag;
    if (result.kind === 'unchanged' || !result.snapshot) return session.notice;
    return this.observeRemote(resourceId, result.snapshot);
  }

  async continueStartupWithLocal(pending: PendingProgressMutation, serverRevision: number) {
    const rebased = { ...pending, mutationId: id(), baseRevision: serverRevision, capturedAtEpochMillis: this.now() };
    await this.storage.putPendingProgress(rebased);
    this.queueUpload(rebased);
  }

  async acceptVerifiedRemote(input: {
    serverIdentity: string; userId: string; bookId: string; resourceId: string;
    pendingKey: string; snapshot: ReaderProgressSnapshot;
  }) {
    const clientId = await this.storage.getClientId();
    const identity = { serverIdentity: input.serverIdentity, userId: input.userId, clientId, bookId: input.bookId, resourceId: input.resourceId } as const;
    const exact: ExactProgressRecord = {
      ...identity,
      key: exactProgressKey(identity),
      schemaVersion: 1,
      bookId: input.bookId,
      locator: input.snapshot.locator,
      displayPercent: input.snapshot.displayPercent,
      revision: input.snapshot.revision,
      capturedAtEpochMillis: input.snapshot.capturedAtEpochMillis ?? input.snapshot.receivedAtEpochMillis
    };
    const supersededWaiters = this.pendingInput?.resourceId === input.resourceId ? this.waiters : [];
    if (supersededWaiters.length > 0) {
      this.pendingInput = null;
      this.waiters = [];
      this.clearTimer();
    }
    this.uploadSlots.delete(input.pendingKey);
    if (this.activeUploadKey === input.pendingKey) this.abort?.abort();
    await this.storage.putExactAndDeletePending(exact, input.pendingKey);
    supersededWaiters.forEach(({ resolve }) => resolve(exact));
    const session = this.sessions.get(input.resourceId);
    if (session) {
      session.revision = input.snapshot.revision;
      session.current = input.snapshot.locator;
      session.notice = null;
    }
    this.emitNotice(input.resourceId, null);
    return exact;
  }

  private readonly handleOnline = () => { if (this.activeUserId) void this.storage.listPendingProgress(this.activeUserId).then((items) => items.forEach((item) => this.queueUpload(item))); };
  private readonly handleExit = () => { void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs }); };
  private readonly handleVisibility = () => { if (document.visibilityState === 'hidden') this.handleExit(); else this.handleOnline(); };
  private clearTimer() { if (this.timer) clearTimeout(this.timer); this.timer = null; }

  private commitPending() {
    if (this.commitPromise) return this.commitPromise;
    const input = this.pendingInput; const waiters = this.waiters; this.pendingInput = null; this.waiters = [];
    if (!input) return Promise.resolve(null);
    const capturedAtEpochMillis = this.now();
    this.commitPromise = this.storage.getClientId().then(async (clientId) => {
      const session = this.sessions.get(input.resourceId);
      if (session?.notice && session.current
        && progressLocationsMatch(session.current, input.locator)) {
        const identity = { serverIdentity: input.serverIdentity, userId: input.userId, clientId, bookId: input.bookId, resourceId: input.resourceId } as const;
        const unchanged: ExactProgressRecord = {
          ...identity,
          key: exactProgressKey(identity),
          schemaVersion: 1,
          bookId: input.bookId,
          locator: input.locator,
          displayPercent: normalizedPercent(input.displayPercent),
          revision: session.revision,
          capturedAtEpochMillis
        };
        waiters.forEach(({ resolve }) => resolve(unchanged));
        return unchanged;
      }
      const identity = { serverIdentity: input.serverIdentity, userId: input.userId, clientId, bookId: input.bookId, resourceId: input.resourceId };
      const key = syncStateKey(identity);
      const baseRevision = Math.max(input.baseRevision, session?.revision ?? 0);
      const mutation: PendingProgressMutation = { key, schemaVersion: 1, serverIdentity: input.serverIdentity, userId: input.userId, bookId: input.bookId, resourceId: input.resourceId, clientId, mutationId: id(), baseRevision, capturedAtEpochMillis, locator: input.locator, displayPercent: normalizedPercent(input.displayPercent) };
      const exact: ExactProgressRecord = { ...identity, key: exactProgressKey(identity), schemaVersion: 1, bookId: input.bookId, locator: input.locator, displayPercent: mutation.displayPercent, revision: baseRevision, capturedAtEpochMillis };
      await this.storage.putExactAndPending(exact, mutation);
      if (session) {
        session.current = input.locator;
        if (session.notice) {
          session.notice = null;
          this.emitNotice(input.resourceId, null);
        }
      }
      waiters.forEach(({ resolve }) => resolve(exact));
      if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(READER_PROGRESS_CHANGED_EVENT, { detail: exact }));
      this.queueUpload(mutation);
      return exact;
    }).catch((reason) => { waiters.forEach(({ reject }) => reject(reason)); throw reason; }).finally(() => { this.commitPromise = null; });
    return this.commitPromise;
  }

  private queueUpload(mutation: PendingProgressMutation) { this.uploadSlots.set(mutation.key, mutation); if (this.uploadPromise) return; this.uploadPromise = this.drain().finally(() => { this.uploadPromise = null; if (this.uploadSlots.size) this.uploadPromise = this.drain().finally(() => { this.uploadPromise = null; }); }); }
  private async drain() {
    while (this.uploadSlots.size) {
      const mutation = [...this.uploadSlots.values()].sort((left, right) => left.capturedAtEpochMillis - right.capturedAtEpochMillis)[0];
      if (!mutation) return;
      this.uploadSlots.delete(mutation.key); const controller = new AbortController(); this.abort = controller; this.activeUploadKey = mutation.key;
      const upload: ProgressUpload = { resourceId: mutation.resourceId, request: { schemaVersion: 4, clientId: mutation.clientId, mutationId: mutation.mutationId, baseRevision: mutation.baseRevision, capturedAtEpochMillis: mutation.capturedAtEpochMillis, locator: mutation.locator } };
      try {
        const snapshot = await this.transport(upload, controller.signal); this.latest.set(mutation.resourceId, snapshot);
        const session = this.sessions.get(mutation.resourceId);
        if (session) {
          session.revision = Math.max(session.revision, snapshot.revision);
          session.etag = `"reader-progress-${snapshot.revision}"`;
        }
        await this.storage.deletePendingProgress(mutation.key, mutation.mutationId);
      } catch (reason) {
        if (reason instanceof ReaderProgressConflictError) {
          await this.storage.deletePendingProgress(mutation.key, mutation.mutationId);
          this.latest.set(mutation.resourceId, { schemaVersion: 4, ...reason.conflict });
          this.observeRemote(mutation.resourceId, { schemaVersion: 4, ...reason.conflict }, mutation.locator);
          emitReaderDebug('warning', '阅读进度存在跨设备冲突', { resourceId: mutation.resourceId, revision: reason.conflict.revision });
        } else if (!controller.signal.aborted) emitReaderDebug('warning', '阅读进度已保留，将在联网后重试', { resourceId: mutation.resourceId });
      } finally { if (this.abort === controller) this.abort = null; if (this.activeUploadKey === mutation.key) this.activeUploadKey = null; }
    }
  }

  private observeRemote(resourceId: string, snapshot: ReaderProgressSnapshot, currentOverride?: PublicationLocation) {
    const session = this.sessions.get(resourceId);
    if (!session || snapshot.revision <= session.revision) return session?.notice ?? null;
    session.revision = snapshot.revision;
    session.etag = `"reader-progress-${snapshot.revision}"`;
    this.latest.set(resourceId, snapshot);
    const current = currentOverride ?? session.current;
    if (snapshot.clientId === session.clientId
      || (current && progressLocationsMatch(current, snapshot.locator))) {
      return session.notice;
    }
    session.notice = {
      revision: snapshot.revision,
      sourceClientId: snapshot.clientId,
      locator: snapshot.locator,
      displayPercent: snapshot.displayPercent,
      receivedAtEpochMillis: snapshot.receivedAtEpochMillis,
      ...(snapshot.capturedAtEpochMillis === undefined ? {} : { capturedAtEpochMillis: snapshot.capturedAtEpochMillis })
    };
    this.emitNotice(resourceId, session.notice);
    return session.notice;
  }

  private emitNotice(resourceId: string, notice: RemoteProgressNotice | null) {
    this.noticeListeners.forEach((listener) => listener(resourceId, notice));
  }
}

let current: ReaderProgressSyncCoordinator | null = null;
export function setReaderProgressSyncCoordinator(coordinator: ReaderProgressSyncCoordinator | null) { if (current === coordinator) return; current?.stop(); current = coordinator; current?.start(); }
export function getReaderProgressSyncCoordinator() { return current; }
