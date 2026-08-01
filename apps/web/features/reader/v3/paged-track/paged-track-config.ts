export type PagedTrackConfig = Readonly<{
  directionLockPx: number;
  tapSlopPx: number;
  horizontalIntentRatio: number;
  commitDistanceRatio: number;
  commitVelocityPxPerMs: number;
  recentVelocityWindowMs: number;
  boundaryResistanceRatio: number;
  minSettleDurationMs: number;
  maxSettleDurationMs: number;
  programmaticDurationMs: number;
  commandTimeoutMs: number;
}>;

export const DEFAULT_PAGED_TRACK_CONFIG: PagedTrackConfig = Object.freeze({
  directionLockPx: 8,
  tapSlopPx: 12,
  horizontalIntentRatio: 1.15,
  commitDistanceRatio: 0.25,
  commitVelocityPxPerMs: 0.45,
  recentVelocityWindowMs: 80,
  boundaryResistanceRatio: 0.15,
  minSettleDurationMs: 140,
  maxSettleDurationMs: 280,
  programmaticDurationMs: 200,
  commandTimeoutMs: 500
});

function positive(value: number, fallback: number) {
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function ratio(value: number, fallback: number, maximum = 1) {
  return Number.isFinite(value) && value > 0 && value <= maximum ? value : fallback;
}

/** Merge test/experiment overrides while keeping unsafe values out of physics. */
export function resolvePagedTrackConfig(overrides: Partial<PagedTrackConfig> = {}): PagedTrackConfig {
  const defaults = DEFAULT_PAGED_TRACK_CONFIG;
  const minSettleDurationMs = positive(overrides.minSettleDurationMs ?? defaults.minSettleDurationMs, defaults.minSettleDurationMs);
  const requestedMaximum = positive(overrides.maxSettleDurationMs ?? defaults.maxSettleDurationMs, defaults.maxSettleDurationMs);

  return Object.freeze({
    directionLockPx: positive(overrides.directionLockPx ?? defaults.directionLockPx, defaults.directionLockPx),
    tapSlopPx: positive(overrides.tapSlopPx ?? defaults.tapSlopPx, defaults.tapSlopPx),
    horizontalIntentRatio: positive(overrides.horizontalIntentRatio ?? defaults.horizontalIntentRatio, defaults.horizontalIntentRatio),
    commitDistanceRatio: ratio(overrides.commitDistanceRatio ?? defaults.commitDistanceRatio, defaults.commitDistanceRatio),
    commitVelocityPxPerMs: positive(
      overrides.commitVelocityPxPerMs ?? defaults.commitVelocityPxPerMs,
      defaults.commitVelocityPxPerMs
    ),
    recentVelocityWindowMs: positive(
      overrides.recentVelocityWindowMs ?? defaults.recentVelocityWindowMs,
      defaults.recentVelocityWindowMs
    ),
    boundaryResistanceRatio: ratio(
      overrides.boundaryResistanceRatio ?? defaults.boundaryResistanceRatio,
      defaults.boundaryResistanceRatio,
      0.5
    ),
    minSettleDurationMs,
    maxSettleDurationMs: Math.max(minSettleDurationMs, requestedMaximum),
    programmaticDurationMs: positive(
      overrides.programmaticDurationMs ?? defaults.programmaticDurationMs,
      defaults.programmaticDurationMs
    ),
    commandTimeoutMs: positive(overrides.commandTimeoutMs ?? defaults.commandTimeoutMs, defaults.commandTimeoutMs)
  });
}
