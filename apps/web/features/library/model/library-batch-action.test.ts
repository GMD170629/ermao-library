import assert from 'node:assert/strict';
import test from 'node:test';
import { canUseLibraryBatchAction, type LibraryBatchAction } from './library-batch-action';

const actions: LibraryBatchAction[] = [
  'metadata',
  'find_replace',
  'shelves',
  'reading_status',
  'covers',
  'delete'
];

test('system managers can use every batch action including delete', () => {
  assert.deepEqual(
    actions.filter((action) => canUseLibraryBatchAction(action, true)),
    actions
  );
});

test('members never receive the destructive batch delete action', () => {
  assert.deepEqual(
    actions.filter((action) => canUseLibraryBatchAction(action, false)),
    ['shelves', 'reading_status']
  );
});
