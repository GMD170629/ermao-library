import assert from 'node:assert/strict';
import test from 'node:test';
import { chapterPresentationSortOrder, resolveChapterReadingStates } from './chapter-reading-state';
const chapters = [
  { href: null, sortOrder: 0 },
  { href: 'all.xhtml#first', sortOrder: 1 },
  { href: 'all.xhtml#second', sortOrder: 2 },
  { href: 'all.xhtml#third', sortOrder: 3 }
];
test('only the server-resolved chapter is current and groups remain unmarked', () => {
  assert.deepEqual(resolveChapterReadingStates(chapters, 2, 42), ['unread', 'read', 'current', 'unread']);
});
test('does not infer chapter from percent when the engine reports no exact chapter', () => {
  assert.deepEqual(resolveChapterReadingStates(chapters, null, 99), ['unread', 'unread', 'unread', 'unread']);
});
test('global preorder works for paginated subsets without page-index arithmetic', () => {
  assert.deepEqual(resolveChapterReadingStates(chapters.slice(2), 1, 25), ['unread', 'unread']);
  assert.deepEqual(resolveChapterReadingStates(chapters.slice(1, 3), 3, 25), ['read', 'read']);
});
test('finished resource marks navigable chapters read', () => {
  assert.deepEqual(resolveChapterReadingStates(chapters, 3, 100), ['unread', 'read', 'read', 'read']);
});

test('local current chapter must carry the same core key and preorder index', () => {
  assert.equal(chapterPresentationSortOrder({ navigationKey: 'chapter-4', index: 4 }), 4);
  assert.equal(chapterPresentationSortOrder({ navigationKey: 'chapter-4', index: 1 }), null);
  assert.equal(chapterPresentationSortOrder({ navigationKey: null, index: 4 }), null);
});
