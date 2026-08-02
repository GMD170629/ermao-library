import type { PagedTrackConfig } from './paged-track-config';
import type { PageStep, PageTrackTarget, PagedTrackReadingDirection } from './paged-track-types';

export type PagedTrackIntent = 'undecided' | 'horizontal' | 'vertical';

export type PagedTrackMotionSample = {
  logicalOffsetPx: number;
  timeMs: number;
};

export type PagedTrackSettleReason =
  | 'boundary'
  | 'distance'
  | 'insufficient'
  | 'reverse-velocity'
  | 'velocity';

export type PagedTrackSettleDecision =
  | {
      target: 0;
      reason: 'boundary' | 'insufficient' | 'reverse-velocity';
    }
  | {
      target: PageStep;
      reason: 'distance' | 'velocity';
    };

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function finite(value: number) {
  return Number.isFinite(value) ? value : 0;
}

export function classifyPagedTrackIntent(
  deltaX: number,
  deltaY: number,
  config: Pick<PagedTrackConfig, 'directionLockPx' | 'horizontalIntentRatio'>
): PagedTrackIntent {
  const x = Math.abs(finite(deltaX));
  const y = Math.abs(finite(deltaY));
  if (Math.hypot(x, y) < config.directionLockPx) return 'undecided';
  return x > y * config.horizontalIntentRatio ? 'horizontal' : 'vertical';
}

/** Convert screen-space movement into a direction-independent track offset. */
export function physicalDeltaToLogicalOffset(deltaX: number, direction: PagedTrackReadingDirection) {
  const normalized = finite(deltaX);
  return direction === 'rtl' ? normalized : -normalized;
}

export function pageStepForLogicalOffset(offsetPx: number): PageStep | 0 {
  if (offsetPx > 0) return 1;
  if (offsetPx < 0) return -1;
  return 0;
}

/**
 * Calculates terminal velocity from the recent tail only. Samples are
 * expected in chronological order; duplicate or invalid timestamps are
 * ignored rather than producing an infinite fling.
 */
export function pagedTrackRecentVelocity(samples: readonly PagedTrackMotionSample[], windowMs: number) {
  if (samples.length < 2 || !Number.isFinite(windowMs) || windowMs <= 0) return 0;
  const end = samples[samples.length - 1];
  if (!end || !Number.isFinite(end.timeMs) || !Number.isFinite(end.logicalOffsetPx)) return 0;

  const cutoff = end.timeMs - windowMs;
  let start: PagedTrackMotionSample | undefined;
  for (let index = samples.length - 2; index >= 0; index -= 1) {
    const candidate = samples[index];
    if (!candidate || !Number.isFinite(candidate.timeMs) || !Number.isFinite(candidate.logicalOffsetPx)) continue;
    if (candidate.timeMs >= end.timeMs) continue;
    if (candidate.timeMs < cutoff) break;
    start = candidate;
  }
  if (!start) return 0;
  const elapsed = end.timeMs - start.timeMs;
  return elapsed > 0 ? (end.logicalOffsetPx - start.logicalOffsetPx) / elapsed : 0;
}

/**
 * Keep available movement within the neighboring slot. At a hard boundary,
 * an exponential rubber band remains continuous at zero and asymptotically
 * approaches the configured maximum.
 */
export function applyPagedTrackBoundaryResistance(
  logicalOffsetPx: number,
  viewportWidth: number,
  hasPrevious: boolean,
  hasNext: boolean,
  maximumRatio: number
) {
  const width = Math.max(0, finite(viewportWidth));
  if (width === 0) return 0;
  const offset = clamp(finite(logicalOffsetPx), -width, width);
  const blocked = (offset > 0 && !hasNext) || (offset < 0 && !hasPrevious);
  if (!blocked) return offset;

  const maximum = width * clamp(finite(maximumRatio), 0, 0.5);
  if (maximum === 0) return 0;
  const resisted = maximum * (1 - Math.exp(-Math.abs(offset) / maximum));
  return Math.sign(offset) * resisted;
}

export function resolvePagedTrackSettle(
  input: {
    logicalOffsetPx: number;
    velocityPxPerMs: number;
    viewportWidth: number;
    hasPrevious: boolean;
    hasNext: boolean;
  },
  config: Pick<PagedTrackConfig, 'commitDistanceRatio' | 'commitVelocityPxPerMs'>
): PagedTrackSettleDecision {
  const width = Math.max(0, finite(input.viewportWidth));
  const offset = finite(input.logicalOffsetPx);
  const velocity = finite(input.velocityPxPerMs);
  if (width === 0) return { target: 0, reason: 'insufficient' };

  const offsetStep = pageStepForLogicalOffset(offset);
  const velocityStep = pageStepForLogicalOffset(velocity);
  if (
    offsetStep !== 0
    && velocityStep !== 0
    && offsetStep !== velocityStep
    && Math.abs(velocity) >= config.commitVelocityPxPerMs
  ) {
    return { target: 0, reason: 'reverse-velocity' };
  }

  const distanceReached = Math.abs(offset) >= width * config.commitDistanceRatio;
  const velocityReached = Math.abs(velocity) >= config.commitVelocityPxPerMs;
  const target = offsetStep || (velocityReached ? velocityStep : 0);
  if (target === 0 || (!distanceReached && !velocityReached)) {
    return { target: 0, reason: 'insufficient' };
  }
  if ((target === 1 && !input.hasNext) || (target === -1 && !input.hasPrevious)) {
    return { target: 0, reason: 'boundary' };
  }
  return { target, reason: distanceReached ? 'distance' : 'velocity' };
}

export function pagedTrackSettleDuration(
  input: {
    logicalOffsetPx: number;
    target: PageTrackTarget;
    viewportWidth: number;
    reducedMotion: boolean;
    programmatic?: boolean;
  },
  config: Pick<
    PagedTrackConfig,
    'minSettleDurationMs' | 'maxSettleDurationMs' | 'programmaticDurationMs'
  >
) {
  const width = Math.max(0, finite(input.viewportWidth));
  if (input.reducedMotion || width === 0) return 0;
  const targetOffset = input.target * width;
  const remaining = Math.abs(targetOffset - finite(input.logicalOffsetPx));
  if (remaining < 0.5) return 0;
  if (input.programmatic) return Math.round(config.programmaticDurationMs);

  const ratio = clamp(remaining / width, 0, 1);
  return Math.round(
    config.minSettleDurationMs
    + (config.maxSettleDurationMs - config.minSettleDurationMs) * ratio
  );
}
