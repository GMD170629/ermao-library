import assert from 'node:assert/strict';
import test from 'node:test';
import {
  BrowserPublicationStore,
  OriginalPublicationStoreError,
  type OriginalPublicationDescriptor
} from './browser-publication-store';
import { READER_SAFETY_RULE_IDS } from '@shuku/reader-core';
import { ReaderSafetyPolicyError } from '../security/reader-safety-policy';

class MemoryCache {
  readonly entries = new Map<string, Response>();
  async match(request: Request) { return this.entries.get(request.url)?.clone(); }
  async delete(request: Request) { return this.entries.delete(request.url); }
  async keys() { return [...this.entries.keys()].map((url) => new Request(url)); }
  async put(request: Request, response: Response) {
    const bytes = await response.arrayBuffer();
    this.entries.set(request.url, new Response(bytes, { headers: response.headers }));
  }
}

const descriptor: OriginalPublicationDescriptor = {
  namespace: 'user-1-7',
  resourceId: 'resource-1',
  assetId: 'asset-1',
  assetVersion: '4:1234',
  sourceFormat: 'epub',
  mimeType: 'application/epub+zip',
  sizeBytes: 4,
  mtimeMs: 1234,
  downloadUrl: '/api/assets/asset-1/download'
};

function response(bytes: Uint8Array, version = descriptor.assetVersion) {
  return new Response(Uint8Array.from(bytes).buffer, { headers: {
    'Content-Type': descriptor.mimeType,
    'Content-Length': String(bytes.byteLength),
    'X-Asset-Version': version
  } });
}

test('streams progress before publishing and then reopens with zero network requests', async () => {
  const cache = new MemoryCache();
  let requests = 0;
  const progress: number[] = [];
  const store = new BrowserPublicationStore({ open: async () => cache }, async () => {
    requests += 1;
    return response(new Uint8Array([1, 2, 3, 4]));
  }, 'https://reader.test');
  const first = await store.ensure(descriptor, {
    signal: new AbortController().signal,
    onProgress: (event) => progress.push(event.loadedBytes)
  });
  const second = await store.ensure(descriptor, { signal: new AbortController().signal });
  assert.equal(first.cacheHit, false);
  assert.equal(second.cacheHit, true);
  assert.equal(first.blob.size, 4);
  assert.equal(requests, 1);
  assert.deepEqual(progress, [0, 4]);
});

test('short and stale responses fail closed without a published cache entry', async () => {
  for (const candidate of [response(new Uint8Array([1, 2, 3])), response(new Uint8Array([1, 2, 3, 4]), '4:999')]) {
    const cache = new MemoryCache();
    const store = new BrowserPublicationStore({ open: async () => cache }, async () => candidate, 'https://reader.test');
    await assert.rejects(store.ensure(descriptor, { signal: new AbortController().signal }));
    assert.equal(cache.entries.size, 0);
  }
});

test('cancellation removes the incomplete entry and never resumes it', async () => {
  const cache = new MemoryCache();
  const abortController = new AbortController();
  let reportProgress: (() => void) | null = null;
  const progressObserved = new Promise<void>((resolve) => { reportProgress = resolve; });
  const store = new BrowserPublicationStore({ open: async () => cache }, async () => new Response(
    new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new Uint8Array([1, 2])); }
    }),
    { headers: {
      'Content-Type': descriptor.mimeType,
      'Content-Length': String(descriptor.sizeBytes),
      'X-Asset-Version': descriptor.assetVersion
    } }
  ), 'https://reader.test');
  const pending = store.ensure(descriptor, {
    signal: abortController.signal,
    onProgress: (event) => { if (event.loadedBytes > 0) reportProgress?.(); }
  });
  await progressObserved;
  let settled = false;
  void pending.finally(() => { settled = true; }).catch(() => undefined);
  await Promise.resolve();
  assert.equal(settled, false);
  abortController.abort();
  await assert.rejects(pending, (error: unknown) => error instanceof DOMException && error.name === 'AbortError');
  assert.equal(cache.entries.size, 0);
});

test('eviction triggers a fresh full request and a wrong MIME never publishes', async () => {
  const cache = new MemoryCache();
  let requests = 0;
  const store = new BrowserPublicationStore({ open: async () => cache }, async () => {
    requests += 1;
    return response(new Uint8Array([1, 2, 3, 4]));
  }, 'https://reader.test');
  await store.ensure(descriptor, { signal: new AbortController().signal });
  cache.entries.clear();
  await store.ensure(descriptor, { signal: new AbortController().signal });
  assert.equal(requests, 2);

  cache.entries.clear();
  const wrongMime = new BrowserPublicationStore({ open: async () => cache }, async () => new Response(
    new Uint8Array([1, 2, 3, 4]),
    { headers: {
      'Content-Type': 'application/octet-stream',
      'Content-Length': '4',
      'X-Asset-Version': descriptor.assetVersion
    } }
  ), 'https://reader.test');
  await assert.rejects(
    wrongMime.ensure(descriptor, { signal: new AbortController().signal }),
    (error: unknown) => error instanceof ReaderSafetyPolicyError
      && error.ruleId === READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME
  );
  assert.equal(cache.entries.size, 0);
});

test('quota failure without reclaimable reader entries is explicit and leaves no partial entry', async () => {
  const cache = new MemoryCache();
  cache.put = async () => { throw new DOMException('Quota exceeded', 'QuotaExceededError'); };
  let requests = 0;
  const store = new BrowserPublicationStore({ open: async () => cache }, async () => {
    requests += 1;
    return response(new Uint8Array([1, 2, 3, 4]));
  }, 'https://reader.test');
  await assert.rejects(
    store.ensure(descriptor, { signal: new AbortController().signal }),
    (error: unknown) => error instanceof OriginalPublicationStoreError && error.code === 'ORIGINAL_CACHE_QUOTA'
  );
  assert.equal(requests, 1);
  assert.equal(cache.entries.size, 0);
});

test('quota failure reclaims inactive originals and retries the complete download once', async () => {
  const cache = new MemoryCache();
  cache.entries.set(
    'https://reader.test/__shuku_reader_originals__/other-resource/other-asset/4%3A1234/epub',
    response(new Uint8Array([9, 8, 7, 6]))
  );
  const persist = cache.put.bind(cache);
  let putAttempts = 0;
  cache.put = async (request, candidate) => {
    putAttempts += 1;
    if (putAttempts === 1) throw new DOMException('Quota exceeded', 'QuotaExceededError');
    await persist(request, candidate);
  };
  let requests = 0;
  const store = new BrowserPublicationStore({ open: async () => cache }, async () => {
    requests += 1;
    return response(new Uint8Array([1, 2, 3, 4]));
  }, 'https://reader.test');

  const stored = await store.ensure(descriptor, { signal: new AbortController().signal });

  assert.equal(stored.cacheHit, false);
  assert.equal(stored.blob.size, descriptor.sizeBytes);
  assert.equal(requests, 2);
  assert.equal(putAttempts, 2);
  assert.equal(cache.entries.size, 1);
});

test('quota recovery makes only one clean retry when storage remains full', async () => {
  const cache = new MemoryCache();
  cache.entries.set(
    'https://reader.test/__shuku_reader_originals__/other-resource/other-asset/4%3A1234/epub',
    response(new Uint8Array([9, 8, 7, 6]))
  );
  cache.put = async () => { throw new DOMException('Quota exceeded', 'QuotaExceededError'); };
  let requests = 0;
  const store = new BrowserPublicationStore({ open: async () => cache }, async () => {
    requests += 1;
    return response(new Uint8Array([1, 2, 3, 4]));
  }, 'https://reader.test');

  await assert.rejects(
    store.ensure(descriptor, { signal: new AbortController().signal }),
    (error: unknown) => error instanceof OriginalPublicationStoreError && error.code === 'ORIGINAL_CACHE_QUOTA'
  );

  assert.equal(requests, 2);
  assert.equal(cache.entries.size, 0);
});

test('cache availability failures are reported separately from device quota', async () => {
  const store = new BrowserPublicationStore({
    open: async () => { throw new DOMException('Cache unavailable', 'InvalidStateError'); }
  }, async () => response(new Uint8Array([1, 2, 3, 4])), 'https://reader.test');

  await assert.rejects(
    store.ensure(descriptor, { signal: new AbortController().signal }),
    (error: unknown) => error instanceof OriginalPublicationStoreError && error.code === 'ORIGINAL_CACHE_IO'
  );
});

test('a new asset version deletes the superseded complete entry before downloading', async () => {
  const cache = new MemoryCache();
  const oldDescriptor: OriginalPublicationDescriptor = {
    ...descriptor,
    assetVersion: '4:1000',
    mtimeMs: 1000
  };
  let requestedVersion = oldDescriptor.assetVersion;
  const store = new BrowserPublicationStore({ open: async () => cache }, async (requested) => {
    requestedVersion = requested.assetVersion;
    return response(new Uint8Array([1, 2, 3, 4]), requested.assetVersion);
  }, 'https://reader.test');
  await store.ensure(oldDescriptor, { signal: new AbortController().signal });
  assert.equal(cache.entries.size, 1);
  await store.ensure(descriptor, { signal: new AbortController().signal });
  assert.equal(requestedVersion, descriptor.assetVersion);
  assert.equal(cache.entries.size, 1);
});

test('zero-byte originals pass delivery admission and remain the parser responsibility', async () => {
  const cache = new MemoryCache();
  const emptyDescriptor: OriginalPublicationDescriptor = {
    ...descriptor,
    assetVersion: '0:1234',
    sizeBytes: 0
  };
  const store = new BrowserPublicationStore({ open: async () => cache }, async () => new Response(
    new Uint8Array(),
    { headers: {
      'Content-Type': emptyDescriptor.mimeType,
      'Content-Length': '0',
      'X-Asset-Version': emptyDescriptor.assetVersion
    } }
  ), 'https://reader.test');
  const stored = await store.ensure(emptyDescriptor, { signal: new AbortController().signal });
  assert.equal(stored.blob.size, 0);
  assert.equal(cache.entries.size, 1);
});
