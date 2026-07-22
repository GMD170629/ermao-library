import assert from 'node:assert/strict';
import { test } from 'node:test';
import { comicVisualSpreadPages } from './comic-reading-order';

test('comicVisualSpreadPages keeps left-to-right spreads in logical order', () => {
  assert.deepEqual(comicVisualSpreadPages([1, 2], 'ltr'), [1, 2]);
  assert.deepEqual(comicVisualSpreadPages([3, 4], 'ltr'), [3, 4]);
});

test('comicVisualSpreadPages places earlier pages on the right for right-to-left spreads', () => {
  assert.deepEqual(comicVisualSpreadPages([1, 2], 'rtl'), [2, 1]);
  assert.deepEqual(comicVisualSpreadPages([3, 4], 'rtl'), [4, 3]);
});

test('comicVisualSpreadPages leaves single pages visible in either direction', () => {
  assert.deepEqual(comicVisualSpreadPages([1], 'ltr'), [1]);
  assert.deepEqual(comicVisualSpreadPages([1], 'rtl'), [1]);
});
