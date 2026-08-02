import { emitReaderDebug } from './debug';
import {
  READER_PROGRESS_DEBOUNCE_MS,
  type ProgressMutationInput,
  type ProgressSyncTransport
} from './model';
import type { ReaderStorage } from './storage';

type ReaderProgressSyncCoordinatorOptions = {
  debounceMs?: number;
  leaseTtlMs?: number;
  retryBaseMs?: number;
  retryMaximumMs?: number;
  now?: () => number;
};

export const READER_PROGRESS_CHANGED_EVENT = 'shuku:reader-progress-changed';
export const READER_PROGRESS_SYNC_CHANNEL = 'shuku-reader-v3-sync';

function runtimeId() {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `runtime_${suffix}`;
}

/**
 * ReaderSession -> enqueue (durable) -> debounce -> lease -> strict sequence
 *                                               -> transport -> compare-delete
 *                                               -> retry/quarantine
 *
 * This is the only progress network writer. pagehide/visibility events may wake
 * it, but correctness comes from the durable outbox, never from a beacon.
 */
export class ReaderProgressSyncCoordinator {
  private readonly ownerId = runtimeId();
  private readonly debounceMs: number;
  private readonly leaseTtlMs: number;
  private readonly retryBaseMs: number;
  private readonly retryMaximumMs: number;
  private readonly now: () => number;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private renewalTimer: ReturnType<typeof setInterval> | null = null;
  private flushPromise: Promise<void> | null = null;
  private activeAbortController: AbortController | null = null;
  private channel: BroadcastChannel | null = null;
  private started = false;
  private lostLease = false;
  private activeUserId: string | null = null;

  constructor(
    private readonly storage: ReaderStorage,
    private readonly transport: ProgressSyncTransport,
    options: ReaderProgressSyncCoordinatorOptions = {}
  ) {
    this.debounceMs = options.debounceMs ?? READER_PROGRESS_DEBOUNCE_MS;
    this.leaseTtlMs = options.leaseTtlMs ?? 9_000;
    this.retryBaseMs = options.retryBaseMs ?? 1_000;
    this.retryMaximumMs = options.retryMaximumMs ?? 60_000;
    this.now = options.now ?? Date.now;
  }

  start() {
    if (this.started) return;
    this.started = true;
    if (typeof BroadcastChannel !== 'undefined') {
      this.channel = new BroadcastChannel(READER_PROGRESS_SYNC_CHANNEL);
      this.channel.addEventListener('message', this.handleBroadcast);
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('online', this.handleOnline);
      window.addEventListener('pagehide', this.handlePageHide);
      document.addEventListener('visibilitychange', this.handleVisibilityChange);
    }
    if (this.activeUserId) this.schedule(0);
  }

  stop() {
    this.clearTimer();
    this.stopRenewal();
    this.activeAbortController?.abort();
    this.activeAbortController = null;
    if (!this.started) {
      void this.storage.releaseProgressLease(this.ownerId);
      return;
    }
    this.started = false;
    this.channel?.removeEventListener('message', this.handleBroadcast);
    this.channel?.close();
    this.channel = null;
    if (typeof window !== 'undefined') {
      window.removeEventListener('online', this.handleOnline);
      window.removeEventListener('pagehide', this.handlePageHide);
      document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    }
    void this.storage.releaseProgressLease(this.ownerId);
  }

  async enqueue(input: ProgressMutationInput) {
    this.activateUser(input.userId);
    const mutation = await this.storage.enqueueProgress(input, this.now());
    emitReaderDebug('info', '阅读进度已写入本地队列', {
      volumeId: mutation.volumeId,
      clientSequence: mutation.clientSequence
    });
    this.channel?.postMessage({ type: 'progress-enqueued' });
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(READER_PROGRESS_CHANGED_EVENT, { detail: mutation }));
    }
    this.schedule(this.debounceMs);
    return mutation;
  }

  activateUser(userId: string) {
    if (!userId || this.activeUserId === userId) return;
    this.activeUserId = userId;
    this.activeAbortController?.abort();
    emitReaderDebug('info', '已激活当前用户的阅读进度队列');
    if (this.flushPromise) void this.flushPromise.finally(() => this.schedule(0));
    else this.schedule(0);
  }

  deactivateUser() {
    this.activeUserId = null;
    this.clearTimer();
    this.activeAbortController?.abort();
    void this.storage.releaseProgressLease(this.ownerId);
  }

  flushNow() {
    this.clearTimer();
    if (this.flushPromise) return this.flushPromise;
    this.flushPromise = this.flushLoop().finally(() => {
      this.flushPromise = null;
    });
    return this.flushPromise;
  }

  private readonly handleBroadcast = (event: MessageEvent) => {
    if (event.data?.type === 'progress-enqueued') this.schedule(this.debounceMs);
  };

  private readonly handleOnline = () => this.schedule(0);
  private readonly handlePageHide = () => void this.flushNow();
  private readonly handleVisibilityChange = () => {
    if (document.visibilityState === 'hidden') void this.flushNow();
  };

  private clearTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private schedule(delayMs: number) {
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.flushNow();
    }, Math.max(0, delayMs));
  }

  private startRenewal() {
    this.lostLease = false;
    this.renewalTimer = setInterval(() => {
      void this.storage.renewProgressLease(this.ownerId, this.leaseTtlMs, this.now()).then((renewed) => {
        if (renewed) return;
        this.lostLease = true;
        this.activeAbortController?.abort();
        emitReaderDebug('warning', '阅读进度同步租约已丢失');
      });
    }, Math.max(250, Math.floor(this.leaseTtlMs / 3)));
  }

  private stopRenewal() {
    if (this.renewalTimer) clearInterval(this.renewalTimer);
    this.renewalTimer = null;
  }

  private retryDelay(retryCount: number) {
    return Math.min(this.retryMaximumMs, this.retryBaseMs * 2 ** Math.min(10, retryCount));
  }

  private async flushLoop() {
    const activeUserId = this.activeUserId;
    if (!activeUserId) return;
    const acquired = await this.storage.acquireProgressLease(this.ownerId, this.leaseTtlMs, this.now());
    if (!acquired) {
      this.schedule(this.leaseTtlMs);
      return;
    }

    this.startRenewal();
    emitReaderDebug('info', '已取得阅读进度同步租约', { ownerId: this.ownerId });
    try {
      while (!this.lostLease) {
        if (this.activeUserId !== activeUserId) return;
        const mutation = (await this.storage.listProgress()).find((item) => item.userId === activeUserId);
        if (!mutation) return;

        const now = this.now();
        if (mutation.nextAttemptAt > now) {
          this.schedule(mutation.nextAttemptAt - now);
          return;
        }

        const controller = new AbortController();
        this.activeAbortController = controller;
        try {
          const result = await this.transport(mutation, controller.signal);
          if (this.lostLease) return;
          if (result.outcome === 'accepted' || result.outcome === 'stale') {
            const deleted = await this.storage.compareDeleteProgress(mutation.mutationId);
            emitReaderDebug('info', result.outcome === 'stale' ? '服务端已忽略过期阅读进度' : '阅读进度同步完成', {
              clientSequence: mutation.clientSequence,
              deleted
            });
            continue;
          }

          const reason = result.outcome === 'fingerprint-conflict' ? 'fingerprint-conflict' : 'terminal';
          const message = result.message ?? '内容指纹已变化，旧进度未写入新内容';
          await this.storage.quarantineProgress(mutation, reason, message, this.now());
          await this.storage.addDiagnostic({
            level: result.outcome === 'fingerprint-conflict' ? 'warning' : 'error',
            code: result.outcome,
            message,
            data: { volumeId: mutation.volumeId, mutationId: mutation.mutationId }
          }, this.now());
          emitReaderDebug(result.outcome === 'fingerprint-conflict' ? 'warning' : 'error', message, {
            volumeId: mutation.volumeId,
            mutationId: mutation.mutationId
          });
        } catch (error) {
          if (controller.signal.aborted || this.lostLease) return;
          const delay = this.retryDelay(mutation.retryCount);
          const retained = await this.storage.markProgressRetry(mutation.mutationId, this.now() + delay, this.now());
          emitReaderDebug('warning', '阅读进度同步失败，已保留并顺序重试', {
            mutationId: mutation.mutationId,
            retained,
            retryInMs: delay,
            error: error instanceof Error ? error.message : String(error)
          });
          if (!retained) continue;
          this.schedule(delay);
          return;
        } finally {
          if (this.activeAbortController === controller) this.activeAbortController = null;
        }
      }
    } finally {
      this.stopRenewal();
      await this.storage.releaseProgressLease(this.ownerId);
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
