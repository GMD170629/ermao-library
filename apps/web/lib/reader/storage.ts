import {
  PDF_RANGE_DOCUMENT_CACHE_BYTES,
  PDF_RANGE_NAMESPACE_CACHE_BYTES,
  READER_SCHEMA_VERSION,
  normalizeReaderPreferences,
  pdfRangeChunkKey,
  pdfRangeDocumentKey,
  pdfRangeNamespaceKey,
  type PdfRangeCacheIdentity,
  type ReaderPreferences
} from '@shuku/reader-core';
import {
  READER_DB_SCHEMA_VERSION,
  READER_PROGRESS_DB_NAME,
  exactProgressKey,
  preferenceKey,
  syncStateKey,
  type ExactProgressIdentity,
  type ExactProgressRecord,
  type PendingProgressMutation,
  type ReaderPreferenceSnapshot,
  type ReaderSyncDiagnostic
} from './model';
import {
  readerResourceCacheKey,
  type CachedReaderResource,
  type ReaderResourceCache,
  type ReaderResourceCacheIdentity
} from './resource-cache';
import type { CachedPdfRangeChunk, PdfRangeCache } from './pdf-range-cache';

const PREFERENCES_STORE = 'preferences';
const EXACT_PROGRESS_STORE = 'exact-progress';
const PENDING_PROGRESS_STORE = 'pending-progress';
const META_STORE = 'meta';
const DIAGNOSTICS_STORE = 'diagnostics';
const RESOURCE_CACHE_STORE = 'resource-cache';
const PDF_RANGE_CHUNKS_STORE = 'pdf-range-chunks';

type ReaderStoreName = typeof PREFERENCES_STORE | typeof EXACT_PROGRESS_STORE
  | typeof PENDING_PROGRESS_STORE | typeof META_STORE
  | typeof DIAGNOSTICS_STORE | typeof RESOURCE_CACHE_STORE | typeof PDF_RANGE_CHUNKS_STORE;
type ClientMeta = { key: 'client'; clientId: string };
type StoredPdfRangeChunk = {
  key: string;
  documentKey: string;
  namespaceKey: string;
  chunkIndex: number;
  byteLength: number;
  bytes: ArrayBuffer;
  lastAccessedAt: number;
};

export interface ReaderStorage {
  getPreference(userId: string, bookId: string): Promise<ReaderPreferenceSnapshot | null>;
  putPreference(userId: string, bookId: string, preferences: ReaderPreferences, updatedAt?: number): Promise<ReaderPreferenceSnapshot>;
  deletePreference(userId: string, bookId: string): Promise<void>;
  getClientId(): Promise<string>;
  getExactProgress(identity: ExactProgressIdentity): Promise<ExactProgressRecord | null>;
  putExactProgress(progress: ExactProgressRecord): Promise<ExactProgressRecord>;
  putExactAndPending(progress: ExactProgressRecord, mutation: PendingProgressMutation): Promise<void>;
  putPendingProgress(mutation: PendingProgressMutation): Promise<void>;
  getPendingProgress(key: string): Promise<PendingProgressMutation | null>;
  getPendingProgressForIdentity(identity: ExactProgressIdentity): Promise<PendingProgressMutation | null>;
  listPendingProgress(userId: string): Promise<PendingProgressMutation[]>;
  deletePendingProgress(key: string, mutationId?: string): Promise<void>;
  putExactAndDeletePending(progress: ExactProgressRecord, pendingKey: string): Promise<void>;
  addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now?: number): Promise<ReaderSyncDiagnostic>;
  listDiagnostics(limit?: number): Promise<ReaderSyncDiagnostic[]>;
  clearAll(): Promise<void>;
}

function createId(prefix: string) {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}_${suffix}`;
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function requestResult<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
  });
}

function transactionComplete(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB transaction failed'));
    transaction.onabort = () => reject(transaction.error ?? new Error('IndexedDB transaction aborted'));
  });
}

let databasePromise: Promise<IDBDatabase> | null = null;

function openDatabase() {
  if (typeof indexedDB === 'undefined') return Promise.reject(new Error('IndexedDB is not available'));
  if (databasePromise) return databasePromise;
  databasePromise = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(READER_PROGRESS_DB_NAME, READER_DB_SCHEMA_VERSION);
    request.onupgradeneeded = (event) => {
      const database = request.result;
      if (!database.objectStoreNames.contains(PREFERENCES_STORE)) database.createObjectStore(PREFERENCES_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(EXACT_PROGRESS_STORE)) database.createObjectStore(EXACT_PROGRESS_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(PENDING_PROGRESS_STORE)) {
        const store = database.createObjectStore(PENDING_PROGRESS_STORE, { keyPath: 'key' });
        store.createIndex('by-user', 'userId', { unique: false });
      }
      if (database.objectStoreNames.contains('progress-conflicts')) database.deleteObjectStore('progress-conflicts');
      if (!database.objectStoreNames.contains(META_STORE)) database.createObjectStore(META_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(DIAGNOSTICS_STORE)) database.createObjectStore(DIAGNOSTICS_STORE, { keyPath: 'id' });
      if (!database.objectStoreNames.contains(RESOURCE_CACHE_STORE)) {
        const store = database.createObjectStore(RESOURCE_CACHE_STORE, { keyPath: 'key' });
        store.createIndex('by-user-resource', 'userResourceKey', { unique: false });
      }
      if (!database.objectStoreNames.contains(PDF_RANGE_CHUNKS_STORE)) {
        const store = database.createObjectStore(PDF_RANGE_CHUNKS_STORE, { keyPath: 'key' });
        store.createIndex('by-document', 'documentKey', { unique: false });
        store.createIndex('by-namespace', 'namespaceKey', { unique: false });
      }
      if (event.oldVersion > 0 && event.oldVersion < 2) {
        [EXACT_PROGRESS_STORE, PENDING_PROGRESS_STORE].forEach((name) => {
          if (database.objectStoreNames.contains(name)) request.transaction?.objectStore(name).clear();
        });
      }
    };
    request.onsuccess = () => {
      const database = request.result;
      database.onversionchange = () => { database.close(); databasePromise = null; };
      resolve(database);
    };
    request.onerror = () => { databasePromise = null; reject(request.error ?? new Error('Reader v4 IndexedDB open failed')); };
    request.onblocked = () => { databasePromise = null; reject(new Error('Reader v4 IndexedDB upgrade is blocked')); };
  });
  return databasePromise;
}

async function withTransaction<T>(stores: ReaderStoreName | ReaderStoreName[], mode: IDBTransactionMode, action: (store: (name: ReaderStoreName) => IDBObjectStore) => Promise<T>) {
  const database = await openDatabase();
  const transaction = database.transaction(stores, mode);
  const completed = transactionComplete(transaction);
  try {
    const result = await action((name) => transaction.objectStore(name));
    await completed;
    return result;
  } catch (error) {
    try { transaction.abort(); } catch { /* transaction already completed */ }
    await completed.catch(() => undefined);
    throw error;
  }
}

export class IndexedDbReaderStorage implements ReaderStorage, ReaderResourceCache, PdfRangeCache {
  async getPdfRangeChunk(identity: PdfRangeCacheIdentity, chunkIndex: number): Promise<CachedPdfRangeChunk | null> {
    return withTransaction(PDF_RANGE_CHUNKS_STORE, 'readwrite', async (stores) => {
      const store = stores(PDF_RANGE_CHUNKS_STORE);
      const value = await requestResult(store.get(pdfRangeChunkKey(identity, chunkIndex))) as StoredPdfRangeChunk | undefined;
      if (!value || !(value.bytes instanceof ArrayBuffer) || value.byteLength <= 0) return null;
      const updated = { ...value, lastAccessedAt: Date.now() };
      await requestResult(store.put(updated));
      return { bytes: new Uint8Array(value.bytes.slice(0)), lastAccessedAt: updated.lastAccessedAt };
    });
  }
  async putPdfRangeChunk(
    identity: PdfRangeCacheIdentity,
    chunkIndex: number,
    bytes: Uint8Array,
    protectedChunkKeys: readonly string[] = []
  ) {
    if (bytes.byteLength <= 0) return;
    const documentKey = pdfRangeDocumentKey(identity);
    const namespaceKey = pdfRangeNamespaceKey(identity);
    const key = pdfRangeChunkKey(identity, chunkIndex);
    const protectedKeys = new Set([...protectedChunkKeys, key]);
    await withTransaction(PDF_RANGE_CHUNKS_STORE, 'readwrite', async (stores) => {
      const store = stores(PDF_RANGE_CHUNKS_STORE);
      const value: StoredPdfRangeChunk = {
        key,
        documentKey,
        namespaceKey,
        chunkIndex,
        byteLength: bytes.byteLength,
        bytes: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer,
        lastAccessedAt: Date.now()
      };
      await requestResult(store.put(value));
      const documentChunks = await requestResult(store.index('by-document').getAll(documentKey)) as StoredPdfRangeChunk[];
      const removed = new Set<string>();
      let documentBytes = documentChunks.reduce((total, chunk) => total + chunk.byteLength, 0);
      for (const chunk of documentChunks.sort((left, right) => left.lastAccessedAt - right.lastAccessedAt)) {
        if (documentBytes <= PDF_RANGE_DOCUMENT_CACHE_BYTES) break;
        if (protectedKeys.has(chunk.key)) continue;
        await requestResult(store.delete(chunk.key));
        removed.add(chunk.key);
        documentBytes -= chunk.byteLength;
      }
      const namespaceChunks = (await requestResult(store.index('by-namespace').getAll(namespaceKey)) as StoredPdfRangeChunk[])
        .filter((chunk) => !removed.has(chunk.key));
      let namespaceBytes = namespaceChunks.reduce((total, chunk) => total + chunk.byteLength, 0);
      for (const chunk of namespaceChunks.sort((left, right) => left.lastAccessedAt - right.lastAccessedAt)) {
        if (namespaceBytes <= PDF_RANGE_NAMESPACE_CACHE_BYTES) break;
        if (protectedKeys.has(chunk.key)) continue;
        await requestResult(store.delete(chunk.key));
        namespaceBytes -= chunk.byteLength;
      }
    });
  }
  async deletePdfRangeNamespace(identity: Omit<PdfRangeCacheIdentity, 'resourceId' | 'assetId'>) {
    await withTransaction(PDF_RANGE_CHUNKS_STORE, 'readwrite', async (stores) => {
      const store = stores(PDF_RANGE_CHUNKS_STORE);
      const keys = await requestResult(store.index('by-namespace').getAllKeys(pdfRangeNamespaceKey(identity)));
      await Promise.all(keys.map((key) => requestResult(store.delete(key))));
    });
  }
  async getResource(identity: ReaderResourceCacheIdentity) {
    return withTransaction(RESOURCE_CACHE_STORE, 'readonly', async (stores) => {
      const value = await requestResult(stores(RESOURCE_CACHE_STORE).get(readerResourceCacheKey(identity))) as CachedReaderResource | undefined;
      return value?.blob instanceof Blob && value.blob.size > 0 ? value : null;
    });
  }
  async putResource(resource: CachedReaderResource) {
    await withTransaction(RESOURCE_CACHE_STORE, 'readwrite', async (stores) => {
      const store = stores(RESOURCE_CACHE_STORE);
      const keys = await requestResult(store.index('by-user-resource').getAllKeys(resource.userResourceKey));
      await Promise.all(keys.filter((key) => key !== resource.key).map((key) => requestResult(store.delete(key))));
      await requestResult(store.put(resource));
    });
  }
  async deleteResource(identity: ReaderResourceCacheIdentity) {
    await withTransaction(RESOURCE_CACHE_STORE, 'readwrite', async (stores) => { await requestResult(stores(RESOURCE_CACHE_STORE).delete(readerResourceCacheKey(identity))); });
  }
  async getPreference(userId: string, bookId: string) {
    return withTransaction(PREFERENCES_STORE, 'readonly', async (stores) => {
      const stored = record(await requestResult(stores(PREFERENCES_STORE).get(preferenceKey(userId, bookId))));
      return stored.preferences ? {
        key: preferenceKey(userId, bookId), userId, bookId, schemaVersion: READER_SCHEMA_VERSION,
        preferences: normalizeReaderPreferences(stored.preferences),
        updatedAt: typeof stored.updatedAt === 'number' ? stored.updatedAt : Date.now()
      } : null;
    });
  }
  async putPreference(userId: string, bookId: string, preferences: ReaderPreferences, updatedAt = Date.now()) {
    const value = { key: preferenceKey(userId, bookId), userId, bookId, schemaVersion: READER_SCHEMA_VERSION, preferences, updatedAt };
    await withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => { await requestResult(stores(PREFERENCES_STORE).put(value)); });
    return value;
  }
  async deletePreference(userId: string, bookId: string) { await withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => { await requestResult(stores(PREFERENCES_STORE).delete(preferenceKey(userId, bookId))); }); }
  async getClientId() {
    return withTransaction(META_STORE, 'readwrite', async (stores) => {
      const store = stores(META_STORE); const current = record(await requestResult(store.get('client')));
      const clientId = typeof current.clientId === 'string' && current.clientId ? current.clientId : createId('web');
      if (current.clientId !== clientId) await requestResult(store.put({ key: 'client', clientId } satisfies ClientMeta));
      return clientId;
    });
  }
  async getExactProgress(identity: ExactProgressIdentity) {
    return withTransaction(EXACT_PROGRESS_STORE, 'readwrite', async (stores) => {
      const store = stores(EXACT_PROGRESS_STORE);
      const key = exactProgressKey(identity);
      const current = await requestResult(store.get(key)) as ExactProgressRecord | undefined;
      if (current) return current;
      const legacy = ((await requestResult(store.getAll())) as ExactProgressRecord[])
        .filter((candidate) => candidate.serverIdentity === identity.serverIdentity
          && candidate.userId === identity.userId
          && candidate.clientId === identity.clientId
          && candidate.bookId === identity.bookId
          && candidate.resourceId === identity.resourceId)
        .sort((left, right) => right.capturedAtEpochMillis - left.capturedAtEpochMillis)[0];
      if (!legacy) return null;
      const migrated = { ...legacy, ...identity, key };
      await requestResult(store.put(migrated));
      if (legacy.key !== key) await requestResult(store.delete(legacy.key));
      return migrated;
    });
  }
  async putExactProgress(progress: ExactProgressRecord) { await withTransaction(EXACT_PROGRESS_STORE, 'readwrite', async (stores) => { await requestResult(stores(EXACT_PROGRESS_STORE).put(progress)); }); return progress; }
  async putExactAndPending(progress: ExactProgressRecord, mutation: PendingProgressMutation) { await withTransaction([EXACT_PROGRESS_STORE, PENDING_PROGRESS_STORE], 'readwrite', async (stores) => { await requestResult(stores(EXACT_PROGRESS_STORE).put(progress)); await requestResult(stores(PENDING_PROGRESS_STORE).put(mutation)); }); }
  async putPendingProgress(mutation: PendingProgressMutation) { await withTransaction(PENDING_PROGRESS_STORE, 'readwrite', async (stores) => { await requestResult(stores(PENDING_PROGRESS_STORE).put(mutation)); }); }
  async getPendingProgress(key: string) { return withTransaction(PENDING_PROGRESS_STORE, 'readonly', async (stores) => (await requestResult(stores(PENDING_PROGRESS_STORE).get(key)) as PendingProgressMutation | undefined) ?? null); }
  async getPendingProgressForIdentity(identity: ExactProgressIdentity) {
    return withTransaction(PENDING_PROGRESS_STORE, 'readwrite', async (stores) => {
      const store = stores(PENDING_PROGRESS_STORE);
      const key = syncStateKey(identity);
      const current = await requestResult(store.get(key)) as PendingProgressMutation | undefined;
      if (current) return current;
      const legacy = ((await requestResult(store.getAll())) as PendingProgressMutation[])
        .filter((candidate) => candidate.serverIdentity === identity.serverIdentity
          && candidate.userId === identity.userId
          && candidate.clientId === identity.clientId
          && candidate.bookId === identity.bookId
          && candidate.resourceId === identity.resourceId)
        .sort((left, right) => right.capturedAtEpochMillis - left.capturedAtEpochMillis)[0];
      if (!legacy) return null;
      const migrated = { ...legacy, key };
      await requestResult(store.put(migrated));
      if (legacy.key !== key) await requestResult(store.delete(legacy.key));
      return migrated;
    });
  }
  async listPendingProgress(userId: string) { return withTransaction(PENDING_PROGRESS_STORE, 'readonly', async (stores) => await requestResult(stores(PENDING_PROGRESS_STORE).index('by-user').getAll(userId)) as PendingProgressMutation[]); }
  async deletePendingProgress(key: string, mutationId?: string) { await withTransaction(PENDING_PROGRESS_STORE, 'readwrite', async (stores) => { const store = stores(PENDING_PROGRESS_STORE); const current = await requestResult(store.get(key)) as PendingProgressMutation | undefined; if (!mutationId || current?.mutationId === mutationId) await requestResult(store.delete(key)); }); }
  async putExactAndDeletePending(progress: ExactProgressRecord, pendingKey: string) { await withTransaction([EXACT_PROGRESS_STORE, PENDING_PROGRESS_STORE], 'readwrite', async (stores) => { await requestResult(stores(EXACT_PROGRESS_STORE).put(progress)); await requestResult(stores(PENDING_PROGRESS_STORE).delete(pendingKey)); }); }
  async addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) { const value = { ...diagnostic, id: createId('diagnostic'), createdAt: now }; await withTransaction(DIAGNOSTICS_STORE, 'readwrite', async (stores) => { await requestResult(stores(DIAGNOSTICS_STORE).put(value)); }); return value; }
  async listDiagnostics(limit = 100) { return withTransaction(DIAGNOSTICS_STORE, 'readonly', async (stores) => ((await requestResult(stores(DIAGNOSTICS_STORE).getAll())) as ReaderSyncDiagnostic[]).sort((a, b) => b.createdAt - a.createdAt).slice(0, limit)); }
  async clearAll() { const names: ReaderStoreName[] = [PREFERENCES_STORE, EXACT_PROGRESS_STORE, PENDING_PROGRESS_STORE, META_STORE, DIAGNOSTICS_STORE, RESOURCE_CACHE_STORE, PDF_RANGE_CHUNKS_STORE]; await withTransaction(names, 'readwrite', async (stores) => { await Promise.all(names.map((name) => requestResult(stores(name).clear()))); }); }
}

export { syncStateKey };
