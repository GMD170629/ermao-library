import { resolvePagedTrackConfig, type PagedTrackConfig } from './paged-track-config';
import {
  applyPagedTrackBoundaryResistance,
  classifyPagedTrackIntent,
  pagedTrackRecentVelocity,
  pagedTrackSettleDuration,
  pageStepForLogicalOffset,
  physicalDeltaToLogicalOffset,
  resolvePagedTrackSettle,
  type PagedTrackMotionSample
} from './paged-track-physics';
import type {
  PageStep,
  PageTrackPhase,
  PagedTrackClock,
  PagedTrackCommitRequest,
  PagedTrackDriver,
  PagedTrackOperationOptions,
  PagedTrackPendingOperationOptions,
  PagedTrackPointerInput,
  PagedTrackPointerRelease,
  PagedTrackPointerResult,
  PagedTrackRequestCommit,
  PagedTrackSnapshot
} from './paged-track-types';

type GesturePreparation = {
  step: PageStep;
  controller: AbortController;
  promise: Promise<boolean>;
};

type ActiveGesture = {
  id: number;
  pointerId: number;
  startX: number;
  startY: number;
  lastX: number;
  lastY: number;
  lastTimeMs: number;
  viewportWidth: number;
  readingDirection: 'ltr' | 'rtl';
  hasPrevious: boolean;
  hasNext: boolean;
  claimed: boolean;
  maximumDistancePx: number;
  samples: PagedTrackMotionSample[];
  preparation?: GesturePreparation;
};

type PendingGesture = {
  id: number;
  pointerId: number;
  step: PageStep;
  velocityPxPerMs: number;
  timer: ReturnType<typeof setTimeout>;
};

type ActiveOperation = {
  epoch: number;
  controller: AbortController;
  cleanup: () => void;
};

export type PagedTrackControllerOptions = {
  config?: Partial<PagedTrackConfig>;
  requestCommit?: PagedTrackRequestCommit;
  boundaryCommitSteps?: readonly PageStep[];
  clock?: PagedTrackClock;
};

const DEFAULT_CLOCK: PagedTrackClock = {
  now: () => globalThis.performance?.now?.() ?? Date.now(),
  setTimeout: (callback, delayMs) => setTimeout(callback, delayMs),
  clearTimeout: (handle) => clearTimeout(handle)
};

function isAbortError(reason: unknown) {
  return reason instanceof DOMException
    ? reason.name === 'AbortError'
    : reason instanceof Error && reason.name === 'AbortError';
}

function available(snapshot: { hasNext: boolean; hasPrevious: boolean }, step: PageStep) {
  return step === 1 ? snapshot.hasNext : snapshot.hasPrevious;
}

/**
 * Format-independent paging state machine. It owns temporary visual motion,
 * but a gesture cannot promote the reader anchor until `acceptPending()` is
 * called from the session-authorized adapter command.
 */
export class PagedTrackController {
  readonly config: PagedTrackConfig;

  private phase: PageTrackPhase = 'idle';
  private logicalOffsetPx = 0;
  private gesture: ActiveGesture | null = null;
  private pending: PendingGesture | null = null;
  private operation: ActiveOperation | null = null;
  private gestureSequence = 0;
  private operationEpoch = 0;
  private queueGeneration = 0;
  private stepTail: Promise<void> = Promise.resolve();
  private disposed = false;
  private readonly requestCommit?: PagedTrackRequestCommit;
  private readonly boundaryCommitSteps: ReadonlySet<PageStep>;
  private readonly clock: PagedTrackClock;

  constructor(private readonly driver: PagedTrackDriver, options: PagedTrackControllerOptions = {}) {
    this.config = resolvePagedTrackConfig(options.config);
    this.requestCommit = options.requestCommit;
    this.boundaryCommitSteps = new Set(options.boundaryCommitSteps ?? []);
    this.clock = options.clock ?? DEFAULT_CLOCK;
  }

  snapshot(): PagedTrackSnapshot {
    const driver = this.driver.snapshot();
    return {
      ...driver,
      phase: this.phase,
      logicalOffsetPx: this.logicalOffsetPx,
      claimed: Boolean(this.gesture?.claimed),
      pendingStep: this.pending?.step ?? null,
      pendingGestureId: this.pending?.id ?? null
    };
  }

  getPendingStep() {
    return this.pending?.step ?? null;
  }

  pointerDown(input: PagedTrackPointerInput): PagedTrackPointerResult {
    if (
      this.disposed
      || this.phase !== 'idle'
      || input.isPrimary === false
      || !this.validPointerInput(input)
    ) {
      return this.pointerResult(false);
    }
    const snapshot = this.driver.snapshot();
    if (!Number.isFinite(snapshot.viewportWidth) || snapshot.viewportWidth <= 0) {
      return this.pointerResult(false);
    }

    const timeMs = this.inputTime(input);
    this.gesture = {
      id: ++this.gestureSequence,
      pointerId: input.pointerId,
      startX: input.clientX,
      startY: input.clientY,
      lastX: input.clientX,
      lastY: input.clientY,
      lastTimeMs: timeMs,
      viewportWidth: snapshot.viewportWidth,
      readingDirection: snapshot.readingDirection,
      hasPrevious: snapshot.hasPrevious,
      hasNext: snapshot.hasNext,
      claimed: false,
      maximumDistancePx: 0,
      samples: [{ logicalOffsetPx: 0, timeMs }]
    };
    this.phase = 'priming';
    return this.pointerResult(true);
  }

  pointerMove(input: PagedTrackPointerInput): PagedTrackPointerResult {
    const gesture = this.gesture;
    if (!gesture || input.pointerId !== gesture.pointerId || !this.validPointerInput(input)) {
      return this.pointerResult(false);
    }

    const deltaX = input.clientX - gesture.startX;
    const deltaY = input.clientY - gesture.startY;
    gesture.lastX = input.clientX;
    gesture.lastY = input.clientY;
    gesture.lastTimeMs = this.inputTime(input);
    gesture.maximumDistancePx = Math.max(gesture.maximumDistancePx, Math.hypot(deltaX, deltaY));

    if (!gesture.claimed) {
      const intent = classifyPagedTrackIntent(deltaX, deltaY, this.config);
      if (intent === 'undecided') return this.pointerResult(true);
      if (intent === 'vertical') {
        this.abortGesturePreparation(gesture);
        this.gesture = null;
        this.phase = 'idle';
        return this.pointerResult(false);
      }
      gesture.claimed = true;
      this.phase = 'dragging';
    }

    this.updateClaimedGesture(gesture, deltaX);
    return this.pointerResult(true);
  }

  async pointerUp(input: PagedTrackPointerInput): Promise<PagedTrackPointerRelease> {
    let gesture = this.gesture;
    if (!gesture || input.pointerId !== gesture.pointerId || !this.validPointerInput(input)) {
      return { kind: 'ignored', claimed: false, logicalOffsetPx: 0 };
    }

    this.pointerMove(input);
    gesture = this.gesture;
    if (!gesture) return { kind: 'ignored', claimed: false, logicalOffsetPx: 0 };

    if (!gesture.claimed) {
      this.gesture = null;
      this.phase = 'idle';
      const kind = gesture.maximumDistancePx <= this.config.tapSlopPx ? 'tap' : 'ignored';
      return { kind, claimed: false, logicalOffsetPx: 0 };
    }

    const velocityPxPerMs = pagedTrackRecentVelocity(gesture.samples, this.config.recentVelocityWindowMs);
    const rawLogicalOffset = physicalDeltaToLogicalOffset(
      gesture.lastX - gesture.startX,
      gesture.readingDirection
    );
    const boundaryStep = pageStepForLogicalOffset(rawLogicalOffset);
    const velocityStep = pageStepForLogicalOffset(velocityPxPerMs);
    const strongReverseVelocity = velocityStep !== 0
      && velocityStep !== boundaryStep
      && Math.abs(velocityPxPerMs) >= this.config.commitVelocityPxPerMs;
    const boundaryCommitRequested = boundaryStep !== 0
      && this.boundaryCommitSteps.has(boundaryStep)
      && !available(gesture, boundaryStep)
      && !strongReverseVelocity
      && (
        Math.abs(rawLogicalOffset) >= gesture.viewportWidth * this.config.commitDistanceRatio
        || Math.abs(velocityPxPerMs) >= this.config.commitVelocityPxPerMs
      );
    const decision = resolvePagedTrackSettle({
      logicalOffsetPx: this.logicalOffsetPx,
      velocityPxPerMs,
      viewportWidth: gesture.viewportWidth,
      hasPrevious: gesture.hasPrevious,
      hasNext: gesture.hasNext
    }, this.config);

    if (decision.target === 0) {
      this.gesture = null;
      this.abortGesturePreparation(gesture);
      await this.rollbackFromOffset();
      if (boundaryCommitRequested) {
        this.notifyCommitRequest({ gestureId: gesture.id, step: boundaryStep });
      }
      return {
        kind: 'rollback',
        reason: decision.reason,
        claimed: true,
        logicalOffsetPx: 0
      };
    }

    const preparation = this.ensureGesturePreparation(gesture, decision.target);
    const ready = await preparation.promise;
    if (this.gesture !== gesture || this.disposed || this.phase === 'suspended') {
      return { kind: 'rollback', reason: 'cancelled', claimed: true, logicalOffsetPx: 0 };
    }
    if (!ready) {
      this.gesture = null;
      this.abortGesturePreparation(gesture);
      await this.rollbackFromOffset();
      return { kind: 'rollback', reason: 'prepare-failed', claimed: true, logicalOffsetPx: 0 };
    }

    this.abortGesturePreparation(gesture);
    this.gesture = null;
    this.phase = 'awaiting-command';
    const timer = this.clock.setTimeout(() => {
      void this.rejectPending(gesture.id);
    }, this.config.commandTimeoutMs);
    this.pending = {
      id: gesture.id,
      pointerId: gesture.pointerId,
      step: decision.target,
      velocityPxPerMs,
      timer
    };
    const request = { gestureId: gesture.id, step: decision.target } satisfies PagedTrackCommitRequest;
    this.notifyCommitRequest(request);
    return {
      kind: 'commit-requested',
      claimed: true,
      logicalOffsetPx: this.logicalOffsetPx,
      ...request
    };
  }

  async pointerCancel(pointerId?: number) {
    const gesture = this.gesture;
    if (!gesture || (pointerId !== undefined && pointerId !== gesture.pointerId)) return false;
    this.gesture = null;
    this.abortGesturePreparation(gesture);
    await this.rollbackFromOffset();
    return true;
  }

  /** Settle a pending physical gesture after session.execute authorizes it. */
  async acceptPending(step: PageStep, options: PagedTrackPendingOperationOptions = {}) {
    const pending = this.pending;
    if (!pending) return false;
    if (options.gestureId !== undefined && options.gestureId !== pending.id) return false;
    if (step !== pending.step) {
      await this.rejectPending(pending.id, options);
      return false;
    }

    this.clearPending();
    return this.completePreparedStep(step, false, options.signal);
  }

  /** Roll a pending gesture back without promoting its candidate anchor. */
  async rejectPending(gestureId?: number, options: PagedTrackOperationOptions = {}) {
    const pending = this.pending;
    if (!pending || (gestureId !== undefined && gestureId !== pending.id)) return false;
    this.clearPending();
    await this.rollbackFromOffset(options.signal);
    return true;
  }

  /**
   * Queue a keyboard/button/tap-zone step. Every call remains a separate
   * prepare/animate/promote transaction and resolves only after recentering.
   */
  step(step: PageStep, options: PagedTrackOperationOptions = {}) {
    const generation = this.queueGeneration;
    const result = this.stepTail
      .catch(() => undefined)
      .then(async () => {
        if (
          this.disposed
          || generation !== this.queueGeneration
          || options.signal?.aborted
          || this.phase !== 'idle'
        ) return false;
        return this.runProgrammaticStep(step, options.signal);
      });
    this.stepTail = result.then(() => undefined, () => undefined);
    return result;
  }

  /** Immediately restore the last committed anchor and invalidate queued work. */
  interrupt(options: { suspended?: boolean } = {}) {
    this.queueGeneration += 1;
    this.operationEpoch += 1;
    this.operation?.controller.abort();
    this.operation?.cleanup();
    this.operation = null;
    if (this.gesture) this.abortGesturePreparation(this.gesture);
    this.gesture = null;
    this.clearPending();
    this.driver.cancel();
    this.driver.recenter();
    this.logicalOffsetPx = 0;
    this.phase = options.suspended ? 'suspended' : 'idle';
  }

  cancel() {
    this.interrupt();
  }

  suspend() {
    this.interrupt({ suspended: true });
  }

  resume() {
    if (this.disposed || this.phase !== 'suspended') return false;
    this.driver.recenter();
    this.logicalOffsetPx = 0;
    this.phase = 'idle';
    return true;
  }

  dispose() {
    if (this.disposed) return;
    this.interrupt({ suspended: true });
    this.disposed = true;
  }

  private validPointerInput(input: PagedTrackPointerInput) {
    return Number.isFinite(input.pointerId)
      && Number.isFinite(input.clientX)
      && Number.isFinite(input.clientY)
      && (input.timeMs === undefined || Number.isFinite(input.timeMs));
  }

  private inputTime(input: PagedTrackPointerInput) {
    return input.timeMs ?? this.clock.now();
  }

  private pointerResult(handled: boolean): PagedTrackPointerResult {
    const claimed = Boolean(this.gesture?.claimed);
    return {
      handled,
      claimed,
      preventDefault: claimed,
      phase: this.phase,
      logicalOffsetPx: this.logicalOffsetPx
    };
  }

  private updateClaimedGesture(gesture: ActiveGesture, physicalDeltaX: number) {
    const rawOffset = physicalDeltaToLogicalOffset(physicalDeltaX, gesture.readingDirection);
    const logicalOffset = applyPagedTrackBoundaryResistance(
      rawOffset,
      gesture.viewportWidth,
      gesture.hasPrevious,
      gesture.hasNext,
      this.config.boundaryResistanceRatio
    );
    this.logicalOffsetPx = logicalOffset;
    this.driver.setLogicalOffset(logicalOffset);
    gesture.samples.push({ logicalOffsetPx: logicalOffset, timeMs: gesture.lastTimeMs });
    this.trimGestureSamples(gesture);

    const candidate = pageStepForLogicalOffset(rawOffset);
    if (candidate === 0 || !available(gesture, candidate)) {
      this.abortGesturePreparation(gesture);
      return;
    }
    this.ensureGesturePreparation(gesture, candidate);
  }

  private trimGestureSamples(gesture: ActiveGesture) {
    const oldestUseful = gesture.lastTimeMs - this.config.recentVelocityWindowMs * 2;
    let firstUseful = gesture.samples.findIndex((sample) => sample.timeMs >= oldestUseful);
    if (firstUseful < 1) return;
    // Retain one sample before the window so velocity has a stable baseline.
    firstUseful -= 1;
    gesture.samples.splice(0, firstUseful);
  }

  private ensureGesturePreparation(gesture: ActiveGesture, step: PageStep) {
    if (gesture.preparation?.step === step) return gesture.preparation;
    this.abortGesturePreparation(gesture);
    const controller = new AbortController();
    const promise = Promise.resolve()
      .then(() => this.driver.prepare(step, controller.signal))
      .then(Boolean)
      .catch(() => false);
    const preparation = { step, controller, promise };
    gesture.preparation = preparation;
    return preparation;
  }

  private abortGesturePreparation(gesture: ActiveGesture) {
    gesture.preparation?.controller.abort();
    gesture.preparation = undefined;
  }

  private notifyCommitRequest(request: PagedTrackCommitRequest) {
    if (!this.requestCommit) return;
    try {
      const result = this.requestCommit(request);
      void Promise.resolve(result).then((accepted) => {
        if (accepted === false) void this.rejectPending(request.gestureId);
      }, () => {
        void this.rejectPending(request.gestureId);
      });
    } catch {
      void this.rejectPending(request.gestureId);
    }
  }

  private clearPending() {
    if (!this.pending) return;
    this.clock.clearTimeout(this.pending.timer);
    this.pending = null;
  }

  private async runProgrammaticStep(step: PageStep, signal?: AbortSignal) {
    const snapshot = this.driver.snapshot();
    if (!available(snapshot, step)) return false;
    const operation = this.beginOperation(signal);
    this.phase = 'priming';
    try {
      const prepared = await this.driver.prepare(step, operation.controller.signal);
      if (!prepared || !this.isCurrentOperation(operation)) {
        if (this.isCurrentOperation(operation)) this.phase = 'idle';
        return false;
      }
      return await this.completeStepWithOperation(step, true, operation);
    } catch (reason) {
      return this.handleOperationFailure(operation, reason);
    } finally {
      this.finishOperation(operation);
    }
  }

  private async completePreparedStep(step: PageStep, programmatic: boolean, signal?: AbortSignal) {
    if (this.disposed || this.phase === 'suspended') return false;
    const operation = this.beginOperation(signal);
    try {
      return await this.completeStepWithOperation(step, programmatic, operation);
    } catch (reason) {
      return this.handleOperationFailure(operation, reason);
    } finally {
      this.finishOperation(operation);
    }
  }

  private async completeStepWithOperation(step: PageStep, programmatic: boolean, operation: ActiveOperation) {
    if (!this.isCurrentOperation(operation)) return false;
    const snapshot = this.driver.snapshot();
    const duration = pagedTrackSettleDuration({
      logicalOffsetPx: this.logicalOffsetPx,
      target: step,
      viewportWidth: snapshot.viewportWidth,
      reducedMotion: snapshot.reducedMotion,
      programmatic
    }, this.config);
    this.phase = 'settling';
    await this.driver.animateTo(step, duration, operation.controller.signal);
    if (!this.isCurrentOperation(operation)) return false;

    this.phase = 'reconciling';
    await this.driver.promote(step, operation.controller.signal);
    if (!this.isCurrentOperation(operation)) return false;
    this.driver.recenter();
    this.logicalOffsetPx = 0;
    this.phase = 'idle';
    return true;
  }

  private async rollbackFromOffset(signal?: AbortSignal) {
    if (this.disposed || this.phase === 'suspended') return false;
    const operation = this.beginOperation(signal);
    const snapshot = this.driver.snapshot();
    const duration = pagedTrackSettleDuration({
      logicalOffsetPx: this.logicalOffsetPx,
      target: 0,
      viewportWidth: snapshot.viewportWidth,
      reducedMotion: snapshot.reducedMotion
    }, this.config);
    this.phase = 'settling';
    try {
      await this.driver.animateTo(0, duration, operation.controller.signal);
      if (!this.isCurrentOperation(operation)) return false;
      this.driver.recenter();
      this.logicalOffsetPx = 0;
      this.phase = 'idle';
      return true;
    } catch (reason) {
      return this.handleOperationFailure(operation, reason);
    } finally {
      this.finishOperation(operation);
    }
  }

  private beginOperation(externalSignal?: AbortSignal) {
    this.operation?.controller.abort();
    this.operation?.cleanup();
    const controller = new AbortController();
    const abort = () => controller.abort(externalSignal?.reason);
    if (externalSignal?.aborted) abort();
    else externalSignal?.addEventListener('abort', abort, { once: true });
    const operation: ActiveOperation = {
      epoch: ++this.operationEpoch,
      controller,
      cleanup: () => externalSignal?.removeEventListener('abort', abort)
    };
    this.operation = operation;
    return operation;
  }

  private isCurrentOperation(operation: ActiveOperation) {
    return this.operation === operation
      && operation.epoch === this.operationEpoch
      && !operation.controller.signal.aborted;
  }

  private finishOperation(operation: ActiveOperation) {
    operation.cleanup();
    if (this.operation !== operation) return;
    if (operation.controller.signal.aborted) {
      this.driver.cancel();
      this.driver.recenter();
      this.logicalOffsetPx = 0;
      this.phase = this.disposed ? 'suspended' : 'idle';
    }
    this.operation = null;
  }

  private handleOperationFailure(operation: ActiveOperation, reason: unknown): false {
    if (this.operation === operation) {
      this.driver.cancel();
      this.driver.recenter();
      this.logicalOffsetPx = 0;
      this.phase = this.disposed ? 'suspended' : 'idle';
    }
    if (operation.controller.signal.aborted || isAbortError(reason)) return false;
    throw reason;
  }
}
