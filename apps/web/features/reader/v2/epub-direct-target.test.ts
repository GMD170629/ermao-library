import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveRequestedEpubHref } from './epub-direct-target';

test('EPUB direct targets are limited to exact bootstrap TOC entries', () => {
  const units = [
    { href: 'chapter.xhtml#first' },
    { href: 'chapter.xhtml#second' },
    { href: 'other.xhtml' }
  ];
  assert.equal(resolveRequestedEpubHref(units, 'CHAPTER.xhtml#second'), 'chapter.xhtml#second');
  assert.equal(resolveRequestedEpubHref(units, 'chapter.xhtml#missing'), null);
  assert.equal(resolveRequestedEpubHref(units, './other.xhtml'), 'other.xhtml');
  assert.equal(resolveRequestedEpubHref(units, 'https://example.com/chapter.xhtml'), null);
});

test('accepts a unique package-relative chapter suffix without weakening ownership checks', () => {
  const units = [{ href: 'OEBPS/Text/chapter.xhtml' }, { href: 'OEBPS/Text/other.xhtml' }];
  assert.equal(resolveRequestedEpubHref(units, 'chapter.xhtml'), 'OEBPS/Text/chapter.xhtml');
  assert.equal(resolveRequestedEpubHref([
    ...units,
    { href: 'Appendix/chapter.xhtml' }
  ], 'chapter.xhtml'), null);
});
