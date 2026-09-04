import assert from 'node:assert/strict';
import test from 'node:test';
import { readerBookmarkFromWire, readerBookmarkToWire } from './api';

const position = {
  locator: {
    href: 'OPS/chapter.xhtml',
    type: 'application/xhtml+xml',
    locations: { progression: 0.25, fragments: ['epubcfi(/6/4!/4/2:1)'] },
    text: { highlight: '', before: 'before', after: 'after' },
    vendorExtension: { preserved: true }
  },
  presentation: {
    displayPercent: 99,
    totalProgression: 0.99,
    currentHref: 'OPS/chapter.xhtml',
    chapter: { href: 'OPS/chapter.xhtml', title: 'Chapter 1', index: 0 },
    page: null,
    playback: null
  }
} as const;

test('maps the Reader v5 bookmark position without projecting a server wire location', () => {
  const bookmark = readerBookmarkFromWire({
    id: 'reflowable:epub:cfi:epubcfi(/6/4!/4/2:1)',
    position,
    label: 'Chapter 1',
    createdAt: '2026-08-13T00:00:00Z'
  }, 'resource-1', 'epub');

  assert.ok(bookmark);
  assert.deepEqual(bookmark.position, position);
  assert.equal('location' in bookmark, false);
  assert.deepEqual(readerBookmarkToWire(bookmark), {
    id: bookmark.id,
    position,
    label: bookmark.label,
    createdAt: bookmark.createdAt
  });
});

test('ignores an incompatible v4 bookmark and preserves an opaque locator extension', () => {
  assert.equal(readerBookmarkFromWire({
    id: 'legacy',
    location: { kind: 'reflow', resourceKey: 'OPS/chapter.xhtml', progression: 0.25 },
    label: 'legacy',
    percent: 10,
    createdAt: '2026-08-13T00:00:00Z'
  }, 'resource-1', 'epub'), null);

  const wire = readerBookmarkToWire({
    id: 'bookmark-1',
    label: 'Chapter',
    createdAt: '2026-08-13T00:00:00Z',
    position
  });

  assert.deepEqual(wire, {
    id: 'bookmark-1',
    position,
    label: 'Chapter',
    createdAt: '2026-08-13T00:00:00Z'
  });
});

test('does not derive navigation from presentation when the opaque locator is empty', () => {
  const emptyLocatorPosition = {
    locator: {},
    presentation: {
      displayPercent: 99,
      totalProgression: 0.99,
      currentHref: 'OPS/chapter.xhtml',
      chapter: { href: 'OPS/chapter.xhtml', title: 'Chapter 1', index: 0 },
      page: null,
      playback: null
    }
  } as const;

  const bookmark = readerBookmarkFromWire({
    id: 'opaque-empty',
    position: emptyLocatorPosition,
    label: 'Empty locator',
    createdAt: '2026-08-13T00:00:00Z'
  }, 'resource-1', 'epub');

  assert.ok(bookmark);
  assert.deepEqual(bookmark.position.locator, {});
  assert.equal('location' in bookmark, false);
});
