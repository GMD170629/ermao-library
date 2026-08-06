import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_READER_PREFERENCES } from '@shuku/reader-core';
import { createEpubThemeSnapshot, epubPageWidth, resolveEpubViewportLayout } from './epub-theme';

test('EPUB page width uses one bounded measure in paginated and scrolled layouts', () => {
  assert.equal(epubPageWidth(DEFAULT_READER_PREFERENCES), 1350);
  assert.equal(epubPageWidth({
    ...DEFAULT_READER_PREFERENCES,
    epub: { ...DEFAULT_READER_PREFERENCES.epub, pageWidth: 420 }
  }), 600);
  assert.equal(epubPageWidth({
    ...DEFAULT_READER_PREFERENCES,
    epub: { ...DEFAULT_READER_PREFERENCES.epub, pageWidth: 1800 }
  }), 1350);
});

test('EPUB theme keeps vertical page spacing enforced after epub.js writes layout shorthands', () => {
  const paginated = createEpubThemeSnapshot(DEFAULT_READER_PREFERENCES);
  const scrolled = createEpubThemeSnapshot({
    ...DEFAULT_READER_PREFERENCES,
    epub: { ...DEFAULT_READER_PREFERENCES.epub, flow: 'scrolled' }
  });

  assert.match(paginated, /--shuku-reader-padding-top: clamp\(32px, 5vh, 64px\)/);
  assert.match(paginated, /--shuku-reader-padding-bottom: clamp\(32px, 5vh, 64px\)/);
  assert.match(paginated, /padding-top: var\(--shuku-reader-padding-top\) !important/);
  assert.match(paginated, /padding-bottom: var\(--shuku-reader-padding-bottom\) !important/);
  assert.match(paginated, /--shuku-reader-page-width: 1350px/);
  assert.match(paginated, /html \{\s+font-size: var\(--shuku-reader-font-size\) !important/);
  assert.match(scrolled, /--shuku-reader-padding-top: clamp\(28px, 4vh, 56px\)/);
  assert.match(scrolled, /scrollbar-width: none !important/);
  assert.match(scrolled, /::-webkit-scrollbar/);
  assert.doesNotMatch(paginated, /scrollbar-width: none/);
});

test('EPUB theme uses the outer reader viewport profile instead of an iframe media query', () => {
  const compactLayout = resolveEpubViewportLayout(390);
  const regularLayout = resolveEpubViewportLayout(641);
  const paginated = createEpubThemeSnapshot(
    DEFAULT_READER_PREFERENCES,
    undefined,
    compactLayout
  );
  const scrolled = createEpubThemeSnapshot({
    ...DEFAULT_READER_PREFERENCES,
    epub: { ...DEFAULT_READER_PREFERENCES.epub, flow: 'scrolled' }
  }, undefined, compactLayout);

  assert.match(paginated, /--shuku-reader-padding-inline: 1em/);
  assert.match(paginated, /--shuku-reader-padding-top: clamp\(16px, 2\.5vh, 32px\)/);
  assert.match(scrolled, /--shuku-reader-padding-top: clamp\(14px, 2vh, 28px\)/);
  assert.doesNotMatch(paginated, /@media \(max-width: 640px\)/);
  assert.deepEqual(compactLayout, {
    compact: true,
    automaticColumnCount: 1,
    inlinePadding: '1em',
    paginatorGap: '0%',
    bottomInset: 'calc(var(--shuku-safe-area-bottom) + 10px)'
  });
  assert.deepEqual(regularLayout, {
    compact: false,
    automaticColumnCount: 1,
    inlinePadding: '24px',
    paginatorGap: '7%',
    bottomInset: '0px'
  });
});

test('EPUB theme applies V4 font weight, letter spacing, and responsive page margins', () => {
  const preferences = {
    ...DEFAULT_READER_PREFERENCES,
    epub: {
      ...DEFAULT_READER_PREFERENCES.epub,
      fontWeight: 700 as const,
      letterSpacing: 0.08 as const,
      pageMargin: 'wide' as const
    }
  };
  const compact = createEpubThemeSnapshot(preferences, undefined, resolveEpubViewportLayout(390));
  const desktop = createEpubThemeSnapshot(preferences, undefined, resolveEpubViewportLayout(1200));

  assert.match(compact, /--shuku-reader-font-weight: 700/);
  assert.match(compact, /--shuku-reader-letter-spacing: 0.08em/);
  assert.match(compact, /--shuku-reader-padding-inline: 1.5em/);
  assert.match(desktop, /--shuku-reader-padding-inline: 40px/);
  assert.equal(resolveEpubViewportLayout(1200).automaticColumnCount, 2);
});

test('EPUB theme repaints the Foliate paginator background on the current page', () => {
  const snapshot = createEpubThemeSnapshot({
    ...DEFAULT_READER_PREFERENCES,
    appearance: { ...DEFAULT_READER_PREFERENCES.appearance, theme: 'black' }
  });

  assert.match(snapshot, /--theme-bg-color: #000000/);
});

test('EPUB theme keeps the selected line height on the body while descendants inherit it', () => {
  const snapshot = createEpubThemeSnapshot({
    ...DEFAULT_READER_PREFERENCES,
    epub: { ...DEFAULT_READER_PREFERENCES.epub, lineHeight: 2.2 }
  });

  const bodySelector = 'body:is(#shuku-theme-guard#shuku-theme-guard#shuku-theme-guard, *)';
  const combinedSelector = bodySelector + ', ' + bodySelector + ' * {';
  const combinedStart = snapshot.indexOf(combinedSelector);
  const combinedRule = snapshot.slice(combinedStart, snapshot.indexOf('}', combinedStart));
  const inheritedStart = snapshot.indexOf(bodySelector + ' * {', combinedStart + combinedSelector.length);
  const inheritedRule = snapshot.slice(inheritedStart, snapshot.indexOf('}', inheritedStart));

  assert.ok(combinedStart >= 0);
  assert.ok(inheritedStart >= 0);
  assert.ok(snapshot.includes('--shuku-reader-line-height: 2.2;'));
  assert.ok(snapshot.includes('line-height: var(--shuku-reader-line-height) !important;'));
  assert.equal(combinedRule.includes('line-height'), false);
  assert.ok(inheritedRule.includes('line-height: inherit !important;'));
});

test('EPUB chapter theme uses the session font URL without blocking the first paint', () => {
  const snapshot = createEpubThemeSnapshot(DEFAULT_READER_PREFERENCES, {
    source: 'embedded',
    stack: '"Shuku Reader Sans", sans-serif',
    embedded: { family: 'Shuku Reader Sans', url: 'blob:reader-font-session' }
  });

  assert.match(snapshot, /src: url\("blob:reader-font-session"\)/);
  assert.match(snapshot, /font-display: swap/);
  assert.doesNotMatch(snapshot, /font-display: block/);
  assert.doesNotMatch(snapshot, /\/fonts\/reader\//);
});
