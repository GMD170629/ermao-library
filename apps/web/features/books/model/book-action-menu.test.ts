import assert from 'node:assert/strict';
import test from 'node:test';
import { bookActionIds } from './book-action-menu';

test('keeps directory-owned structure out of the manager menu', () => {
  assert.deepEqual(bookActionIds({ canManage: true, hasDownload: true, kindleSendAvailable: true }), [
    'edit',
    'metadata',
    'upload-cover',
    'regenerate-cover',
    'download',
    'kindle'
  ]);
});

test('derives member actions from concrete file capabilities', () => {
  assert.deepEqual(bookActionIds({ canManage: false, hasDownload: true, kindleSendAvailable: false }), ['download']);
  assert.deepEqual(bookActionIds({ canManage: false, hasDownload: false, kindleSendAvailable: true }), ['kindle']);
});
