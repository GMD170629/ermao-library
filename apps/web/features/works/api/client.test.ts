import assert from 'node:assert/strict';
import test from 'node:test';
import { mapWorkView } from './client';

test('full work responses reject summary projections before reaching detail UI', () => {
  assert.throws(
    () => mapWorkView({ id: 'work-1', title: 'Summary only' }),
    /媒介版本结构/
  );
});
