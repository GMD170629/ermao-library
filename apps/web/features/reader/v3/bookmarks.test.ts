import assert from 'node:assert/strict';
import test from 'node:test';
import { hasReaderBookmark, mergeReaderBookmarks, readReaderBookmarks, readerBookmarkId, readerBookmarkStorageKey, removeReaderBookmark, toggleReaderBookmark } from './bookmarks';

test('creates stable bookmark ids for every reader location kind', () => {
  assert.equal(readerBookmarkId({ kind: 'epub', cfi: 'epubcfi(/6/4!/4/2:1)' }), 'epub:cfi:epubcfi(/6/4!/4/2:1)');
  assert.equal(readerBookmarkId({ kind: 'reflowable', format: 'fb2', cfi: 'epubcfi(/6/4!/4/2:1)' }), 'reflowable:fb2:cfi:epubcfi(/6/4!/4/2:1)');
  assert.equal(readerBookmarkId({ kind: 'comic', volumeId: 'volume-2', pageIndex: 18 }), 'comic:volume-2:18');
  assert.equal(readerBookmarkId({ kind: 'pdf', pageNumber: 7 }), 'pdf:7');
});

test('toggles a current location without creating duplicate bookmarks', () => {
  const draft = {
    location: { kind: 'pdf' as const, pageNumber: 7 },
    label: '第 7 / 20 页',
    percent: 35,
    createdAt: '2026-07-19T00:00:00.000Z'
  };
  const added = toggleReaderBookmark([], draft);
  assert.equal(added.length, 1);
  assert.equal(hasReaderBookmark(added, draft.location), true);
  assert.deepEqual(toggleReaderBookmark(added, draft), []);
});

test('isolates bookmarks by user, volume and content fingerprint', () => {
  assert.notEqual(
    readerBookmarkStorageKey('user-1', 'volume-1', 'fingerprint-a'),
    readerBookmarkStorageKey('user-2', 'volume-1', 'fingerprint-a')
  );
  assert.notEqual(readerBookmarkStorageKey('user-1', 'volume-1', 'fingerprint-a'), readerBookmarkStorageKey('user-1', 'volume-2', 'fingerprint-a'));
  assert.deepEqual(readReaderBookmarks('{broken'), []);
  assert.deepEqual(readReaderBookmarks('[{"id":"pdf:2","location":{"kind":"pdf","pageNumber":2},"label":"第 2 页","percent":10,"createdAt":"now"}]').length, 1);
});

test('merges legacy volume lists in reading order and removes a single saved bookmark', () => {
  const first = toggleReaderBookmark([], {
    location: { kind: 'comic', volumeId: 'volume-1', pageIndex: 8 },
    label: '第一卷 · 第 8 页',
    percent: 15,
    createdAt: '2026-07-19T00:00:00.000Z'
  });
  const second = toggleReaderBookmark([], {
    location: { kind: 'comic', volumeId: 'volume-2', pageIndex: 3 },
    label: '第二卷 · 第 3 页',
    percent: 55,
    createdAt: '2026-07-19T01:00:00.000Z'
  });
  const merged = mergeReaderBookmarks(second, first, first);
  assert.deepEqual(merged.map((bookmark) => bookmark.id), ['comic:volume-1:8', 'comic:volume-2:3']);
  assert.deepEqual(removeReaderBookmark(merged, first[0]!.id), second);
});
