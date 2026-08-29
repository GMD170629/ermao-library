import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchReaderBootstrap } from './api';

const cases = [
  ['epub', 'EPUB', 'application/epub+zip'],
  ['mobi', 'MOBI', 'application/x-mobipocket-ebook'],
  ['azw', 'AZW', 'application/vnd.amazon.ebook'],
  ['azw3', 'AZW3', 'application/vnd.amazon.ebook'],
  ['prc', 'PRC', 'application/x-mobipocket-ebook'],
  ['txt', 'TXT', 'text/plain'],
  ['fb2', 'FB2', 'application/x-fictionbook+xml']
] as const;

function bootstrapPayload(sourceFormat: string) {
  return { ok: true, data: {
    schemaVersion: 4, userId: 'user-1', readerType: 'reflowable', sourceFormat,
    book: { id: 'book-1', title: 'Book' },
    resource: { id: 'resource-1', bookId: 'book-1', title: 'Resource', format: sourceFormat, readerType: 'reflowable', sortOrder: 0, resourceCompleted: false },
    availableResources: [], assets: [], units: [], capabilities: {}, progressSnapshot: null
  } };
}

function descriptorPayload(format: string, mimeType: string) {
  return { ok: true, data: { resource: {
    id: 'resource-1', bookId: 'book-1', sourceNodeId: 'source-1', title: 'Resource', format,
    readerType: 'reflowable', sortOrder: 0, importStatus: 'READY', coverUrl: '', sizeBytes: 42,
    readable: true, kindleSendAvailable: false,
    assets: [{
      id: 'asset-1', title: 'Original', resourceId: 'resource-1', sourceNodeId: 'asset-source-1',
      role: 'PRIMARY', mimeType, sourceFormat: format, sizeBytes: 42, size: '42 B', mtimeMs: 1234,
      sortOrder: 0, url: '/api/assets/asset-1', downloadUrl: '/api/assets/asset-1?download=true'
    }]
  } } };
}

test('maps all reflowable bootstraps to exact original descriptors without RWPM', async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const [sourceFormat, format, mimeType] of cases) {
      const requests: string[] = [];
      globalThis.fetch = async (input) => {
        const url = String(input);
        requests.push(url);
        return Response.json(url.startsWith('/api/resources/')
          ? descriptorPayload(format, mimeType)
          : bootstrapPayload(sourceFormat));
      };
      const bootstrap = await fetchReaderBootstrap('resource-1', new AbortController().signal);
      assert.equal(bootstrap.source.kind, 'reflowable');
      assert.equal(bootstrap.source.sourceFormat, sourceFormat);
      assert.equal(bootstrap.source.originalResource.assetId, 'asset-1');
      assert.equal(bootstrap.source.originalResource.assetVersion, '42:1234');
      assert.equal(bootstrap.source.originalResource.mimeType, mimeType);
      assert.equal(bootstrap.units.length, 0);
      assert.equal(requests.some((url) => url.includes('/publication/')), false);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('PDF and comic remain streamed while audio never enters the Reader download flow', async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const readerType of ['pdf', 'comic'] as const) {
      const resourceId = `${readerType}-resource`;
      const requests: string[] = [];
      globalThis.fetch = async (input) => {
        const url = String(input);
        requests.push(url);
        if (url.endsWith('/comic/manifest')) {
          return Response.json({ ok: true, data: {
            schemaVersion: 1,
            kind: 'comic',
            resourceId,
            sourceFormat: 'cbz',
            pageCount: 1,
            readingOrder: [{ pageIndex: 0, resourceHref: 'pages/0', mediaType: 'image/jpeg' }]
          } });
        }
        const format = readerType === 'pdf' ? 'pdf' : 'cbz';
        const mimeType = readerType === 'pdf' ? 'application/pdf' : 'application/vnd.comicbook+zip';
        return Response.json({ ok: true, data: {
          schemaVersion: 4,
          userId: 'user-1',
          readerType,
          sourceFormat: format,
          book: { id: 'book-1', title: 'Book' },
          resource: { id: resourceId, bookId: 'book-1', title: 'Resource', format, readerType, sortOrder: 0 },
          availableResources: [],
          assets: [{ id: `${readerType}-asset`, kind: 'CONTENT', mimeType, sizeBytes: 42, url: `/api/assets/${readerType}-asset` }],
          units: readerType === 'comic' ? [{ id: 'page-0', index: 0, title: '1', metadata: { pageIndex: 0 } }] : [],
          publication: readerType === 'comic' ? {
            kind: 'comic',
            manifestUrl: `/api/reader/v4/resources/${resourceId}/comic/manifest`,
            pageUrlTemplate: `/api/reader/v4/resources/${resourceId}/comic/pages/{pageIndex}`,
            imageVariants: ['original', 'data-saver']
          } : undefined,
          capabilities: {},
          progressSnapshot: null
        } });
      };
      const bootstrap = await fetchReaderBootstrap(resourceId, new AbortController().signal);
      assert.equal(bootstrap.source.kind, readerType);
      assert.equal(requests.some((url) => url.startsWith('/api/resources/')), false);
      assert.equal(requests.some((url) => url.includes('/api/assets/')), false);
    }

    const requests: string[] = [];
    globalThis.fetch = async (input) => {
      requests.push(String(input));
      return Response.json({ ok: true, data: {
        schemaVersion: 4,
        userId: 'user-1',
        readerType: 'audio',
        sourceFormat: 'm4b',
        book: { id: 'book-1', title: 'Audio' },
        resource: { id: 'audio-resource', bookId: 'book-1', title: 'Audio', format: 'M4B', readerType: 'audio', sortOrder: 0 }
      } });
    };
    await assert.rejects(fetchReaderBootstrap('audio-resource', new AbortController().signal));
    assert.equal(requests.some((url) => url.startsWith('/api/resources/')), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
