import assert from 'node:assert/strict';
import test from 'node:test';
import { canUseLibraryBatchAction, type LibraryBatchAction } from './library-batch-action';

const actions: LibraryBatchAction[] = [
  'metadata',
  'find_replace',
  'shelves',
  'reading_status',
  'covers'
];

test('system managers can use every metadata and presentation batch action', () => {
  assert.deepEqual(
    actions.filter((action) => canUseLibraryBatchAction(action, true)),
    actions
  );
});

test('members receive only their personal-state actions', () => {
  assert.deepEqual(
    actions.filter((action) => canUseLibraryBatchAction(action, false)),
    ['shelves', 'reading_status']
  );
});
