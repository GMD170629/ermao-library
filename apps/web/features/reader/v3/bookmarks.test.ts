import assert from 'node:assert/strict';
import test from 'node:test';
import { hasReaderBookmark, mergeReaderBookmarks, readReaderBookmarks, readerBookmarkId, readerBookmarkStorageKey, removeReaderBookmark, toggleReaderBookmark } from './bookmarks';

const pdfPosition = {
  locator: { href: 'document.pdf', type: 'application/pdf', locations: { position: 8, progression: 0 } },
  presentation: {
    displayPercent: 35,
    totalProgression: 0.35,
    currentHref: 'document.pdf',
    chapter: null,
    page: { number: 8, total: 20 },
    playback: null
  }
} as const;

const comicPosition = {
  locator: { href: 'pages/9.jpg', type: 'image/jpeg', locations: { position: 9, progression: 0, totalProgression: 0.4 } },
  presentation: {
    displayPercent: 15,
    totalProgression: 0.15,
    currentHref: 'pages/9.jpg',
    chapter: null,
    page: { number: 9, total: 20 },
    playback: null
  }
} as const;

test('creates stable bounded bookmark ids from complete v5 positions', () => {
  assert.equal(readerBookmarkId(pdfPosition), readerBookmarkId({
    presentation: { ...pdfPosition.presentation },
    locator: { locations: { progression: 0, position: 8 }, type: 'application/pdf', href: 'document.pdf' }
  }));
  assert.notEqual(readerBookmarkId(pdfPosition), readerBookmarkId(comicPosition));
  assert.match(readerBookmarkId(pdfPosition) ?? '', /^v5:\d+:[0-9a-f]{16}$/);
});

test('toggles a current position without creating duplicate bookmarks', () => {
  const draft = {
    position: pdfPosition,
    label: '第 8 / 20 页',
    createdAt: '2026-07-19T00:00:00.000Z'
  };
  const added = toggleReaderBookmark([], draft);
  assert.equal(added.length, 1);
  assert.equal(hasReaderBookmark(added, draft.position), true);
  assert.deepEqual(toggleReaderBookmark(added, draft), []);
});

test('isolates bookmarks by user and resource and ignores old local shapes', () => {
  assert.notEqual(
    readerBookmarkStorageKey('user-1', 'resource-1'),
    readerBookmarkStorageKey('user-2', 'resource-1')
  );
  assert.notEqual(readerBookmarkStorageKey('user-1', 'resource-1'), readerBookmarkStorageKey('user-1', 'resource-2'));
  assert.deepEqual(readReaderBookmarks('{broken'), []);
  assert.deepEqual(readReaderBookmarks('[{"id":"pdf:2","location":{"kind":"pdf","pageIndex":2,"pageProgression":0},"label":"第 3 页","percent":10,"createdAt":"now"}]'), []);
  const id = readerBookmarkId(pdfPosition);
  assert.ok(id);
  assert.equal(readReaderBookmarks(JSON.stringify([{
    id,
    position: pdfPosition,
    label: '第 8 页',
    createdAt: '2026-07-19T00:00:00.000Z'
  }])).length, 1);
});

test('merges positions by digest and removes a single saved bookmark', () => {
  const first = toggleReaderBookmark([], {
    position: comicPosition,
    label: '第一卷 · 第 9 页',
    createdAt: '2026-07-19T00:00:00.000Z'
  });
  const secondPosition = {
    ...comicPosition,
    locator: { ...comicPosition.locator, href: 'pages/4.jpg', locations: { position: 4, progression: 0, totalProgression: 0.15 } },
    presentation: { ...comicPosition.presentation, displayPercent: 55, totalProgression: 0.55, currentHref: 'pages/4.jpg', page: { number: 4, total: 20 } }
  } as const;
  const second = toggleReaderBookmark([], {
    position: secondPosition,
    label: '第二卷 · 第 4 页',
    createdAt: '2026-07-19T01:00:00.000Z'
  });
  const merged = mergeReaderBookmarks(second, first, first);
  assert.deepEqual(merged.map((bookmark) => bookmark.id), [first[0]!.id, second[0]!.id]);
  assert.deepEqual(removeReaderBookmark(merged, first[0]!.id), second);
});
