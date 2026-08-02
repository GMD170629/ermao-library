export type PageStep = -1 | 1;

export type PageTrackTarget = PageStep | 0;

export type PageTrackPhase =
  | 'idle'
  | 'priming'
  | 'dragging'
  | 'awaiting-command'
  | 'settling'
  | 'reconciling'
  | 'suspended';

export type PagedTrackReadingDirection = 'ltr' | 'rtl';

/**
 * Driver-owned facts about the currently rendered track. `phase`, when
 * supplied, is ignored by the controller and exists only for compatibility
 * with the original design contract. The controller always overlays its own
 * authoritative phase in `snapshot()`.
 */
export type PagedTrackDriverSnapshot = {
  phase?: PageTrackPhase;
  readingDirection: PagedTrackReadingDirection;
  viewportWidth: number;
  hasPrevious: boolean;
  hasNext: boolean;
  reducedMotion: boolean;
};

export type PagedTrackSnapshot = PagedTrackDriverSnapshot & {
  phase: PageTrackPhase;
  logicalOffsetPx: number;
  claimed: boolean;
  pendingStep: PageStep | null;
  pendingGestureId: number | null;
};

/**
 * All offsets passed to a driver are logical: positive reveals `next`,
 * negative reveals `previous`. The driver alone maps that logical sign onto
 * physical LTR/RTL scroll coordinates.
 */
export interface PagedTrackDriver {
  snapshot(): PagedTrackDriverSnapshot;
  prepare(step: PageStep, signal: AbortSignal): Promise<boolean>;
  setLogicalOffset(offsetPx: number): void;
  animateTo(target: PageTrackTarget, durationMs: number, signal: AbortSignal): Promise<void>;
  promote(step: PageStep, signal: AbortSignal): Promise<void>;
  recenter(): void;
  cancel(): void;
}

export type PagedTrackPointerInput = {
  pointerId: number;
  clientX: number;
  clientY: number;
  timeMs?: number;
  isPrimary?: boolean;
};

export type PagedTrackPointerResult = {
  handled: boolean;
  claimed: boolean;
  preventDefault: boolean;
  phase: PageTrackPhase;
  logicalOffsetPx: number;
};

export type PagedTrackCommitRequest = {
  gestureId: number;
  step: PageStep;
};

export type PagedTrackPointerRelease =
  | {
      kind: 'ignored' | 'tap';
      claimed: false;
      logicalOffsetPx: 0;
    }
  | {
      kind: 'rollback';
      reason: 'boundary' | 'cancelled' | 'insufficient' | 'prepare-failed' | 'reverse-velocity';
      claimed: true;
      logicalOffsetPx: 0;
    }
  | ({
      kind: 'commit-requested';
      claimed: true;
      logicalOffsetPx: number;
    } & PagedTrackCommitRequest);

export type PagedTrackOperationOptions = {
  signal?: AbortSignal;
};

export type PagedTrackPendingOperationOptions = PagedTrackOperationOptions & {
  gestureId?: number;
};

export type PagedTrackRequestCommit = (
  request: PagedTrackCommitRequest
) => void | boolean | Promise<void | boolean>;

export type PagedTrackClock = {
  now(): number;
  setTimeout(callback: () => void, delayMs: number): ReturnType<typeof setTimeout>;
  clearTimeout(handle: ReturnType<typeof setTimeout>): void;
};
