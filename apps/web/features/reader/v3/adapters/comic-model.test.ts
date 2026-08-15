import assert from 'node:assert/strict';
import test from 'node:test';
import {
  comicAdjacentSpreadPage,
  comicCacheWindow,
  comicImageSizing,
  comicLastSpreadPage,
  comicNormalizePage,
  comicOrderedPages,
  comicPageSlotSizing,
  comicPageForProgress,
  comicPagePercent,
  comicPreloadWindow,
  comicSpreadPages,
  comicVisualPages
} from './comic-model';

test('double-page anchors pair the first page and align every later spread', () => {
  const pages = comicOrderedPages(6);
  assert.deepEqual(comicSpreadPages(pages, 0, 'double'), [0, 1]);
  assert.equal(comicAdjacentSpreadPage(pages, 0, 'double', 1), 2);
  assert.equal(comicNormalizePage(pages, 3, 'double'), 2);
  assert.equal(comicLastSpreadPage(pages, 'double'), 4);
  assert.deepEqual(comicSpreadPages(pages, 4, 'double'), [4, 5]);
});

test('comic spread is deterministic and only visual order changes for RTL', () => {
  const pages = comicOrderedPages(8);
  assert.deepEqual(comicSpreadPages(pages, 0, 'double'), [0, 1]);
  assert.deepEqual(comicSpreadPages(pages, 3, 'double'), [2, 3]);
  assert.deepEqual(comicVisualPages(pages, 4, 'double', 'ltr'), [4, 5]);
  assert.deepEqual(comicVisualPages(pages, 4, 'double', 'rtl'), [5, 4]);
});

test('comic cache is bounded to the current and adjacent spreads', () => {
  const pages = comicOrderedPages(12);
  assert.deepEqual(comicCacheWindow(pages, 5, 'single'), [4, 5, 6]);
  assert.deepEqual(comicCacheWindow(pages, 5, 'double'), [2, 3, 4, 5, 6, 7]);
  assert.deepEqual(comicPreloadWindow(pages, 5, 'single'), [6, 4]);
  assert.deepEqual(comicPreloadWindow(pages, 5, 'double'), [6, 7, 2, 3]);
});

test('double-page mode leaves only an unmatched final page single', () => {
  const pages = comicOrderedPages(5);
  assert.deepEqual(comicSpreadPages(pages, 4, 'double'), [4]);
  assert.equal(comicLastSpreadPage(pages, 'double'), 4);
});

test('cover-single pairing keeps the cover alone and pairs later pages', () => {
  const pages = comicOrderedPages(7);
  assert.deepEqual(comicSpreadPages(pages, 0, 'double', 'cover-single'), [0]);
  assert.deepEqual(comicSpreadPages(pages, 1, 'double', 'cover-single'), [1, 2]);
  assert.equal(comicNormalizePage(pages, 2, 'double', 'cover-single'), 1);
  assert.equal(comicAdjacentSpreadPage(pages, 0, 'double', 1, 'cover-single'), 1);
  assert.equal(comicLastSpreadPage(pages, 'double', 'cover-single'), 5);
});

test('comic page slots and default width fit stay inside the reading area', () => {
  assert.deepEqual(comicPageSlotSizing('single'), { flex: '0 1 100%', maxWidth: '100%', width: '100%' });
  assert.deepEqual(comicPageSlotSizing('double'), { flex: '1 1 50%', maxWidth: '50%', width: '50%' });
  assert.deepEqual(comicImageSizing('width'), {
    display: 'block',
    height: 'auto',
    maxHeight: '100%',
    maxWidth: '100%',
    objectFit: 'contain',
    width: '100%'
  });
  assert.deepEqual(comicImageSizing('width', 'double'), {
    display: 'block',
    height: '100%',
    maxHeight: '100%',
    maxWidth: '100%',
    objectFit: 'contain',
    width: 'auto'
  });
});

test('comic progress maps to a stable zero-based page', () => {
  const pages = comicOrderedPages(9);
  assert.equal(comicPageForProgress(0, pages), 0);
  assert.equal(comicPageForProgress(0.5, pages), 4);
  assert.equal(comicPageForProgress(1, pages), 8);
  assert.equal(comicPagePercent(0, [0]), 100);
});

test('comic progress follows the last visible page in double-page mode', () => {
  const evenPages = comicOrderedPages(10);
  assert.equal(comicPagePercent(8, evenPages, 'single'), (8 / 9) * 100);
  assert.equal(comicPagePercent(8, evenPages, 'double'), 100);
  assert.equal(comicPagePercent(4, evenPages, 'double'), (5 / 9) * 100);

  const oddPages = comicOrderedPages(9);
  assert.equal(comicPagePercent(6, oddPages, 'double'), 87.5);
  assert.equal(comicPagePercent(8, oddPages, 'double'), 100);
});
