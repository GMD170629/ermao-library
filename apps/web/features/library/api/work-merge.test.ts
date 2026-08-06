import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchWorkMergePreview } from './work-merge';

test('maps grouped merge volumes and preserves the server ordering', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    ok: true,
    data: {
      works: [
        { id: 'work-2', title: 'Book 2', author: 'Author' },
        { id: 'work-1', title: 'Book 1', author: 'Author' }
      ],
      mediaGroups: [{
        mediaKind: 'EBOOK',
        volumes: [
          { id: 'volume-1', title: 'Volume 1', volumeIndex: 1, format: 'EPUB', sourceWorkId: 'work-1', sourceWorkTitle: 'Book 1', coverUrl: '/cover-1', hasCover: true },
          { id: 'volume-2', title: 'Volume 2', volumeIndex: 2, format: 'EPUB', sourceWorkId: 'work-2', sourceWorkTitle: 'Book 2', coverUrl: '/cover-2', hasCover: false }
        ]
      }],
      suggestedMetadata: { title: 'Book 2', author: 'Author', description: null, seriesName: null, seriesIndex: null, tags: ['tag'] },
      defaultCoverVolumeId: 'volume-1',
      writeMetadataToFiles: true
    }
  }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  try {
    const preview = await fetchWorkMergePreview(['work-2', 'work-1']);
    assert.deepEqual(preview.mediaGroups[0]?.volumes.map((volume) => volume.id), ['volume-1', 'volume-2']);
    assert.equal(preview.defaultCoverVolumeId, 'volume-1');
    assert.equal(preview.writeMetadataToFiles, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('rejects an unknown media kind at the network boundary', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    ok: true,
    data: {
      works: [],
      mediaGroups: [{ mediaKind: 'VIDEO', volumes: [] }],
      suggestedMetadata: { title: 'Book', author: '', tags: [] },
      defaultCoverVolumeId: 'volume-1',
      writeMetadataToFiles: false
    }
  }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  try {
    await assert.rejects(() => fetchWorkMergePreview(['work-1', 'work-2']), /WORK_MERGE_INVALID_mediaKind/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
