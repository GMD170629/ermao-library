import assert from 'node:assert/strict';
import test from 'node:test';
import { bookActionIds } from './book-action-menu';

test('restores the original manager menu without the library-hide action', () => {
  assert.deepEqual(bookActionIds({ canManage: true, hasDownload: true, kindleSendAvailable: true }), [
    'edit',
    'metadata',
    'upload-cover',
    'regenerate-cover',
    'download',
    'kindle',
    'delete'
  ]);
});

test('derives member actions from concrete file capabilities', () => {
  assert.deepEqual(bookActionIds({ canManage: false, hasDownload: true, kindleSendAvailable: false }), ['download']);
  assert.deepEqual(bookActionIds({ canManage: false, hasDownload: false, kindleSendAvailable: true }), ['kindle']);
});
