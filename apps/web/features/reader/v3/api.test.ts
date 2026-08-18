import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchReaderBootstrap } from './api';

function bootstrapPayload(sourceFormat: 'mobi' | 'txt') {
  const fileKind = sourceFormat === 'txt' ? 'TXT' : 'MOBI';
  const mimeType = sourceFormat === 'txt' ? 'text/plain' : 'application/x-mobipocket-ebook';
  return {
    ok: true,
    data: {
      schemaVersion: 4,
      userId: 'user-1',
      readerType: 'reflowable',
      sourceFormat,
      book: { id: 'work-1', title: 'Book' },
      version: { id: 'version-1', workId: 'work-1', sourceKey: '__implicit__', sourceName: null },
      versionCompleted: false,
      volume: {
        id: 'volume-1', versionId: 'version-1', title: 'Volume', format: sourceFormat,
        readerType: 'reflowable', sortOrder: 0,
      },
      availableVolumes: [],
      files: [{
        id: 'file-1', kind: fileKind, mimeType, sizeBytes: 42, sortOrder: 0,
        url: '/api/volumes/volume-1/file',
      }],
      units: [],
      fileUrl: '/api/volumes/volume-1/file',
      publication: {
        kind: 'reflowable',
        manifestUrl: '/api/reader/v4/volumes/volume-1/publication/manifest.json',
        positionsUrl: '/api/reader/v4/volumes/volume-1/publication/positions.json',
      },
      capabilities: {},
      progressSnapshot: null,
    },
  };
}

test('maps MOBI and TXT bootstrap to manifest-only reflowable sources', async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const sourceFormat of ['mobi', 'txt'] as const) {
      globalThis.fetch = async () => Response.json(bootstrapPayload(sourceFormat));

      const bootstrap = await fetchReaderBootstrap('volume-1', new AbortController().signal);

      assert.equal(bootstrap.source.kind, 'reflowable');
      assert.equal(bootstrap.source.sourceFormat, sourceFormat);
      assert.equal(
        bootstrap.source.publicationManifestUrl,
        '/api/reader/v4/volumes/volume-1/publication/manifest.json',
      );
      assert.equal('contentUrl' in bootstrap.source, false);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});
