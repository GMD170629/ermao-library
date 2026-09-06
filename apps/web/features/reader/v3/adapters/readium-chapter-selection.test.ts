import assert from 'node:assert/strict';
import test from 'node:test';
import { currentReadiumChapter } from './readium-chapter-selection';

test('selects an exact nested fragment and leaves ambiguous resource-only positions unknown', () => {
  const entries = [{ id: 'part', navigationKey: 'chapter-0', label: 'Part', children: [
    { id: 'a', navigationKey: 'chapter-1', label: 'A', href: 'body.xhtml#a', index: 1 },
    { id: 'b', navigationKey: 'chapter-2', label: 'B', href: 'body.xhtml#b', index: 2 }
  ] }];
  assert.equal(currentReadiumChapter(entries, 'body.xhtml', ['b'])?.navigationKey, 'chapter-2');
  assert.equal(currentReadiumChapter(entries, 'body.xhtml#b', [])?.index, 2);
  assert.equal(currentReadiumChapter(entries, 'body.xhtml', []), null);
  assert.equal(currentReadiumChapter(entries, 'other.xhtml', []), null);
});
