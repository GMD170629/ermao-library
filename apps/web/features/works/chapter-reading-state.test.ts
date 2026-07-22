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
