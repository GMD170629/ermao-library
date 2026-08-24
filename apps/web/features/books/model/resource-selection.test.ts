import assert from 'node:assert/strict';
import test from 'node:test';
import { applyResourceSelectionMode, contextResourceSelection, pruneResourceSelection, toggleResourceSelection } from './resource-selection';

test('toggles ctrl-style selection without replacing other resources', () => {
  assert.deepEqual([...toggleResourceSelection(new Set(['one']), 'two')], ['one', 'two']);
  assert.deepEqual([...toggleResourceSelection(new Set(['one', 'two']), 'one')], ['two']);
});

test('applies one drag mode to every visited resource', () => {
  assert.deepEqual([...applyResourceSelectionMode(new Set(['one']), 'two', 'select')], ['one', 'two']);
  assert.deepEqual([...applyResourceSelectionMode(new Set(['one', 'two']), 'one', 'deselect')], ['two']);
});

test('right click preserves an existing group and replaces an outside target', () => {
  assert.deepEqual([...contextResourceSelection(new Set(['one', 'two']), 'two')], ['one', 'two']);
  assert.deepEqual([...contextResourceSelection(new Set(['one', 'two']), 'three')], ['three']);
});

test('prunes resources that are no longer available', () => {
  assert.deepEqual([...pruneResourceSelection(new Set(['one', 'two']), ['two', 'three'])], ['two']);
});
