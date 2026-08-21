import assert from 'node:assert/strict';
import test from 'node:test';
import { bookActionIds } from './book-action-menu';

test('keeps directory-owned structure out of the manager menu', () => {
  assert.deepEqual(bookActionIds({ canManage: true, kindleSendAvailable: true }), [
    'edit',
    'metadata',
    'upload-cover',
    'regenerate-cover',
    'kindle'
  ]);
});

test('keeps only supported member actions in the manager menu', () => {
  assert.deepEqual(bookActionIds({ canManage: false, kindleSendAvailable: false }), []);
  assert.deepEqual(bookActionIds({ canManage: false, kindleSendAvailable: true }), ['kindle']);
});
