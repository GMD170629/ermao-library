import { isExactPublicationLocation, parsePublicationLocation } from '@shuku/reader-core';
import { emitReaderDebug } from './debug';
import {
  READER_PROGRESS_DEBOUNCE_MS,
  ReaderProgressConflictError,
  exactProgressKey,
  normalizedPercent,
  publicationFingerprintKey,
  syncStateKey,
  type ExactProgressRecord,
  type ExactProgressSaveInput,
  type PendingProgressMutation,
  type ProgressSaveInput,
  type ProgressSyncTransport,
  type ProgressUpload,
  type ReaderProgressSnapshot
} from './model';
import type { ReaderStorage } from './storage';

type Options = { debounceMs?: number; now?: () => number; exitUploadTimeoutMs?: number };
type Waiter = { resolve: (record: ExactProgressRecord) => void; reject: (reason: unknown) => void };
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
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pendingInput: ExactProgressSaveInput | null = null;
  private waiters: Waiter[] = [];
  private commitPromise: Promise<ExactProgressRecord | null> | null = null;
  private readonly uploadSlots = new Map<string, PendingProgressMutation>();
  private uploadPromise: Promise<void> | null = null;
  private abort: AbortController | null = null;
  private activeUserId: string | null = null;
  private started = false;
  private readonly latest = new Map<string, ReaderProgressSnapshot>();

  constructor(private readonly storage: ReaderStorage, private readonly transport: ProgressSyncTransport, options: Options = {}) {
    this.debounceMs = options.debounceMs ?? READER_PROGRESS_DEBOUNCE_MS;
    this.now = options.now ?? Date.now;
    this.exitUploadTimeoutMs = options.exitUploadTimeoutMs ?? 2_500;
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
  getLatestServerSnapshot(volumeId: string) { return this.latest.get(volumeId) ?? null; }

  async getConflict(serverIdentity: string, userId: string, volumeId: string) {
    const clientId = await this.storage.getClientId();
    return this.storage.getProgressConflict(syncStateKey({ serverIdentity, userId, clientId, volumeId }));
  }

  /** User chose “continue this device”; no automatic conflict overwrite is allowed. */
  async resolveConflictWithLocal(serverIdentity: string, userId: string, volumeId: string) {
    const conflict = await this.getConflict(serverIdentity, userId, volumeId);
    if (!conflict) return false;
    const mutation: PendingProgressMutation = {
      ...conflict.localMutation,
      mutationId: id(),
      baseRevision: conflict.revision,
      capturedAtEpochMillis: this.now()
    };
    await this.storage.deleteProgressConflict(conflict.key);
    await this.storage.putPendingProgress(mutation);
    this.queueUpload(mutation);
    return true;
  }

  /** User chose the other device after the adapter verified exact-block navigation. */
  async resolveConflictWithRemote(serverIdentity: string, userId: string, volumeId: string) {
    const conflict = await this.getConflict(serverIdentity, userId, volumeId);
    if (!conflict) return null;
    const fingerprint = publicationFingerprintKey(conflict.locator.publication);
    const identity = { serverIdentity, userId, clientId: conflict.clientId, volumeId, publicationFingerprint: fingerprint } as const;
    await this.storage.putExactProgress({
      ...identity,
      key: exactProgressKey(identity),
      schemaVersion: 1,
      workId: conflict.workId,
      locator: conflict.locator,
      displayPercent: conflict.displayPercent,
      revision: conflict.revision,
      capturedAtEpochMillis: conflict.capturedAtEpochMillis ?? conflict.receivedAtEpochMillis
    });
    await this.storage.deletePendingProgress(conflict.key);
    await this.storage.deleteProgressConflict(conflict.key);
    return conflict.locator;
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
      const fingerprint = publicationFingerprintKey(input.locator.publication);
      const identity = { serverIdentity: input.serverIdentity, userId: input.userId, clientId, volumeId: input.volumeId, publicationFingerprint: fingerprint };
      const key = syncStateKey(identity);
      const mutation: PendingProgressMutation = { key, schemaVersion: 1, serverIdentity: input.serverIdentity, userId: input.userId, workId: input.workId, volumeId: input.volumeId, clientId, mutationId: id(), baseRevision: input.baseRevision, capturedAtEpochMillis, locator: input.locator, displayPercent: normalizedPercent(input.displayPercent) };
      const exact: ExactProgressRecord = { ...identity, key: exactProgressKey(identity), schemaVersion: 1, workId: input.workId, locator: input.locator, displayPercent: mutation.displayPercent, revision: input.baseRevision, capturedAtEpochMillis };
      await this.storage.putExactAndPending(exact, mutation);
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
      this.uploadSlots.delete(mutation.key); const controller = new AbortController(); this.abort = controller;
      const upload: ProgressUpload = { volumeId: mutation.volumeId, request: { schemaVersion: 4, clientId: mutation.clientId, mutationId: mutation.mutationId, baseRevision: mutation.baseRevision, capturedAtEpochMillis: mutation.capturedAtEpochMillis, locator: mutation.locator } };
      try {
        const snapshot = await this.transport(upload, controller.signal); this.latest.set(mutation.volumeId, snapshot);
        await this.storage.deletePendingProgress(mutation.key, mutation.mutationId); await this.storage.deleteProgressConflict(mutation.key);
      } catch (reason) {
        if (reason instanceof ReaderProgressConflictError) {
          await this.storage.putProgressConflict({ ...reason.conflict, key: mutation.key, schemaVersion: 1, serverIdentity: mutation.serverIdentity, userId: mutation.userId, workId: mutation.workId, volumeId: mutation.volumeId, clientId: mutation.clientId, localMutation: mutation });
          emitReaderDebug('warning', '阅读进度存在跨设备冲突', { volumeId: mutation.volumeId, revision: reason.conflict.revision });
        } else if (!controller.signal.aborted) emitReaderDebug('warning', '阅读进度已保留，将在联网后重试', { volumeId: mutation.volumeId });
      } finally { if (this.abort === controller) this.abort = null; }
    }
  }
}

let current: ReaderProgressSyncCoordinator | null = null;
export function setReaderProgressSyncCoordinator(coordinator: ReaderProgressSyncCoordinator | null) { if (current === coordinator) return; current?.stop(); current = coordinator; current?.start(); }
export function getReaderProgressSyncCoordinator() { return current; }
