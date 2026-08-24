import assert from 'node:assert/strict';
import test from 'node:test';
import { readableResourceActionIds } from './readable-resource-action-menu';

test('returns the complete ordered resource menu for managers', () => {
  assert.deepEqual(
    readableResourceActionIds({ canManage: true, kindleSendAvailable: true }),
    ['edit', 'upload-cover', 'regenerate-cover', 'recognize', 'kindle', 'delete']
  );
});

test('keeps Kindle conditional and available to members', () => {
  assert.deepEqual(
    readableResourceActionIds({ canManage: true, kindleSendAvailable: false }),
    ['edit', 'upload-cover', 'regenerate-cover', 'recognize', 'delete']
  );
  assert.deepEqual(
    readableResourceActionIds({ canManage: false, kindleSendAvailable: true }),
    ['kindle']
  );
  assert.deepEqual(
    readableResourceActionIds({ canManage: false, kindleSendAvailable: false }),
    []
  );
});
