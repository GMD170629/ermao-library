import assert from 'node:assert/strict';
import test from 'node:test';
import type { ReaderSource } from '@shuku/reader-core';
import {
  claimSharedEpubLocations,
  EPUB_LOCATION_CACHE_VERSION,
  EPUB_SHARED_LOCATION_WAIT_LIMIT_MS,
  saveSharedEpubLocations,
  sharedEpubLocationsWaitMs
} from './epub-location-cache';

const source: ReaderSource = {
  editionId: 'edition/one',
  workId: 'work-one',
  volumeId: 'volume one',
  kind: 'epub',
  contentUrl: '/content.epub',
  contentFingerprint: 'sha256:book'
};

test('shared EPUB location claim is scoped by edition and volume content identity', async () => {
  const originalFetch = globalThis.fetch;
  let requestUrl = '';
  let requestInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    requestInit = init;
    return Response.json({ status: 'claimed', leaseToken: 'lease-1', leaseExpiresAt: 123 });
  };
  try {
    const result = await claimSharedEpubLocations(source);
    assert.equal(result.status, 'claimed');
    assert.equal(requestUrl, '/api/v2/reading/editions/edition%2Fone/epub-locations/claim?volume=volume+one');
    assert.equal(requestInit?.method, 'POST');
    assert.deepEqual(JSON.parse(String(requestInit?.body)), {
      cacheVersion: EPUB_LOCATION_CACHE_VERSION,
      contentFingerprint: 'sha256:book',
      breakSize: 1200
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('shared EPUB locations upload the serialized map with its generation lease', async () => {
  const originalFetch = globalThis.fetch;
  let requestInit: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    requestInit = init;
    return Response.json({ status: 'ready', serialized: '["epubcfi(/6/2)"]' });
  };
  try {
    const result = await saveSharedEpubLocations(source, 'lease-1', '["epubcfi(/6/2)"]');
    assert.equal(result.status, 'ready');
    assert.deepEqual(JSON.parse(String(requestInit?.body)), {
      cacheVersion: 2,
      contentFingerprint: 'sha256:book',
      breakSize: 1200,
      leaseToken: 'lease-1',
      serialized: '["epubcfi(/6/2)"]'
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('shared EPUB location wait is bounded so an abandoned lease cannot block opening', () => {
  const startedAt = 10_000;
  assert.equal(sharedEpubLocationsWaitMs(1_000, startedAt, startedAt), 1_000);
  assert.equal(
    sharedEpubLocationsWaitMs(1_000, startedAt, startedAt + EPUB_SHARED_LOCATION_WAIT_LIMIT_MS - 200),
    200
  );
  assert.equal(
    sharedEpubLocationsWaitMs(1_000, startedAt, startedAt + EPUB_SHARED_LOCATION_WAIT_LIMIT_MS),
    0
  );
});

test('shared EPUB location claims reject malformed success payloads instead of retrying forever', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({});
  try {
    await assert.rejects(
      claimSharedEpubLocations(source),
      /EPUB 位置索引服务返回了无效状态/
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
