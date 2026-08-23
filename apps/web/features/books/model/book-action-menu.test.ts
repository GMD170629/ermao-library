import assert from 'node:assert/strict';
import test from 'node:test';
import { bookActionIds } from './book-action-menu';

test('offers regeneration only when the Book anchor owns a Resource', () => {
  assert.deepEqual(bookActionIds({ canManage: true, canRegenerateCover: true, kindleSendAvailable: true }), [
    'edit',
    'metadata',
    'upload-cover',
    'regenerate-cover',
    'kindle'
  ]);
  assert.deepEqual(bookActionIds({ canManage: true, canRegenerateCover: false, kindleSendAvailable: false }), [
    'edit',
    'metadata',
    'upload-cover'
  ]);
});

test('keeps only supported member actions in the manager menu', () => {
  assert.deepEqual(bookActionIds({ canManage: false, canRegenerateCover: true, kindleSendAvailable: false }), []);
  assert.deepEqual(bookActionIds({ canManage: false, canRegenerateCover: true, kindleSendAvailable: true }), ['kindle']);
});
