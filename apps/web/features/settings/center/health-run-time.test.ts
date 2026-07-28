import assert from 'node:assert/strict';
import test from 'node:test';
import { healthRunElapsedMs } from './health-run-time';

test('health run elapsed time uses epoch milliseconds without producing NaN', () => {
  assert.equal(healthRunElapsedMs(1_000, 3_500, 9_000), 2_500);
  assert.equal(healthRunElapsedMs(1_000, null, 4_000), 3_000);
  assert.equal(healthRunElapsedMs(Number.NaN, null, 4_000), 0);
});
