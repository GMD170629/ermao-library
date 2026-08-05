import assert from 'node:assert/strict';
import test from 'node:test';
import {
  captureContinuousAnchor,
  continuousItemAtReadingLine,
  ContinuousOffsetIndex,
  continuousPlaceholderRanges,
  estimatedContinuousHeight,
  restoreContinuousAnchor
} from './continuous-layout';

test('logical offsets locate and update sections without scanning DOM nodes', () => {
  const index = new ContinuousOffsetIndex([100, 200, 300, 400]);
  assert.equal(index.total(), 1_000);
  assert.equal(index.prefix(2), 300);
  assert.equal(index.range(1, 3), 500);
  assert.equal(index.indexAtOffset(0), 0);
  assert.equal(index.indexAtOffset(99), 0);
  assert.equal(index.indexAtOffset(100), 1);
  assert.equal(index.indexAtOffset(999), 3);

  index.set(1, 500);
  assert.equal(index.total(), 1_300);
  assert.equal(index.indexAtOffset(599), 1);
  assert.equal(index.indexAtOffset(600), 2);
});

test('ten thousand logical sections use a bounded set of aggregate placeholder ranges', () => {
  const ranges = continuousPlaceholderRanges(10_000);
  assert.equal(ranges.length, 40);
  assert.deepEqual(ranges[0], { start: 0, end: 256 });
  assert.deepEqual(ranges.at(-1), { start: 9_984, end: 10_000 });
});

test('the reading line selects the stable item crossing one quarter of the viewport', () => {
  const items = [
    { offsetTop: 0, offsetHeight: 600 },
    { offsetTop: 600, offsetHeight: 800 },
    { offsetTop: 1400, offsetHeight: 700 }
  ];
  assert.equal(continuousItemAtReadingLine(items, 0, 800), 0);
  assert.equal(continuousItemAtReadingLine(items, 500, 800), 1);
  assert.equal(continuousItemAtReadingLine(items, 1800, 800), 2);
});

test('placeholder estimates are bounded for empty and very large sections', () => {
  assert.equal(estimatedContinuousHeight(undefined, 600), 480);
  assert.equal(estimatedContinuousHeight(1_000_000, 600), 4_800);
});

test('stable item keys restore the same viewport anchor after an earlier slot changes size', () => {
  const root = { scrollTop: 500, clientHeight: 800 } as HTMLElement;
  const first = { offsetTop: 0, offsetHeight: 600, dataset: { key: 'first' } } as unknown as HTMLElement;
  const second = { offsetTop: 600, offsetHeight: 700, dataset: { key: 'second' } } as unknown as HTMLElement;
  const items = [first, second];
  const anchor = captureContinuousAnchor(root, items, (item) => item.dataset.key);
  assert.deepEqual(anchor, { key: 'second', offset: 100 });

  Object.defineProperty(second, 'offsetTop', { configurable: true, value: 720 });
  restoreContinuousAnchor(root, items, anchor, (item) => item.dataset.key);
  assert.equal(root.scrollTop, 620);
});
