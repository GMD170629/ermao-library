import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchReaderBootstrap } from './api';

function bootstrapPayload(sourceFormat: 'mobi' | 'txt') {
  const assetKind = sourceFormat === 'txt' ? 'TXT' : 'MOBI';
  const mimeType = sourceFormat === 'txt' ? 'text/plain' : 'application/x-mobipocket-ebook';
  return {
    ok: true,
    data: {
      schemaVersion: 4,
      userId: 'user-1',
      readerType: 'reflowable',
      sourceFormat,
      book: { id: 'book-1', title: 'Book' },
      resource: {
        id: 'resource-1', bookId: 'book-1', title: 'Resource', format: sourceFormat,
        readerType: 'reflowable', sortOrder: 0, resourceCompleted: false,
      },
      availableResources: [],
      assets: [{
        id: 'asset-1', kind: assetKind, mimeType, sizeBytes: 42, sortOrder: 0,
        url: '/api/assets/asset-1',
      }],
      units: [],
      publication: {
        kind: 'reflowable',
        manifestUrl: '/api/reader/v4/resources/resource-1/publication/manifest.json',
        positionsUrl: '/api/reader/v4/resources/resource-1/publication/positions.json',
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

      const bootstrap = await fetchReaderBootstrap('resource-1', new AbortController().signal);

      assert.equal(bootstrap.source.kind, 'reflowable');
      assert.equal(bootstrap.source.sourceFormat, sourceFormat);
      assert.equal(
        bootstrap.source.publicationManifestUrl,
        '/api/reader/v4/resources/resource-1/publication/manifest.json',
      );
      assert.equal('contentUrl' in bootstrap.source, false);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});
