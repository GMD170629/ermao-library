import assert from 'node:assert/strict';
import test from 'node:test';
import { bookActionIds } from './book-action-menu';

test('restores the original manager menu without the library-hide action', () => {
  assert.deepEqual(bookActionIds({ canManage: true, mediaKind: 'EBOOK', hasDownload: true }), [
    'edit',
    'metadata',
    'upload-cover',
    'regenerate-cover',
    'download',
    'kindle',
    'delete'
  ]);
});

test('keeps member actions bounded to available reading operations', () => {
  assert.deepEqual(bookActionIds({ canManage: false, mediaKind: 'COMIC', hasDownload: true }), ['download']);
  assert.deepEqual(bookActionIds({ canManage: false, mediaKind: 'AUDIOBOOK', hasDownload: true }), []);
});
