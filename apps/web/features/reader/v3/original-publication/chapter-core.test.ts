import assert from 'node:assert/strict';
import test from 'node:test';
import { chapterEntriesToToc, type ChapterEntry } from './chapter-core';

function entry(value: Partial<ChapterEntry> & Pick<ChapterEntry, 'index' | 'key' | 'title'>): ChapterEntry {
  return {
    index: value.index,
    parentIndex: value.parentIndex ?? null,
    navigable: value.navigable ?? true,
    key: value.key,
    title: value.title,
    href: value.href === undefined ? `text/chapter-${String(value.index + 1).padStart(4, '0')}.xhtml#heading-000001` : value.href,
    sourceStart: value.sourceStart ?? 0,
    sourceEnd: value.sourceEnd ?? 1,
    contentStart: value.contentStart ?? 1
  };
}

test('chapter core tree projection keeps core keys, preorder and nesting', () => {
  assert.deepEqual(chapterEntriesToToc([
    entry({ index: 0, key: 'chapter-0', title: 'Part I', href: null, navigable: false }),
    entry({ index: 1, key: 'chapter-1', title: 'Chapter 1', parentIndex: 0 }),
    entry({ index: 2, key: 'chapter-2', title: 'Section 1.1', parentIndex: 1 })
  ]), [{
    href: null,
    title: 'Part I',
    navigationKey: 'chapter-0',
    children: [{
      href: 'text/chapter-0002.xhtml#heading-000001',
      title: 'Chapter 1',
      navigationKey: 'chapter-1',
      children: [{
        href: 'text/chapter-0003.xhtml#heading-000001',
        title: 'Section 1.1',
        navigationKey: 'chapter-2'
      }]
    }]
  }]);
});

test('chapter core tree projection rejects an invalid parent instead of reinterpreting it', () => {
  assert.throws(
    () => chapterEntriesToToc([
      entry({ index: 0, key: 'chapter-0', title: 'Orphan', parentIndex: 99 })
    ]),
    /CHAPTER_RESULT_TREE_INVALID/
  );
});
