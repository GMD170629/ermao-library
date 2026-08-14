import assert from 'node:assert/strict';
import test from 'node:test';
import {
  chapterDeepLinkHref,
  hasEbookChapterNavigation,
  isReflowableEbookFormat
} from './ebook-chapter-navigation';

test('isReflowableEbookFormat accepts known reflowable ebook formats', () => {
  for (const format of ['EPUB', 'MOBI', 'AZW', 'AZW3', 'PRC', 'FB2', 'TXT'] as const) {
    assert.equal(isReflowableEbookFormat(format), true);
  }
});

test('isReflowableEbookFormat rejects comic, pdf, audio, and unknown values', () => {
  for (const format of ['COMIC', 'PDF', 'AUDIO', '', null, undefined, 'DOCX']) {
    assert.equal(isReflowableEbookFormat(format), false);
  }
});

test('hasEbookChapterNavigation follows format across classified media tabs', () => {
  assert.equal(hasEbookChapterNavigation('EBOOK', 'MOBI'), true);
  assert.equal(hasEbookChapterNavigation('EBOOK', 'EPUB'), true);
  assert.equal(hasEbookChapterNavigation('EBOOK', 'TXT'), true);
  assert.equal(hasEbookChapterNavigation('EBOOK', 'FB2'), true);
  assert.equal(hasEbookChapterNavigation('STRUCTURE', 'MOBI'), false);
  assert.equal(hasEbookChapterNavigation('COMIC', 'EPUB'), true);
  assert.equal(hasEbookChapterNavigation('AUDIOBOOK', 'EPUB'), true);
  assert.equal(hasEbookChapterNavigation('EBOOK', 'PDF'), false);
  assert.equal(hasEbookChapterNavigation('EBOOK', null), false);
});

test('chapterDeepLinkHref keeps EPUB hrefs including fragments', () => {
  assert.equal(chapterDeepLinkHref('EPUB', 'Text/ch1.xhtml'), 'Text/ch1.xhtml');
  assert.equal(chapterDeepLinkHref('EPUB', 'Text/all.xhtml#section-2'), 'Text/all.xhtml#section-2');
});

test('chapterDeepLinkHref keeps Publication-generated TXT and FB2 resource targets', () => {
  assert.equal(
    chapterDeepLinkHref('TXT', 'text/chapter-0002.xhtml#heading-000001'),
    'text/chapter-0002.xhtml#heading-000001'
  );
  assert.equal(
    chapterDeepLinkHref('FB2', 'fb2/section-0001.xhtml#fb2-node-000001'),
    'fb2/section-0001.xhtml#fb2-node-000001'
  );
});

test('chapterDeepLinkHref keeps Publication resources and drops every legacy locator family', () => {
  assert.equal(chapterDeepLinkHref('MOBI', 'part00000.html#chapter-3'), 'part00000.html#chapter-3');
  assert.equal(chapterDeepLinkHref('AZW3', 'text/part0001.html#chapter-1'), 'text/part0001.html#chapter-1');
  for (const [format, href] of [
    ['MOBI', 'filepos:0000015808'],
    ['AZW3', 'kindle:pos:fid:0001:off:000000000A'],
    ['MOBI', 'mobi-section:3'],
    ['TXT', 'txt-section:1'],
    ['TXT', 'txt-chapter:1'],
    ['FB2', 'fb2-section:0']
  ] as const) assert.equal(chapterDeepLinkHref(format, href), null, href);
  assert.equal(chapterDeepLinkHref('FB2', '#fragment-only'), null);
  assert.equal(chapterDeepLinkHref('EPUB', 'https://example.com/chapter.xhtml'), null);
  assert.equal(chapterDeepLinkHref('MOBI', null), null);
  assert.equal(chapterDeepLinkHref('EPUB', '  '), null);
});
