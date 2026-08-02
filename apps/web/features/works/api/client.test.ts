import assert from 'node:assert/strict';
import test from 'node:test';
import { mapWorkView, searchWorkTransferTargets } from './client';

test('full work responses reject summary projections before reaching detail UI', () => {
  assert.throws(
    () => mapWorkView({ id: 'work-1', title: 'Summary only' }),
    /媒介版本结构/
  );
});

test('maps optional detail-tab fields and ignores invalid boundary values', () => {
  const work = mapWorkView({
    id: 'work-1', mediaVersions: [], availableMediaKinds: ['EBOOK', 'NOPE'],
    detailTabs: [{ key: 'AUDIOBOOK', label: 'Listen', sortOrder: 3 }, { key: 'NOPE' }],
    selectedDetailTab: 'NOPE'
  });
  assert.deepEqual(work.availableMediaKinds, ['EBOOK']);
  assert.deepEqual(work.detailTabs, [{ key: 'AUDIOBOOK', label: 'Listen', sortOrder: 3 }]);
  assert.equal(work.selectedDetailTab, null);
});

test('derives available media kinds when optional detail fields are absent', () => {
  const work = mapWorkView({ id: 'work-1', mediaVersions: [{ id: 'media-1', mediaKind: 'COMIC', volumes: [] }] });
  assert.deepEqual(work.availableMediaKinds, ['COMIC']);
  assert.deepEqual(work.detailTabs, []);
  assert.equal(work.selectedDetailTab, null);
});

test('keeps server totals when the lean work detail contains only the first volume page', () => {
  const work = mapWorkView({
    id: 'work-1',
    mediaVersions: [{
      id: 'media-1',
      mediaKind: 'COMIC',
      volumeCount: 12,
      sizeBytes: 4096,
      volumes: [{
        id: 'volume-1',
        mediaVersionId: 'media-1',
        title: 'Volume 1',
        format: 'COMIC',
        sortOrder: 0,
        sizeBytes: 1024,
        files: []
      }]
    }]
  });

  assert.equal(work.mediaVersions[0]?.volumeCount, 12);
  assert.equal(work.mediaVersions[0]?.sizeBytes, 4096);
  assert.equal(work.mediaVersions[0]?.volumes.length, 1);
});

test('searches transfer targets and excludes the current work', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    assert.match(url, /view=bookshelf/);
    assert.match(url, /search=target/);
    return new Response(JSON.stringify({
      ok: true,
      data: {
        books: [
          { id: 'current-work', title: 'Current', author: 'Author' },
          { id: 'target-work', title: 'Target', author: 'Writer' }
        ]
      }
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };

  try {
    assert.deepEqual(
      await searchWorkTransferTargets('target', 'current-work'),
      [{ id: 'target-work', title: 'Target', author: 'Writer' }]
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
