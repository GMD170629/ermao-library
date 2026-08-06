import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveChapterReadingStates } from './chapter-reading-state';

const anchoredChapters = [
  { href: 'Text/all.xhtml#chapter-1', sortOrder: 1 },
  { href: 'Text/all.xhtml#chapter-2', sortOrder: 2 },
  { href: 'Text/all.xhtml#chapter-3', sortOrder: 3 }
];

test('only the exact anchored chapter is current when chapters share one XHTML file', () => {
  assert.deepEqual(
    resolveChapterReadingStates(anchoredChapters, 'text/all.xhtml#chapter-2', 2, 42),
    ['read', 'current', 'unread']
  );
});

test('uses stored sort order for a page that does not contain the current chapter', () => {
  const laterPage = [
    { href: 'chapter-11.xhtml', sortOrder: 11 },
    { href: 'chapter-12.xhtml', sortOrder: 12 }
  ];
  assert.deepEqual(resolveChapterReadingStates(laterPage, 'chapter-3.xhtml', 3, 20), ['unread', 'unread']);
});

test('does not guess among ambiguous resource-only chapter anchors', () => {
  assert.deepEqual(
    resolveChapterReadingStates(anchoredChapters, 'Text/all.xhtml', null, 20),
    ['unread', 'unread', 'unread']
  );
});

test('marks every chapter including the final current chapter read when the book is finished', () => {
  assert.deepEqual(
    resolveChapterReadingStates(anchoredChapters, 'Text/all.xhtml#chapter-3', 3, 100),
    ['read', 'read', 'read']
  );
});

test('does not estimate chapters from percent when progress has no exact navigation', () => {
  const mobiChapters = Array.from({ length: 10 }, (_, index) => ({
    href: `mobi-section:${index}`,
    sortOrder: index
  }));
  assert.deepEqual(
    resolveChapterReadingStates(mobiChapters, null, null, 11, { total: 10, page: 1, pageSize: 10 }),
    ['unread', 'unread', 'unread', 'unread', 'unread', 'unread', 'unread', 'unread', 'unread', 'unread']
  );
});

test('does not derive paginated chapter state from overall percent', () => {
  const pageTwo = [
    { href: 'mobi-section:5', sortOrder: 5 },
    { href: 'mobi-section:6', sortOrder: 6 }
  ];
  assert.deepEqual(
    resolveChapterReadingStates(pageTwo, null, null, 45, { total: 10, page: 2, pageSize: 5 }),
    ['unread', 'unread']
  );
  assert.deepEqual(
    resolveChapterReadingStates(pageTwo, null, null, 55, { total: 10, page: 2, pageSize: 5 }),
    ['unread', 'unread']
  );
});

test('uses an exact foliate TOC index across paginated chapter rows', () => {
  const pageTwo = [
    { href: 'chapter-6.xhtml', sortOrder: 6 },
    { href: 'chapter-7.xhtml', sortOrder: 7 }
  ];
  assert.deepEqual(
    resolveChapterReadingStates(pageTwo, null, null, 55, {
      total: 10,
      page: 2,
      pageSize: 5,
      currentIndex: 5
    }),
    ['current', 'unread']
  );
});

test('uses the exact Reader v3 chapter index across pages before and after the current chapter', () => {
  const firstPage = Array.from({ length: 5 }, (_, index) => ({
    href: `txt-section:${index}`,
    sortOrder: index
  }));
  const laterPage = Array.from({ length: 5 }, (_, index) => ({
    href: `txt-section:${index + 10}`,
    sortOrder: index + 10
  }));

  assert.deepEqual(
    resolveChapterReadingStates(firstPage, null, null, 0.2, { total: 20, page: 1, pageSize: 5, currentIndex: 9 }),
    ['read', 'read', 'read', 'read', 'read']
  );
  assert.deepEqual(
    resolveChapterReadingStates(laterPage, null, null, 0.2, { total: 20, page: 3, pageSize: 5, currentIndex: 9 }),
    ['unread', 'unread', 'unread', 'unread', 'unread']
  );
});

test('does not use percent fallback when an unresolved href was provided', () => {
  assert.deepEqual(
    resolveChapterReadingStates(anchoredChapters, 'Text/all.xhtml', null, 50),
    ['unread', 'unread', 'unread']
  );
});
