import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveRequestedPublicationHref } from './publication-direct-target';

test('direct targets are limited to exact bootstrap Publication TOC entries', () => {
  const units = [
    { href: 'chapter.xhtml#first' },
    { href: 'chapter.xhtml#second' },
    { href: 'text/chapter-0002.xhtml#heading-000001' },
    { href: 'fb2/section-0001.xhtml#fb2-node-000001' },
    { href: 'other.xhtml' }
  ];
  assert.equal(resolveRequestedPublicationHref(units, 'CHAPTER.xhtml#second'), 'chapter.xhtml#second');
  assert.equal(
    resolveRequestedPublicationHref(units, 'text/chapter-0002.xhtml#heading-000001'),
    'text/chapter-0002.xhtml#heading-000001'
  );
  assert.equal(
    resolveRequestedPublicationHref(units, 'fb2/section-0001.xhtml#fb2-node-000001'),
    'fb2/section-0001.xhtml#fb2-node-000001'
  );
  assert.equal(resolveRequestedPublicationHref(units, 'chapter.xhtml#missing'), null);
  assert.equal(resolveRequestedPublicationHref(units, './other.xhtml'), 'other.xhtml');
  assert.equal(resolveRequestedPublicationHref(units, 'https://example.com/chapter.xhtml'), null);
});
