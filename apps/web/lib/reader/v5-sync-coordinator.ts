import { emitReaderDebug } from './debug';
import { readerV5PendingKey, readerV5ProgressKey } from './v5-storage';
import {
  parseReaderV5PositionReport,
  positionReportsEqual,
  READER_V5_SCHEMA_VERSION,
  type ReaderV5PendingMutation,
  type ReaderV5ProgressIdentity,
  type ReaderV5ProgressPut,
  type ReaderV5ProgressRecord,
  type ReaderV5ProgressSaveInput,
  type ReaderV5ProgressSnapshot,
  type ReaderV5ProgressUpload,
  type ReaderV5ProgressWriteResult,
  type ReaderV5RemoteProgressNotice
} from './v5-wire';
import type { ReaderV5Storage } from './v5-storage';

type Options = {
  debounceMs?: number;
  now?: () => number;
  exitUploadTimeoutMs?: number;
  queryTransport?: ReaderV5ProgressQueryTransport;
};

type Waiter = {
  resolve: (record: ReaderV5ProgressRecord) => void;
  reject: (reason: unknown) => void;
};

type SessionProgressState = {
  revision: number;
  clientId: string;
  current: import('@shuku/reader-core').ReaderPositionReport | null;
  etag: string | null;
  notice: ReaderV5RemoteProgressNotice | null;
};

export type ReaderV5ProgressWriteTransport = (
  upload: ReaderV5ProgressUpload,
  signal: AbortSignal
) => Promise<ReaderV5ProgressWriteResult>;

export type ReaderV5ProgressQueryResult =
  | Readonly<{ kind: 'unchanged'; etag: string | null }>
  | Readonly<{ kind: 'current'; snapshot: ReaderV5ProgressSnapshot | null; etag: string | null }>;

export type ReaderV5ProgressQueryTransport = (
  resourceId: string,
  etag: string | null,
  signal: AbortSignal
) => Promise<ReaderV5ProgressQueryResult>;

type NoticeListener = (resourceId: string, notice: ReaderV5RemoteProgressNotice | null) => void;

export const READER_V5_PROGRESS_CHANGED_EVENT = 'shuku:reader-v5-progress-changed';
export const READER_V5_PROGRESS_DEBOUNCE_MS = 500;

function mutationId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return '00000000-0000-4000-8000-'.concat(Math.random().toString(16).slice(2).padEnd(12, '0').slice(0, 12));
}

function asIdentity(input: ReaderV5ProgressSaveInput, clientId: string): ReaderV5ProgressIdentity {
  return {
    serverIdentity: input.serverIdentity,
    userId: input.userId,
    clientId,
    bookId: input.bookId,
    resourceId: input.resourceId
  };
}

/**
 * v5 owns one latest position per resource. Locator bytes are never decoded
 * here; adapters produce the report and this coordinator persists it intact.
 */
export class ReaderV5ProgressSyncCoordinator {
  private readonly debounceMs: number;
  private readonly now: () => number;
  private readonly exitUploadTimeoutMs: number;
  private readonly queryTransport: ReaderV5ProgressQueryTransport | null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pendingInput: ReaderV5ProgressSaveInput | null = null;
  private waiters: Waiter[] = [];
  private commitPromise: Promise<ReaderV5ProgressRecord | null> | null = null;
  private readonly uploadSlots = new Map<string, ReaderV5PendingMutation>();
  private uploadPromise: Promise<void> | null = null;
  private abort: AbortController | null = null;
  private activeUploadKey: string | null = null;
  private activeUserId: string | null = null;
  private started = false;
  private readonly latest = new Map<string, ReaderV5ProgressSnapshot>();
  private readonly sessions = new Map<string, SessionProgressState>();
  private readonly noticeListeners = new Set<NoticeListener>();

  constructor(
    private readonly storage: ReaderV5Storage,
    private readonly transport: ReaderV5ProgressWriteTransport,
    options: Options = {}
  ) {
    this.debounceMs = options.debounceMs ?? READER_V5_PROGRESS_DEBOUNCE_MS;
    this.now = options.now ?? Date.now;
    this.exitUploadTimeoutMs = options.exitUploadTimeoutMs ?? 2_500;
    this.queryTransport = options.queryTransport ?? null;
  }

  start() {
    if (this.started) return;
    this.started = true;
    if (typeof window !== 'undefined') {
      window.addEventListener('online', this.handleOnline);
      window.addEventListener('pagehide', this.handleExit);
      document.addEventListener('visibilitychange', this.handleVisibility);
    }
  }

  stop() {
    if (typeof window !== 'undefined' && this.started) {
      window.removeEventListener('online', this.handleOnline);
      window.removeEventListener('pagehide', this.handleExit);
      document.removeEventListener('visibilitychange', this.handleVisibility);
    }
    this.started = false;
    void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs });
  }

  activateUser(userId: string) {
    if (!userId) return;
    this.activeUserId = userId;
    void this.storage.listV5PendingProgress(userId).then((items) => {
      items.forEach((item) => this.queueUpload(item));
    });
  }

  deactivateUser() {
    void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs });
    this.activeUserId = null;
  }

  enqueue(input: ReaderV5ProgressSaveInput) {
    if (this.activeUserId && this.activeUserId !== input.userId) {
      return Promise.reject(new Error('Progress owner does not match active user'));
    }
    const position = parseReaderV5PositionReport(input.position);
    if (!position) return Promise.reject(new Error('READER_POSITION_INVALID'));
    this.activeUserId = input.userId;
    this.pendingInput = { ...input, position };
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.commitPending();
    }, Math.max(0, this.debounceMs));
    return new Promise<ReaderV5ProgressRecord>((resolve, reject) => this.waiters.push({ resolve, reject }));
  }

  async flushNow(options: { timeoutMs?: number } = {}) {
    this.clearTimer();
    do {
      await this.commitPending();
    } while (this.pendingInput);
    if (!this.uploadPromise) return;
    if (options.timeoutMs === undefined) return this.uploadPromise;
    await Promise.race([
      this.uploadPromise,
      new Promise<void>((resolve) => setTimeout(resolve, options.timeoutMs))
    ]);
  }

  getLatestServerSnapshot(resourceId: string) {
    return this.latest.get(resourceId) ?? null;
  }

  subscribeRemoteProgress(listener: NoticeListener) {
    this.noticeListeners.add(listener);
    return () => this.noticeListeners.delete(listener);
  }

  beginSession(
    resourceId: string,
    clientId: string,
    snapshot: ReaderV5ProgressSnapshot | null,
    current: import('@shuku/reader-core').ReaderPositionReport | null
  ) {
    const known = this.latest.get(resourceId) ?? null;
    const baseline = known && (!snapshot || known.revision > snapshot.revision) ? known : snapshot;
    if (baseline) this.latest.set(resourceId, baseline);
    this.sessions.set(resourceId, {
      revision: baseline?.revision ?? 0,
      clientId,
      current,
      etag: baseline ? `"reader-v5-progress-${baseline.revision}"` : '"reader-v5-progress-0"',
      notice: null
    });
    this.emitNotice(resourceId, null);
  }

  endSession(resourceId: string) {
    this.sessions.delete(resourceId);
  }

  dismissRemoteProgress(resourceId: string) {
    const session = this.sessions.get(resourceId);
    if (!session) return;
    session.notice = null;
    this.emitNotice(resourceId, null);
  }

  async acceptRemoteProgress(
    identity: Omit<ReaderV5ProgressIdentity, 'clientId'>,
    notice: ReaderV5RemoteProgressNotice
  ) {
    const session = this.sessions.get(identity.resourceId);
    if (!session) return false;
    const exactIdentity: ReaderV5ProgressIdentity = { ...identity, clientId: session.clientId };
    const exact: ReaderV5ProgressRecord = {
      ...exactIdentity,
      key: readerV5ProgressKey(exactIdentity),
      schemaVersion: READER_V5_SCHEMA_VERSION,
      mutationId: notice.mutationId,
      revision: notice.revision,
      capturedAtEpochMillis: notice.capturedAtEpochMillis,
      position: notice.position
    };
    await this.storage.putV5Progress(exact);
    session.current = notice.position;
    session.revision = Math.max(session.revision, notice.revision);
    session.notice = null;
    this.emitNotice(identity.resourceId, null);
    return true;
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

  private readonly handleOnline = () => {
    if (this.activeUserId) {
      void this.storage.listV5PendingProgress(this.activeUserId).then((items) => {
        items.forEach((item) => this.queueUpload(item));
      });
    }
  };

  private readonly handleExit = () => { void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs }); };

  private readonly handleVisibility = () => {
    if (document.visibilityState === 'hidden') this.handleExit();
    else this.handleOnline();
  };

  private clearTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private commitPending(): Promise<ReaderV5ProgressRecord | null> {
    // A new enqueue may arrive while the previous atomic transaction is still
    // running. Chain behind it so the later input is not stranded in memory.
    if (this.commitPromise) {
      return this.commitPromise.then(
        () => this.commitPending(),
        () => this.commitPending()
      );
    }
    const input = this.pendingInput;
    const waiters = this.waiters;
    this.pendingInput = null;
    this.waiters = [];
    if (!input) return Promise.resolve(null);
    const capturedAtEpochMillis = this.now();
    this.commitPromise = this.storage.getClientId().then(async (clientId) => {
      const identity = asIdentity(input, clientId);
      const mutationIdValue = mutationId();
      const key = readerV5PendingKey(identity);
      const mutation: ReaderV5PendingMutation = {
        ...identity,
        key,
        schemaVersion: READER_V5_SCHEMA_VERSION,
        mutationId: mutationIdValue,
        capturedAtEpochMillis,
        position: input.position
      };
      const session = this.sessions.get(input.resourceId);
      const exact: ReaderV5ProgressRecord = {
        ...identity,
        key: readerV5ProgressKey(identity),
        schemaVersion: READER_V5_SCHEMA_VERSION,
        mutationId: mutationIdValue,
        revision: session?.revision ?? 0,
        capturedAtEpochMillis,
        position: input.position
      };
      await this.storage.putV5ExactAndPending(exact, mutation);
      if (session) {
        session.current = input.position;
        if (session.notice) {
          session.notice = null;
          this.emitNotice(input.resourceId, null);
        }
      }
      waiters.forEach(({ resolve }) => resolve(exact));
      if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(READER_V5_PROGRESS_CHANGED_EVENT, { detail: exact }));
      this.queueUpload(mutation);
      return exact;
    }).catch((reason) => {
      waiters.forEach(({ reject }) => reject(reason));
      throw reason;
    }).finally(() => {
      this.commitPromise = null;
    });
    return this.commitPromise;
  }

  private queueUpload(mutation: ReaderV5PendingMutation) {
    this.uploadSlots.set(mutation.key, mutation);
    if (this.uploadPromise) return;
    this.uploadPromise = this.drain().finally(() => {
      this.uploadPromise = null;
      if (this.uploadSlots.size) this.queueUploadDrain();
    });
  }

  private queueUploadDrain() {
    if (this.uploadPromise) return;
    this.uploadPromise = this.drain().finally(() => {
      this.uploadPromise = null;
      if (this.uploadSlots.size) this.queueUploadDrain();
    });
  }

  private async drain() {
    while (this.uploadSlots.size) {
      const mutation = [...this.uploadSlots.values()].sort(
        (left, right) => left.capturedAtEpochMillis - right.capturedAtEpochMillis
      )[0];
      if (!mutation) return;
      this.uploadSlots.delete(mutation.key);
      const controller = new AbortController();
      this.abort = controller;
      this.activeUploadKey = mutation.key;
      const request: ReaderV5ProgressPut = {
        schemaVersion: READER_V5_SCHEMA_VERSION,
        clientId: mutation.clientId,
        mutationId: mutation.mutationId,
        capturedAtEpochMillis: mutation.capturedAtEpochMillis,
        position: mutation.position
      };
      try {
        const result = await this.transport({ resourceId: mutation.resourceId, request }, controller.signal);
        this.latest.set(mutation.resourceId, result.currentSnapshot);
        const session = this.sessions.get(mutation.resourceId);
        if (session) {
          session.revision = Math.max(session.revision, result.acceptedRevision, result.currentSnapshot.revision);
          session.etag = `"reader-v5-progress-${session.revision}"`;
        }
        // `currentSnapshot` is the server's LWW view and may belong to another
        // device when this request is an idempotent replay. It is retained in
        // `latest` for the next session, but never replaces this device's
        // locally captured position.
        const exact: ReaderV5ProgressRecord = {
          serverIdentity: mutation.serverIdentity,
          userId: mutation.userId,
          clientId: mutation.clientId,
          bookId: mutation.bookId,
          resourceId: mutation.resourceId,
          key: readerV5ProgressKey(mutation),
          schemaVersion: READER_V5_SCHEMA_VERSION,
          mutationId: mutation.mutationId,
          revision: result.acceptedRevision,
          capturedAtEpochMillis: mutation.capturedAtEpochMillis,
          position: mutation.position
        };
        const cleared = result.acceptedMutationId === mutation.mutationId
          ? await this.storage.putV5ExactAndDeletePending(exact, mutation.key, mutation.mutationId)
          : false;
        if (!cleared) {
          // A newer local mutation may already occupy the key. Its body/id stay
          // durable and will be retried; an older ack may never clear it.
          emitReaderDebug('warning', 'Reader v5 确认未匹配本机待上传变更', {
            resourceId: mutation.resourceId,
            mutationId: mutation.mutationId,
            acceptedMutationId: result.acceptedMutationId
          });
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          emitReaderDebug('warning', '阅读进度已保留，将在联网后重试', { resourceId: mutation.resourceId });
          // Keep the durable pending record. It is reloaded by activateUser or
          // the next online event with the same mutation id and body.
        }
      } finally {
        if (this.abort === controller) this.abort = null;
        if (this.activeUploadKey === mutation.key) this.activeUploadKey = null;
      }
    }
  }

  private observeRemote(resourceId: string, snapshot: ReaderV5ProgressSnapshot) {
    const session = this.sessions.get(resourceId);
    if (!session || snapshot.revision <= session.revision) return session?.notice ?? null;
    session.revision = snapshot.revision;
    session.etag = `"reader-v5-progress-${snapshot.revision}"`;
    this.latest.set(resourceId, snapshot);
    if (snapshot.clientId === session.clientId || positionReportsEqual(session.current, snapshot.position)) {
      return session.notice;
    }
    session.notice = {
      revision: snapshot.revision,
      sourceClientId: snapshot.clientId,
      mutationId: snapshot.mutationId,
      position: snapshot.position,
      receivedAtEpochMillis: snapshot.receivedAtEpochMillis,
      capturedAtEpochMillis: snapshot.capturedAtEpochMillis
    };
    this.emitNotice(resourceId, session.notice);
    return session.notice;
  }

  private emitNotice(resourceId: string, notice: ReaderV5RemoteProgressNotice | null) {
    this.noticeListeners.forEach((listener) => listener(resourceId, notice));
  }
}

let current: ReaderV5ProgressSyncCoordinator | null = null;

export function setReaderV5ProgressSyncCoordinator(coordinator: ReaderV5ProgressSyncCoordinator | null) {
  if (current === coordinator) return;
  current?.stop();
  current = coordinator;
  current?.start();
}

export function getReaderV5ProgressSyncCoordinator() {
  return current;
}
