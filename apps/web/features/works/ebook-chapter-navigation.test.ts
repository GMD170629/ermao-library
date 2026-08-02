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

test('hasEbookChapterNavigation requires EBOOK tab and a reflowable format', () => {
  assert.equal(hasEbookChapterNavigation('EBOOK', 'MOBI'), true);
  assert.equal(hasEbookChapterNavigation('EBOOK', 'EPUB'), true);
  assert.equal(hasEbookChapterNavigation('EBOOK', 'TXT'), true);
  assert.equal(hasEbookChapterNavigation('STRUCTURE', 'MOBI'), false);
  assert.equal(hasEbookChapterNavigation('COMIC', 'EPUB'), false);
  assert.equal(hasEbookChapterNavigation('EBOOK', 'PDF'), false);
  assert.equal(hasEbookChapterNavigation('EBOOK', null), false);
});

test('chapterDeepLinkHref keeps EPUB hrefs including fragments', () => {
  assert.equal(chapterDeepLinkHref('EPUB', 'Text/ch1.xhtml'), 'Text/ch1.xhtml');
  assert.equal(chapterDeepLinkHref('EPUB', 'Text/all.xhtml#section-2'), 'Text/all.xhtml#section-2');
});

test('chapterDeepLinkHref keeps exact FB2 and TXT engine targets', () => {
  assert.equal(chapterDeepLinkHref('FB2', '2#1'), '2#1');
  assert.equal(chapterDeepLinkHref('TXT', 'txt-section:1'), 'txt-section:1');
  assert.equal(chapterDeepLinkHref('FB2', 'fb2-section:0'), null);
  assert.equal(chapterDeepLinkHref('FB2', '#'), null);
});

test('chapterDeepLinkHref keeps native Kindle targets and drops legacy pseudo hrefs', () => {
  assert.equal(chapterDeepLinkHref('MOBI', 'filepos:0000015808'), 'filepos:0000015808');
  assert.equal(chapterDeepLinkHref('AZW3', 'kindle:pos:fid:0001:off:000000000A'), 'kindle:pos:fid:0001:off:000000000A');
  assert.equal(chapterDeepLinkHref('MOBI', 'mobi-section:3'), null);
  assert.equal(chapterDeepLinkHref('AZW3', 'mobi-section:0'), null);
  assert.equal(chapterDeepLinkHref('TXT', 'txt-chapter:1'), null);
  assert.equal(chapterDeepLinkHref('MOBI', null), null);
  assert.equal(chapterDeepLinkHref('EPUB', '  '), null);
});
