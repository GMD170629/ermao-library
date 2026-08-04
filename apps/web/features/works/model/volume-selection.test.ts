import assert from 'node:assert/strict';
import test from 'node:test';
import { applyVolumeSelectionMode, contextVolumeSelection, pruneVolumeSelection, toggleVolumeSelection } from './volume-selection';

test('toggles ctrl-style selection without replacing other volumes', () => {
  assert.deepEqual([...toggleVolumeSelection(new Set(['one']), 'two')], ['one', 'two']);
  assert.deepEqual([...toggleVolumeSelection(new Set(['one', 'two']), 'one')], ['two']);
});

test('applies one drag mode to every visited volume', () => {
  assert.deepEqual([...applyVolumeSelectionMode(new Set(['one']), 'two', 'select')], ['one', 'two']);
  assert.deepEqual([...applyVolumeSelectionMode(new Set(['one', 'two']), 'one', 'deselect')], ['two']);
});

test('right click preserves an existing group and replaces an outside target', () => {
  assert.deepEqual([...contextVolumeSelection(new Set(['one', 'two']), 'two')], ['one', 'two']);
  assert.deepEqual([...contextVolumeSelection(new Set(['one', 'two']), 'three')], ['three']);
});

test('prunes volumes that leave the active media tab', () => {
  assert.deepEqual([...pruneVolumeSelection(new Set(['one', 'two']), ['two', 'three'])], ['two']);
});
