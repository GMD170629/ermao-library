import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_READER_PREFERENCES } from '@shuku/reader-core';
import { createEpubThemeSnapshot } from './epub-theme';

test('EPUB theme keeps vertical page spacing enforced after epub.js writes layout shorthands', () => {
  const paginated = createEpubThemeSnapshot(DEFAULT_READER_PREFERENCES);
  const scrolled = createEpubThemeSnapshot({
    ...DEFAULT_READER_PREFERENCES,
    epub: { ...DEFAULT_READER_PREFERENCES.epub, flow: 'scrolled' }
  });

  assert.match(paginated, /padding-top: clamp\(32px, 5vh, 64px\) !important/);
  assert.match(paginated, /padding-bottom: clamp\(32px, 5vh, 64px\) !important/);
  assert.match(paginated, /--shuku-reader-page-width: 1350px/);
  assert.match(paginated, /html \{\s+font-size: var\(--shuku-reader-font-size\) !important/);
  assert.match(scrolled, /padding-top: clamp\(28px, 4vh, 56px\) !important/);
  assert.match(scrolled, /scrollbar-width: none !important/);
  assert.match(scrolled, /::-webkit-scrollbar/);
  assert.doesNotMatch(paginated, /scrollbar-width: none/);
});

test('EPUB theme repaints the Foliate paginator background on the current page', () => {
  const snapshot = createEpubThemeSnapshot({
    ...DEFAULT_READER_PREFERENCES,
    appearance: { theme: 'black' }
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
