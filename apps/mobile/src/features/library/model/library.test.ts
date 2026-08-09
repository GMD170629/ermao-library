import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_BOOKS_QUERY,
  isImportTargetPathWithinRoot,
  isSupportedImportFileName,
  normalizeBooksQuery,
} from './library';

test('normalizes bounded search without mutating other URL query fields', () => {
  const query = normalizeBooksQuery({
    ...DEFAULT_BOOKS_QUERY,
    search: `  ${'书'.repeat(240)}  `,
    status: 'UNREAD',
    mediaKind: 'EBOOK',
    shelfId: 'shelf-1',
  });
  assert.equal(query.search.length, 200);
  assert.equal(query.status, 'UNREAD');
  assert.equal(query.mediaKind, 'EBOOK');
  assert.equal(query.shelfId, 'shelf-1');
});

test('matches the server-supported import extension set case-insensitively', () => {
  assert.equal(isSupportedImportFileName('novel.EPUB'), true);
  assert.equal(isSupportedImportFileName('archive.cbz'), true);
  assert.equal(isSupportedImportFileName('audio.FLAC'), true);
  assert.equal(isSupportedImportFileName('cover.png'), false);
  assert.equal(isSupportedImportFileName('no-extension'), false);
});

test('accepts preferred upload directories only within an enabled root', () => {
  assert.equal(isImportTargetPathWithinRoot('/books/inbox', '/books'), true);
  assert.equal(isImportTargetPathWithinRoot('D:\\Books\\Inbox', 'D:\\Books'), true);
  assert.equal(isImportTargetPathWithinRoot('/books-other', '/books'), false);
  assert.equal(isImportTargetPathWithinRoot('/outside', '/books'), false);
});
