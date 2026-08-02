import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_PAGED_TRACK_CONFIG, resolvePagedTrackConfig } from './paged-track-config';
import {
  applyPagedTrackBoundaryResistance,
  classifyPagedTrackIntent,
  pagedTrackRecentVelocity,
  pagedTrackSettleDuration,
  pageStepForLogicalOffset,
  physicalDeltaToLogicalOffset,
  resolvePagedTrackSettle
} from './paged-track-physics';

test('paged track config exposes the V1 defaults and rejects unsafe overrides', () => {
  assert.deepEqual(DEFAULT_PAGED_TRACK_CONFIG, {
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

  const resolved = resolvePagedTrackConfig({
    directionLockPx: -1,
    commitDistanceRatio: 2,
    boundaryResistanceRatio: 0.75,
    minSettleDurationMs: 220,
    maxSettleDurationMs: 100
  });
  assert.equal(resolved.directionLockPx, 8);
  assert.equal(resolved.commitDistanceRatio, 0.25);
  assert.equal(resolved.boundaryResistanceRatio, 0.15);
  assert.equal(resolved.minSettleDurationMs, 220);
  assert.equal(resolved.maxSettleDurationMs, 220);
});

test('direction lock waits for 8px and claims only clearly horizontal movement', () => {
  const config = DEFAULT_PAGED_TRACK_CONFIG;
  assert.equal(classifyPagedTrackIntent(7, 0, config), 'undecided');
  assert.equal(classifyPagedTrackIntent(9, 0, config), 'horizontal');
  assert.equal(classifyPagedTrackIntent(-12, 5, config), 'horizontal');
  assert.equal(classifyPagedTrackIntent(9, 8, config), 'vertical');
  assert.equal(classifyPagedTrackIntent(1, 9, config), 'vertical');
  assert.equal(classifyPagedTrackIntent(Number.NaN, 0, config), 'undecided');
});

test('screen deltas map to one logical direction in LTR and RTL', () => {
  assert.equal(physicalDeltaToLogicalOffset(-100, 'ltr'), 100);
  assert.equal(physicalDeltaToLogicalOffset(100, 'ltr'), -100);
  assert.equal(physicalDeltaToLogicalOffset(100, 'rtl'), 100);
  assert.equal(physicalDeltaToLogicalOffset(-100, 'rtl'), -100);
  assert.equal(pageStepForLogicalOffset(1), 1);
  assert.equal(pageStepForLogicalOffset(-1), -1);
  assert.equal(pageStepForLogicalOffset(0), 0);
});

test('terminal velocity uses only samples from the recent tail', () => {
  const velocity = pagedTrackRecentVelocity([
    { logicalOffsetPx: 0, timeMs: 0 },
    { logicalOffsetPx: 10, timeMs: 100 },
    { logicalOffsetPx: 30, timeMs: 130 },
    { logicalOffsetPx: 70, timeMs: 180 }
  ], 80);
  assert.equal(velocity, 0.75);
  assert.equal(pagedTrackRecentVelocity([{ logicalOffsetPx: 10, timeMs: 10 }], 80), 0);
  assert.equal(pagedTrackRecentVelocity([
    { logicalOffsetPx: 0, timeMs: 10 },
    { logicalOffsetPx: 20, timeMs: 10 }
  ], 80), 0);
});

test('boundary resistance clamps available motion and rubber-bands a missing neighbor', () => {
  assert.equal(applyPagedTrackBoundaryResistance(600, 400, true, true, 0.15), 400);
  assert.equal(applyPagedTrackBoundaryResistance(-600, 400, true, true, 0.15), -400);

  const resistedNext = applyPagedTrackBoundaryResistance(400, 400, true, false, 0.15);
  const resistedPrevious = applyPagedTrackBoundaryResistance(-400, 400, false, true, 0.15);
  assert.ok(resistedNext > 0 && resistedNext < 60);
  assert.ok(resistedPrevious < 0 && resistedPrevious > -60);
  assert.equal(applyPagedTrackBoundaryResistance(100, 0, false, false, 0.15), 0);
});

test('settle target accepts distance or recent velocity, but rejects reverse flings and boundaries', () => {
  const config = DEFAULT_PAGED_TRACK_CONFIG;
  assert.deepEqual(resolvePagedTrackSettle({
    logicalOffsetPx: 100,
    velocityPxPerMs: 0.1,
    viewportWidth: 400,
    hasPrevious: true,
    hasNext: true
  }, config), { target: 1, reason: 'distance' });

  assert.deepEqual(resolvePagedTrackSettle({
    logicalOffsetPx: -40,
    velocityPxPerMs: -0.8,
    viewportWidth: 400,
    hasPrevious: true,
    hasNext: true
  }, config), { target: -1, reason: 'velocity' });

  assert.deepEqual(resolvePagedTrackSettle({
    logicalOffsetPx: 160,
    velocityPxPerMs: -0.7,
    viewportWidth: 400,
    hasPrevious: true,
    hasNext: true
  }, config), { target: 0, reason: 'reverse-velocity' });

  assert.deepEqual(resolvePagedTrackSettle({
    logicalOffsetPx: 160,
    velocityPxPerMs: 0.7,
    viewportWidth: 400,
    hasPrevious: true,
    hasNext: false
  }, config), { target: 0, reason: 'boundary' });

  assert.deepEqual(resolvePagedTrackSettle({
    logicalOffsetPx: 50,
    velocityPxPerMs: 0.2,
    viewportWidth: 400,
    hasPrevious: true,
    hasNext: true
  }, config), { target: 0, reason: 'insufficient' });
});

test('settle duration is distance-sensitive and reduced motion keeps the same zero-duration path', () => {
  const config = DEFAULT_PAGED_TRACK_CONFIG;
  assert.equal(pagedTrackSettleDuration({
    logicalOffsetPx: 0,
    target: 1,
    viewportWidth: 400,
    reducedMotion: false,
    programmatic: true
  }, config), 200);
  assert.equal(pagedTrackSettleDuration({
    logicalOffsetPx: 100,
    target: 1,
    viewportWidth: 400,
    reducedMotion: false
  }, config), 245);
  assert.equal(pagedTrackSettleDuration({
    logicalOffsetPx: 40,
    target: 0,
    viewportWidth: 400,
    reducedMotion: false
  }, config), 154);
  assert.equal(pagedTrackSettleDuration({
    logicalOffsetPx: 100,
    target: 1,
    viewportWidth: 400,
    reducedMotion: true
  }, config), 0);
});
