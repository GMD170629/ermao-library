import assert from 'node:assert/strict';
import { test } from 'node:test';
import { comicPreloadPages, comicRetainedPages } from './comic-preload';

test('comicPreloadPages limits double-page preloading to the next spread', () => {
  const pages = Array.from({ length: 12 }, (_, index) => index + 1);

  assert.deepEqual(comicPreloadPages(pages, 7, 2), [9, 10]);
});

test('comicPreloadPages limits single-page preloading to two forward pages', () => {
  const pages = Array.from({ length: 12 }, (_, index) => index + 1);

  assert.deepEqual(comicPreloadPages(pages, 7, 1), [8, 9]);
});

test('comicPreloadPages falls back to previous pages near the end', () => {
  const pages = Array.from({ length: 12 }, (_, index) => index + 1);

  assert.deepEqual(comicPreloadPages(pages, 11, 2), [10, 9]);
});

test('comicPreloadPages follows the provided page order', () => {
  const pages = Array.from({ length: 12 }, (_, index) => 12 - index);

  assert.deepEqual(comicPreloadPages(pages, 7, 2), [5, 4]);
});

test('comicPreloadPages returns no candidates for an unknown current page', () => {
  const pages = Array.from({ length: 12 }, (_, index) => index + 1);

  assert.deepEqual(comicPreloadPages(pages, 99, 2), []);
});

test('comicRetainedPages keeps the adjacent overlap window for cache reuse', () => {
  const pages = Array.from({ length: 24 }, (_, index) => index + 1);

  assert.deepEqual(comicRetainedPages(pages, 15, 2), [13, 14, 15, 16, 17, 18]);
});
