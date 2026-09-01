import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createScrollViewportPlan,
  normalizedHorizontalScrollOffset,
  rawHorizontalScrollOffset
} from './scroll-page-turn';

test('moves 88 percent of a viewport and reaches short remaining content before crossing', () => {
  assert.deepEqual(createScrollViewportPlan({ current: 100, maximum: 3000, viewport: 1000 }, 'next'), {
    atBoundary: false,
    target: 980
  });
  assert.deepEqual(createScrollViewportPlan({ current: 2800, maximum: 3000, viewport: 1000 }, 'next'), {
    atBoundary: false,
    target: 3000
  });
  assert.deepEqual(createScrollViewportPlan({ current: 3000, maximum: 3000, viewport: 1000 }, 'next'), {
    atBoundary: true,
    target: 3000
  });
  assert.deepEqual(createScrollViewportPlan({ current: 0.5, maximum: 3000, viewport: 1000 }, 'previous'), {
    atBoundary: true,
    target: 0.5
  });
});

test('normalizes every RTL scrollLeft model to one forward coordinate', () => {
  const maximum = 1200;
  for (const [model, raw] of [['negative', -400], ['reverse', 400], ['default', 800]] as const) {
    assert.equal(normalizedHorizontalScrollOffset(raw, maximum, 'rtl', model), 400);
    assert.equal(rawHorizontalScrollOffset(400, maximum, 'rtl', model), raw);
  }
  assert.equal(normalizedHorizontalScrollOffset(400, maximum, 'ltr', 'negative'), 400);
  assert.equal(rawHorizontalScrollOffset(400, maximum, 'ltr', 'negative'), 400);
});
