import assert from 'node:assert/strict';
import test from 'node:test';
import { publicationNavigationHref } from '@shuku/reader-core';

test('blocks legacy import and native-engine locators', () => {
  for (const [format, href] of [
    ['mobi', 'mobi-section:4'],
    ['mobi', 'filepos:1234'],
    ['azw3', 'kindle:pos:fid:0001:off:0000000000'],
    ['txt', 'txt-section:0'],
    ['txt', 'txt-chapter:0'],
    ['fb2', 'fb2-section:1']
  ] as const) assert.equal(publicationNavigationHref(format, href), null, href);
});

test('passes through Publication resource hrefs for every reflowable format', () => {
  for (const [format, href] of [
    ['epub', 'OEBPS/text00003.html'],
    ['epub', 'Text/all.xhtml#chapter-2'],
    ['mobi', 'part00000.html#chapter-1'],
    ['azw', 'text/part0001.html'],
    ['azw3', 'text/part0001.html#chapter-2'],
    ['prc', 'part00000.html'],
    ['fb2', 'fb2/section-0001.xhtml#fb2-node-000001'],
    ['txt', 'text/chapter-0002.xhtml#heading-000001']
  ] as const) assert.equal(publicationNavigationHref(format, href), href);
});

test('rejects non-publication and unsafe hrefs', () => {
  assert.equal(publicationNavigationHref('mobi', null), null);
  assert.equal(publicationNavigationHref('epub', '  '), null);
  assert.equal(publicationNavigationHref('fb2', '#fragment-only'), null);
  assert.equal(publicationNavigationHref('epub', 'https://example.com/chapter.xhtml'), null);
  assert.equal(publicationNavigationHref('epub', '../chapter.xhtml'), null);
  assert.equal(publicationNavigationHref('pdf', 'chapter.xhtml'), null);
});
