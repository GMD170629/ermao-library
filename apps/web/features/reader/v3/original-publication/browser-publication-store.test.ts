import { ORIGINAL_CHUNK_BYTES } from './original-store-contract';
import assert from 'node:assert/strict';
import test from 'node:test';
import { IDBFactory, IDBKeyRange } from 'fake-indexeddb';
import { BrowserPublicationStore, OriginalPublicationStoreError, type OriginalPublicationDescriptor, type OriginalDownloadTransport } from './browser-publication-store';
import { IndexedDbPublicationStorage, ORIGINAL_DATABASE_NAME } from './indexeddb-publication-storage';

Object.assign(globalThis, { IDBKeyRange });
const descriptor: OriginalPublicationDescriptor = {
  namespace: 'user-1-7', resourceId: 'resource-1', assetId: 'asset-1', assetVersion: '4:1234',
  sourceFormat: 'epub', mimeType: 'application/epub+zip', sizeBytes: 4, mtimeMs: 1234,
  downloadUrl: '/api/assets/asset-1/download'
};
const options = () => ({ signal: new AbortController().signal });
function response(bytes = new Uint8Array([1, 2, 3, 4]), requested = descriptor) {
  return new Response(Uint8Array.from(bytes).buffer, { headers: {
    'Content-Length': String(requested.sizeBytes), 'X-Asset-Version': requested.assetVersion
  } });
}
async function setup(transport: OriginalDownloadTransport = async () => response()) {
  const factory = new IDBFactory();
  const storage = new IndexedDbPublicationStorage(() => factory);
  await storage.activate(descriptor.namespace);
  return { factory, storage, store: new BrowserPublicationStore(storage, transport, 'http://reader.test') };
}
async function records(factory: IDBFactory, name: string): Promise<unknown[]> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const operation = factory.open(ORIGINAL_DATABASE_NAME);
    operation.onsuccess = () => resolve(operation.result);
    operation.onerror = () => reject(operation.error);
  });
  try {
    return await new Promise((resolve, reject) => {
      const operation = db.transaction(name).objectStore(name).getAll();
      operation.onsuccess = () => resolve(operation.result);
      operation.onerror = () => reject(operation.error);
    });
  } finally { db.close(); }
}
function code(expected: string) {
  return (error: unknown) => error instanceof OriginalPublicationStoreError && error.code === expected;
}

test('streams committed progress, publishes exact bytes and reopens without network', async () => {
  let requests = 0;
  const { store, factory } = await setup(async () => { requests += 1; return response(); });
  const progress: number[] = [];
  const first = await store.ensure(descriptor, { ...options(), onProgress: (event) => progress.push(event.loadedBytes) });
  const reopened = await store.ensure(descriptor, options());
  assert.equal(first.cacheHit, false);
  assert.equal(reopened.cacheHit, true);
  assert.deepEqual(new Uint8Array(await reopened.blob.arrayBuffer()), new Uint8Array([1, 2, 3, 4]));
  assert.equal(requests, 1);
  assert.deepEqual(progress, [0, 4]);
  assert.equal((await records(factory, 'chunks')).length, 1);
});

test('short, excess, missing length and stale version responses never publish', async () => {
  for (const candidate of [response(new Uint8Array(3)), response(new Uint8Array(5)),
    new Response(new Uint8Array(4)), response(new Uint8Array(4), { ...descriptor, assetVersion: '4:999' })]) {
    const { store, storage, factory } = await setup(async () => candidate);
    await assert.rejects(store.ensure(descriptor, options()));
    assert.equal(await storage.read(await storage.session(descriptor.namespace), descriptor), null);
    assert.deepEqual(await records(factory, 'chunks'), []);
  }
});

test('slow downloads persist bounded chunks before EOF without opening; cancellation discards and retry starts at zero', async () => {
  const abort = new AbortController();
  let progressed: () => void = () => undefined;
  const observed = new Promise<void>((resolve) => { progressed = resolve; });
  const big: OriginalPublicationDescriptor = { ...descriptor, sizeBytes: ORIGINAL_CHUNK_BYTES * 3, assetVersion: `${ORIGINAL_CHUNK_BYTES * 3}:1234` };
  let requests = 0;
  let cancelled = false;
  const { store, storage, factory } = await setup(async () => {
    requests += 1;
    if (requests > 1) return response(new Uint8Array(big.sizeBytes), big);
    return new Response(new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new Uint8Array(ORIGINAL_CHUNK_BYTES * 2)); },
      cancel() { cancelled = true; }
    }), { headers: { 'Content-Length': String(big.sizeBytes), 'X-Asset-Version': big.assetVersion } });
  });
  const pending = store.ensure(big, { signal: abort.signal, onProgress: (event) => {
    if (event.loadedBytes === ORIGINAL_CHUNK_BYTES * 2) progressed();
  } });
  await observed;
  assert.equal((await records(factory, 'chunks')).length, 2);
  assert.equal(await storage.read(await storage.session(big.namespace), big), null);
  abort.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(cancelled, true);
  assert.deepEqual(await records(factory, 'chunks'), []);
  assert.equal((await store.ensure(big, options())).blob.size, big.sizeBytes);
  assert.equal(requests, 2);
});

test('incomplete artifacts survive another connection but are never used as cached originals', async () => {
  let requests = 0;
  const { factory, storage } = await setup();
  const session = await storage.session(descriptor.namespace);
  const abandoned = await storage.begin(session, descriptor);
  await storage.append(abandoned, new Blob([new Uint8Array([1, 2])]));
  const reopened = new IndexedDbPublicationStorage(() => factory);
  await reopened.activate(descriptor.namespace);
  const store = new BrowserPublicationStore(reopened, async () => { requests += 1; return response(); }, 'http://reader.test');
  assert.equal((await store.ensure(descriptor, options())).cacheHit, false);
  assert.equal(requests, 1);
});

test('unknown, empty and mismatched transport MIME preserve descriptor MIME and original bytes', async () => {
  for (const mimeType of ['', 'application/x-reader-unknown', 'application/epub+zip']) {
    const { store } = await setup();
    const requested = { ...descriptor, mimeType };
    assert.equal((await store.ensure(requested, options())).blob.type, mimeType);
    assert.equal((await store.ensure(requested, options())).cacheHit, true);
  }
});

test('zero byte originals remain the parser responsibility', async () => {
  const empty: OriginalPublicationDescriptor = { ...descriptor, sizeBytes: 0, assetVersion: '0:1234' };
  const { store } = await setup(async () => response(new Uint8Array(), empty));
  assert.equal((await store.ensure(empty, options())).blob.size, 0);
  assert.equal((await store.ensure(empty, options())).cacheHit, true);
});

test('quota with no reclaimable originals is explicit', async () => {
  const { storage, store, factory } = await setup();
  storage.append = async () => { throw new DOMException('Full', 'QuotaExceededError'); };
  await assert.rejects(store.ensure(descriptor, options()), code('ORIGINAL_CACHE_QUOTA'));
  assert.deepEqual(await records(factory, 'chunks'), []);
});

test('quota reclaims other completed originals and retries the whole download only once', async () => {
  for (const permanentlyFull of [false, true]) {
    let requests = 0;
    const { storage, store, factory } = await setup(async (_, signal) => { signal.throwIfAborted(); requests += 1; return response(); });
    const other = { ...descriptor, resourceId: 'other' };
    await store.ensure(other, options());
    const append = storage.append.bind(storage);
    let attempts = 0;
    storage.append = async (...args) => {
      attempts += 1;
      if (attempts === 1 || permanentlyFull) throw new DOMException('Full', 'QuotaExceededError');
      await append(...args);
    };
    if (permanentlyFull) await assert.rejects(store.ensure(descriptor, options()), code('ORIGINAL_CACHE_QUOTA'));
    else assert.equal((await store.ensure(descriptor, options())).blob.size, 4);
    assert.equal(requests, 3);
    assert.equal(attempts, 2);
    assert.equal((await records(factory, 'chunks')).length, permanentlyFull ? 0 : 1);
  }
});

test('a failed concurrent attempt does not remove another successful original', async () => {
  let unblock: () => void = () => undefined;
  const blocked = new Promise<void>((resolve) => { unblock = resolve; });
  let begun: () => void = () => undefined;
  const started = new Promise<void>((resolve) => { begun = resolve; });
  const { storage, store } = await setup();
  const other = new BrowserPublicationStore(storage, async () => {
    begun(); await blocked; return response(new Uint8Array(3));
  }, 'http://reader.test');
  const failed = other.ensure(descriptor, options());
  await started;
  await store.ensure(descriptor, options());
  unblock();
  await assert.rejects(failed, code('ORIGINAL_LENGTH_INVALID'));
  assert.equal((await store.ensure(descriptor, options())).cacheHit, true);
});

test('session changes in another tab invalidate old writes and reads, including switch back to same account', async () => {
  const { factory, storage } = await setup();
  const token = await storage.session(descriptor.namespace);
  const artifact = await storage.begin(token, descriptor);
  await storage.append(artifact, new Blob([new Uint8Array(4)]));
  const otherTab = new IndexedDbPublicationStorage(() => factory);
  await otherTab.activate(null);
  await assert.rejects(storage.session(descriptor.namespace), { name: 'AbortError' });
  await otherTab.activate(descriptor.namespace);
  await assert.rejects(storage.append(artifact, new Blob([new Uint8Array(1)])), { name: 'AbortError' });
  await assert.rejects(storage.complete(artifact, options().signal), { name: 'AbortError' });
  await assert.rejects(storage.read(token, descriptor), { name: 'AbortError' });
  assert.deepEqual(await records(factory, 'chunks'), []);
  const current = await otherTab.session(descriptor.namespace);
  assert.notEqual(current.epoch, token.epoch);
});

test('authorization version changes clear originals and reject old namespace', async () => {
  const { storage, store, factory } = await setup();
  await store.ensure(descriptor, options());
  await storage.activate('user-1-8');
  await assert.rejects(storage.session(descriptor.namespace), { name: 'AbortError' });
  assert.deepEqual(await records(factory, 'chunks'), []);
});

test('new complete asset versions replace old complete bytes', async () => {
  const { store, storage } = await setup(async (requested) => response(new Uint8Array(4), requested));
  await store.ensure(descriptor, options());
  const updated: OriginalPublicationDescriptor = { ...descriptor, mtimeMs: 2000, assetVersion: '4:2000' };
  await store.ensure(updated, options());
  const session = await storage.session(descriptor.namespace);
  assert.equal(await storage.read(session, descriptor), null);
  assert.equal((await store.ensure(updated, options())).cacheHit, true);
});

test('network and storage failures remain distinct; unavailable IndexedDB can retry', async () => {
  const { store } = await setup(async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(store.ensure(descriptor, options()), code('NETWORK_UNAVAILABLE'));
  const factory = new IDBFactory();
  let unavailable = true;
  const storage = new IndexedDbPublicationStorage(() => {
    if (unavailable) throw new DOMException('Unavailable', 'InvalidStateError');
    return factory;
  });
  await assert.rejects(storage.activate(descriptor.namespace));
  const reader = new BrowserPublicationStore(storage, async () => response(), 'http://reader.test');
  await assert.rejects(reader.ensure(descriptor, options()), code('ORIGINAL_CACHE_IO'));
  unavailable = false;
  assert.equal((await reader.ensure(descriptor, options())).blob.size, 4);
});

test('transaction abort never exposes a partially committed chunk', async () => {
  const { storage, factory } = await setup();
  const token = await storage.session(descriptor.namespace);
  const artifact = await storage.begin(token, descriptor);
  await assert.rejects(storage.append(artifact, new Blob([new Uint8Array(5)])), code('ORIGINAL_LENGTH_INVALID'));
  assert.deepEqual(await records(factory, 'chunks'), []);
  assert.equal(await storage.read(token, descriptor), null);
});

test('evicted or corrupt cached chunks are rebuilt with one fresh complete request', async () => {
  let requests = 0;
  const { store, factory } = await setup(async () => { requests += 1; return response(); });
  await store.ensure(descriptor, options());
  const db = await new Promise<IDBDatabase>((resolve) => {
    const operation = factory.open(ORIGINAL_DATABASE_NAME);
    operation.onsuccess = () => resolve(operation.result);
  });
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction('chunks', 'readwrite');
    tx.objectStore('chunks').clear();
    tx.oncomplete = () => resolve();
    tx.onabort = () => reject(tx.error);
  });
  db.close();
  assert.equal((await store.ensure(descriptor, options())).cacheHit, false);
  assert.equal(requests, 2);
  assert.equal((await records(factory, 'chunks')).length, 1);
});

test('cancellation before publication leaves the previous successful concurrent original intact', async () => {
  const { storage, store } = await setup();
  await store.ensure(descriptor, options());
  const session = await storage.session(descriptor.namespace);
  const pending = await storage.begin(session, descriptor);
  await storage.append(pending, new Blob([new Uint8Array([9, 8, 7, 6])]));
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(storage.complete(pending, abort.signal), { name: 'AbortError' });
  await storage.discard(pending);
  assert.deepEqual(new Uint8Array(await (await store.ensure(descriptor, options())).blob.arrayBuffer()), new Uint8Array([1, 2, 3, 4]));
});
