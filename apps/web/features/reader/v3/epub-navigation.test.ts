import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveActiveEpubNavigationIndex, resolveEpubSpineIntervalHref } from './epub-navigation';

const anchored = [
  { href: 'Text/all.xhtml#first' },
  { href: 'Text/all.xhtml#second' },
  { href: 'Text/all.xhtml#third' }
];

test('matches the exact TOC fragment in a multi-chapter spine resource', () => {
  assert.equal(resolveActiveEpubNavigationIndex(anchored, 'text/all.xhtml#second', 0), 1);
  assert.equal(resolveActiveEpubNavigationIndex(anchored, 'Text/all.xhtml#third', 0), 2);
});

test('does not guess the first chapter when a resource has multiple anchors', () => {
  assert.equal(resolveActiveEpubNavigationIndex(anchored, 'Text/all.xhtml', 0), null);
});

test('selects a resource-only total contents entry when the rendition reports its heading fragment', () => {
  assert.equal(resolveActiveEpubNavigationIndex(
    [{ href: 'text/part0000.html' }, { href: 'text/part0001.html#chapter' }],
    'Text/part0000.html#contents-heading',
    1
  ), 0);
});

test('allows resource and real spine fallbacks only when they are unambiguous', () => {
  assert.equal(resolveActiveEpubNavigationIndex([{ href: 'one.xhtml' }], 'one.xhtml', null), 0);
  assert.equal(resolveActiveEpubNavigationIndex([{ href: 'one.xhtml', sectionIndex: 4 }], null, 4), 0);
});

test('maps EPUB-authored contents and split resources to the preceding TOC interval', () => {
  const toc = [
    { href: 'text/part0000.html', sectionIndex: 0 },
    { href: 'text/part0011.html', sectionIndex: 11 },
    { href: 'text/part0013.html', sectionIndex: 13 }
  ];
  assert.equal(resolveEpubSpineIntervalHref(toc, 12, 'text/part0012.html'), 'text/part0011.html');
  assert.equal(resolveEpubSpineIntervalHref(toc, 14, 'text/part0013_split_001.html'), 'text/part0013.html');
});

test('leaves an exact TOC spine alone for fragment-aware matching', () => {
  const toc = [
    { href: 'text/all.xhtml#first', sectionIndex: 3 },
    { href: 'text/all.xhtml#second', sectionIndex: 3 }
  ];
  assert.equal(resolveEpubSpineIntervalHref(toc, 3, 'text/all.xhtml'), 'text/all.xhtml');
});
