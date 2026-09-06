import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveRequestedChapterHref } from './publication-direct-target';

test('resolves a local chapter key and fragment, never a group or unknown key', () => {
  const entries = [{ id: 'group', navigationKey: 'chapter-0', label: 'Part', children: [
    { id: 'first', navigationKey: 'chapter-1', label: 'A', href: 'body.xhtml#a' },
    { id: 'second', navigationKey: 'chapter-2', label: 'B', href: 'body.xhtml#b' }
  ] }];
  assert.equal(resolveRequestedChapterHref(entries, 'chapter-2'), 'body.xhtml#b');
  assert.equal(resolveRequestedChapterHref(entries, 'chapter-0'), null);
  assert.equal(resolveRequestedChapterHref(entries, 'unknown'), null);
  assert.equal(resolveRequestedChapterHref([], 'chapter-2'), null);
});
