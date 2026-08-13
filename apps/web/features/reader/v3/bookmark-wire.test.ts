import assert from 'node:assert/strict';
import test from 'node:test';
import { readerBookmarkFromWire, readerBookmarkToWire } from './api';

test('maps the Reader v4 simplified reflow bookmark contract', () => {
  const bookmark = readerBookmarkFromWire({
    id: 'reflowable:epub:position:OPS/chapter.xhtml:0.25',
    location: { kind: 'reflow', resourceKey: 'OPS/chapter.xhtml', progression: 0.25 },
    label: 'Chapter 1',
    percent: 10,
    createdAt: '2026-08-13T00:00:00Z'
  }, 'volume-1', 'epub');

  assert.ok(bookmark);
  assert.deepEqual(bookmark.location, {
    kind: 'reflowable',
    format: 'epub',
    href: 'OPS/chapter.xhtml',
    resourceProgression: 0.25
  });
  assert.deepEqual(readerBookmarkToWire(bookmark), {
    ...bookmark,
    location: { kind: 'reflow', resourceKey: 'OPS/chapter.xhtml', progression: 0.25 }
  });
});

test('projects an exact local Readium locator instead of sending it to the server', () => {
  const wire = readerBookmarkToWire({
    id: 'bookmark-1',
    label: 'Chapter',
    percent: 20,
    createdAt: '2026-08-13T00:00:00Z',
    location: {
      kind: 'reflowable',
      format: 'epub',
      exactLocator: {
        engine: 'readium',
        platform: 'web',
        version: 'readium-web:1',
        publication: {
          originalFileHash: `sha256:${'0'.repeat(64)}`,
          parser: 'readium',
          normalization: 'epub-v1'
        },
        payload: {
          href: 'OPS/exact.xhtml',
          type: 'application/xhtml+xml',
          locations: { cssSelector: '#p1', progression: 0.4 }
        }
      }
    }
  });

  assert.deepEqual(wire.location, {
    kind: 'reflow',
    resourceKey: 'OPS/exact.xhtml',
    progression: 0.4
  });
});
