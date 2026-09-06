import assert from 'node:assert/strict';
import test from 'node:test';
import {
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

test('hasEbookChapterNavigation follows format', () => {
  assert.equal(hasEbookChapterNavigation('MOBI'), true);
  assert.equal(hasEbookChapterNavigation('EPUB'), true);
  assert.equal(hasEbookChapterNavigation('TXT'), true);
  assert.equal(hasEbookChapterNavigation('FB2'), true);
  assert.equal(hasEbookChapterNavigation('PDF'), false);
  assert.equal(hasEbookChapterNavigation(null), false);
});
