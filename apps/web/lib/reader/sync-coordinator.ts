import { emitReaderDebug } from './debug';
import {
  READER_PROGRESS_DEBOUNCE_MS,
  exactProgressKey,
  normalizedPercent,
  type ExactProgressRecord,
  type ProgressSaveInput,
  type ProgressSyncTransport,
  type ProgressUpload,
  type ReaderProgressSnapshot
} from './model';
import { toV4WireLocation } from './progress-wire';
import type { ReaderStorage } from './storage';

type ReaderProgressSyncCoordinatorOptions = {
  debounceMs?: number;
  now?: () => number;
  exitUploadTimeoutMs?: number;
};

type PendingWaiter = {
  resolve: (record: ExactProgressRecord) => void;
  reject: (reason: unknown) => void;
};

export const READER_PROGRESS_CHANGED_EVENT = 'shuku:reader-progress-changed';

/**
 * One trailing local save plus a best-effort in-memory uploader.
 *
 * There is deliberately no outbox, lease, retry policy, quarantine, sequence
 * counter, or cross-tab ownership. While one request is in flight, new stable
 * progress replaces a single memory slot and only that latest snapshot is sent
 * after the request completes. A failed request is discarded.
 */
export class ReaderProgressSyncCoordinator {
  private readonly debounceMs: number;
  private readonly now: () => number;
  private readonly exitUploadTimeoutMs: number;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pendingInput: ProgressSaveInput | null = null;
  private pendingWaiters: PendingWaiter[] = [];
  private commitPromise: Promise<ExactProgressRecord | null> | null = null;
  private uploadSlot: ProgressUpload | null = null;
  private uploadPromise: Promise<void> | null = null;
  private activeAbortController: AbortController | null = null;
  private readonly latestServerSnapshots = new Map<string, ReaderProgressSnapshot>();
  private started = false;
  private activeUserId: string | null = null;

  constructor(
    private readonly storage: ReaderStorage,
    private readonly transport: ProgressSyncTransport,
    options: ReaderProgressSyncCoordinatorOptions = {}
  ) {
    this.debounceMs = options.debounceMs ?? READER_PROGRESS_DEBOUNCE_MS;
    this.now = options.now ?? Date.now;
    this.exitUploadTimeoutMs = options.exitUploadTimeoutMs ?? 2_500;
  }

  start() {
    if (this.started) return;
    this.started = true;
    if (typeof window !== 'undefined') {
      window.addEventListener('pagehide', this.handlePageHide);
      document.addEventListener('visibilitychange', this.handleVisibilityChange);
    }
  }

  stop() {
    if (typeof window !== 'undefined' && this.started) {
      window.removeEventListener('pagehide', this.handlePageHide);
      document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    }
    this.started = false;
    void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs });
  }

  activateUser(userId: string) {
    if (!userId) return;
    this.activeUserId = userId;
  }

  deactivateUser() {
    void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs });
    this.activeUserId = null;
  }

  enqueue(input: ProgressSaveInput) {
    if (this.activeUserId && this.activeUserId !== input.userId) {
      return Promise.reject(new Error('Progress owner does not match the active reader user'));
    }
    this.activeUserId = input.userId;
    this.pendingInput = input;
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.commitPending();
    }, Math.max(0, this.debounceMs));
    return new Promise<ExactProgressRecord>((resolve, reject) => {
      this.pendingWaiters.push({ resolve, reject });
    });
  }

  /** Used by one-shot migrations: persist exact data before deleting legacy data. */
  async saveExactOnly(input: ProgressSaveInput, updatedAtEpochMillis = this.now()) {
    const clientId = await this.storage.getClientId();
    const identity = {
      serverIdentity: input.serverIdentity,
      userId: input.userId,
      clientId,
      volumeId: input.volumeId,
      localContentFingerprint: input.localContentFingerprint
    };
    return this.storage.putExactProgress({
      ...identity,
      key: exactProgressKey(identity),
      schemaVersion: 1,
      workId: input.workId,
      location: input.location,
      percent: normalizedPercent(input.percent),
      updatedAtEpochMillis
    });
  }

  async flushNow(options: { timeoutMs?: number } = {}) {
    this.clearTimer();
    do {
      await this.commitPending();
    } while (this.pendingInput);
    const currentUpload = this.uploadPromise;
    if (!currentUpload) return;
    if (options.timeoutMs === undefined) {
      await currentUpload;
      return;
    }
    const timeoutMs = options.timeoutMs;
    let timeout: ReturnType<typeof setTimeout> | null = null;
    const completed = await Promise.race([
      currentUpload.then(() => true),
      new Promise<false>((resolve) => {
        timeout = setTimeout(() => resolve(false), Math.max(0, timeoutMs));
      })
    ]);
    if (timeout) clearTimeout(timeout);
    if (!completed) {
      this.uploadSlot = null;
      this.activeAbortController?.abort();
    }
  }

  getLatestServerSnapshot(volumeId: string) {
    return this.latestServerSnapshots.get(volumeId) ?? null;
  }

  private readonly handlePageHide = () => {
    void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs });
  };

  private readonly handleVisibilityChange = () => {
    if (document.visibilityState === 'hidden') {
      void this.flushNow({ timeoutMs: this.exitUploadTimeoutMs });
    }
  };

  private clearTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private commitPending() {
    if (this.commitPromise) return this.commitPromise;
    const input = this.pendingInput;
    const waiters = this.pendingWaiters;
    this.pendingInput = null;
    this.pendingWaiters = [];
    if (!input) return Promise.resolve(null);

    const updatedAtEpochMillis = this.now();
    this.commitPromise = this.saveExactOnly(input, updatedAtEpochMillis)
      .then((exact) => {
        waiters.forEach(({ resolve }) => resolve(exact));
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent(READER_PROGRESS_CHANGED_EVENT, { detail: exact }));
        }
        emitReaderDebug('info', '阅读位置已保存到本机精确进度', {
          volumeId: exact.volumeId,
          updatedAtEpochMillis
        });
        const percent = normalizedPercent(input.percent);
        if (percent !== null) {
          const snapshot: ReaderProgressSnapshot = {
            schemaVersion: 4,
            clientId: exact.clientId,
            updatedAtEpochMillis,
            percent,
            location: toV4WireLocation(input.location, input.locationContentFingerprint),
            contentFingerprint: input.contentFingerprint
          };
          this.queueUpload({ volumeId: input.volumeId, snapshot });
        }
        return exact;
      })
      .catch((reason) => {
        waiters.forEach(({ reject }) => reject(reason));
        throw reason;
      })
      .finally(() => {
        this.commitPromise = null;
      });
    return this.commitPromise;
  }

  private queueUpload(upload: ProgressUpload) {
    this.uploadSlot = upload;
    if (this.uploadPromise) return;
    this.uploadPromise = this.drainUploadSlot().finally(() => {
      this.uploadPromise = null;
      if (this.uploadSlot) this.queueUpload(this.uploadSlot);
    });
  }

  private async drainUploadSlot() {
    while (this.uploadSlot) {
      const upload = this.uploadSlot;
      this.uploadSlot = null;
      const controller = new AbortController();
      this.activeAbortController = controller;
      try {
        const serverSnapshot = await this.transport(upload, controller.signal);
        this.latestServerSnapshots.set(upload.volumeId, serverSnapshot);
        emitReaderDebug('info', '阅读进度快照已上传', {
          volumeId: upload.volumeId,
          updatedAtEpochMillis: upload.snapshot.updatedAtEpochMillis
        });
      } catch (reason) {
        if (!controller.signal.aborted) {
          emitReaderDebug('warning', '阅读进度上传失败，本次请求已放弃', {
            volumeId: upload.volumeId,
            error: reason instanceof Error ? reason.message : String(reason)
          });
        }
      } finally {
        if (this.activeAbortController === controller) this.activeAbortController = null;
      }
    }
  }
}

let defaultCoordinator: ReaderProgressSyncCoordinator | null = null;

export function setReaderProgressSyncCoordinator(coordinator: ReaderProgressSyncCoordinator | null) {
  if (defaultCoordinator === coordinator) return;
  defaultCoordinator?.stop();
  defaultCoordinator = coordinator;
  defaultCoordinator?.start();
}

export function getReaderProgressSyncCoordinator() {
  return defaultCoordinator;
}
