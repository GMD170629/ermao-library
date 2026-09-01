import assert from 'node:assert/strict';
import test from 'node:test';
import fixture from '../../../../../../packages/reader-contracts/fixtures/comic-reader-semantics-v1.json';
import {
  comicAdjacentSpreadPage,
  comicCacheWindow,
  comicNormalizePage,
  comicOrderedPages,
  comicPageForProgress,
  comicPagePercent,
  comicPreloadWindow,
  comicSpreadPages,
  comicVisualPages,
  type ComicPairingPolicy
} from './comic-model';

function fixtureSpreadMode(value: string): 'single' | 'double' {
  if (value === 'single' || value === 'double') return value;
  throw new Error(`Unsupported comic spread fixture value: ${value}`);
}

function fixtureDirection(value: string): 'ltr' | 'rtl' {
  if (value === 'ltr' || value === 'rtl') return value;
  throw new Error(`Unsupported comic direction fixture value: ${value}`);
}

test('Web comic semantics conform to the canonical cross-client fixture', () => {
  assert.equal(fixture.schemaVersion, 1);
  for (const scenario of fixture.cases) {
    const pages = comicOrderedPages(scenario.pageCount);
    const mode = scenario.preferences.flow === 'paginated'
      ? fixtureSpreadMode(scenario.preferences.spreadMode)
      : 'single';
    const pairing: ComicPairingPolicy = scenario.preferences.coverSingle
      ? 'cover-single'
      : 'paired-from-first';
    const anchor = comicNormalizePage(pages, scenario.currentPageIndex, mode, pairing);
    const previous = comicAdjacentSpreadPage(pages, anchor, mode, -1, pairing);
    const next = comicAdjacentSpreadPage(pages, anchor, mode, 1, pairing);
    const effectivePageWidth = scenario.viewport.wide
      ? Math.min(scenario.preferences.pageWidth, scenario.viewport.width)
      : scenario.viewport.width;
    const pageGap = scenario.preferences.flow === 'paginated' && mode === 'double'
      ? scenario.preferences.pageGap
      : 0;

    assert.equal(mode, scenario.expected.spreadMode, `${scenario.id}: spread mode`);
    assert.equal(pairing, scenario.expected.pairingPolicy, `${scenario.id}: pairing`);
    assert.equal(scenario.currentPageIndex, scenario.expected.currentPageIndex, `${scenario.id}: current page`);
    assert.equal(anchor, scenario.expected.anchorPageIndex, `${scenario.id}: anchor`);
    assert.deepEqual(comicSpreadPages(pages, anchor, mode, pairing), scenario.expected.logicalPageIndices, `${scenario.id}: logical pages`);
    assert.deepEqual(
      comicVisualPages(pages, anchor, mode, fixtureDirection(scenario.preferences.direction), pairing),
      scenario.expected.visualPageIndices,
      `${scenario.id}: visual pages`
    );
    assert.equal(previous === anchor ? null : previous, scenario.expected.previousAnchor, `${scenario.id}: previous`);
    assert.equal(next === anchor ? null : next, scenario.expected.nextAnchor, `${scenario.id}: next`);
    assert.ok(
      Math.abs(comicPagePercent(anchor, pages, mode, pairing) / 100 - scenario.expected.progress) < 1e-9,
      `${scenario.id}: progress`
    );
    assert.deepEqual(comicCacheWindow(pages, anchor, mode, pairing), scenario.expected.cachePageIndices, `${scenario.id}: cache`);
    assert.deepEqual(comicPreloadWindow(pages, anchor, mode, pairing), scenario.expected.preloadPageIndices, `${scenario.id}: preload`);
    assert.equal(effectivePageWidth, scenario.expected.effectivePageWidth, `${scenario.id}: effective width`);
    assert.equal(pageGap, scenario.expected.pageGap, `${scenario.id}: gap`);
    const effectiveImageFit = scenario.preferences.flow === 'scrolled' ? 'width' : scenario.preferences.imageFit;
    assert.equal(effectiveImageFit, scenario.expected.effectiveImageFit, `${scenario.id}: effective image fit`);
    assert.equal(
      scenario.preferences.pageTurnAnimation === 'slide' && !('reducedMotion' in scenario && scenario.reducedMotion),
      scenario.expected.animatePageTurn,
      `${scenario.id}: animation`
    );
  }
});

test('Web progress rounding conforms to the canonical cross-client fixture', () => {
  for (const scenario of fixture.progressCases) {
    assert.equal(
      comicPageForProgress(scenario.progression, comicOrderedPages(scenario.pageCount)),
      scenario.pageIndex
    );
  }
});
