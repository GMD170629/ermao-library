import { READER_SCHEMA_VERSION, normalizeReaderPreferences, type ReaderPreferences } from '@shuku/reader-core';
import {
  READER_DB_SCHEMA_VERSION,
  READER_PROGRESS_DB_NAME,
  exactProgressKey,
  preferenceKey,
  syncStateKey,
  type ExactProgressIdentity,
  type ExactProgressRecord,
  type PendingProgressMutation,
  type PersistedProgressConflict,
  type ReaderPreferenceSnapshot,
  type ReaderSyncDiagnostic
} from './model';
import {
  readerBookCacheKey,
  type CachedReaderBookFile,
  type ReaderBookCache,
  type ReaderBookCacheIdentity
} from './book-cache';

const PREFERENCES_STORE = 'preferences';
const EXACT_PROGRESS_STORE = 'exact-progress';
const PENDING_PROGRESS_STORE = 'pending-progress';
const CONFLICT_STORE = 'progress-conflicts';
const META_STORE = 'meta';
const DIAGNOSTICS_STORE = 'diagnostics';
const BOOK_FILES_STORE = 'book-files';

type ReaderStoreName = typeof PREFERENCES_STORE | typeof EXACT_PROGRESS_STORE
  | typeof PENDING_PROGRESS_STORE | typeof CONFLICT_STORE | typeof META_STORE
  | typeof DIAGNOSTICS_STORE | typeof BOOK_FILES_STORE;
type ClientMeta = { key: 'client'; clientId: string };

export interface ReaderStorage {
  getPreference(userId: string, workId: string): Promise<ReaderPreferenceSnapshot | null>;
  putPreference(userId: string, workId: string, preferences: ReaderPreferences, updatedAt?: number): Promise<ReaderPreferenceSnapshot>;
  deletePreference(userId: string, workId: string): Promise<void>;
  getClientId(): Promise<string>;
  getExactProgress(identity: ExactProgressIdentity): Promise<ExactProgressRecord | null>;
  putExactProgress(progress: ExactProgressRecord): Promise<ExactProgressRecord>;
  putExactAndPending(progress: ExactProgressRecord, mutation: PendingProgressMutation): Promise<void>;
  putPendingProgress(mutation: PendingProgressMutation): Promise<void>;
  getPendingProgress(key: string): Promise<PendingProgressMutation | null>;
  listPendingProgress(userId: string): Promise<PendingProgressMutation[]>;
  deletePendingProgress(key: string, mutationId?: string): Promise<void>;
  putProgressConflict(conflict: PersistedProgressConflict): Promise<void>;
  getProgressConflict(key: string): Promise<PersistedProgressConflict | null>;
  deleteProgressConflict(key: string): Promise<void>;
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
      if (!database.objectStoreNames.contains(CONFLICT_STORE)) database.createObjectStore(CONFLICT_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(META_STORE)) database.createObjectStore(META_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(DIAGNOSTICS_STORE)) database.createObjectStore(DIAGNOSTICS_STORE, { keyPath: 'id' });
      if (!database.objectStoreNames.contains(BOOK_FILES_STORE)) {
        const store = database.createObjectStore(BOOK_FILES_STORE, { keyPath: 'key' });
        store.createIndex('by-user-volume', 'userVolumeKey', { unique: false });
      }
      if (event.oldVersion > 0 && event.oldVersion < 2) {
        [EXACT_PROGRESS_STORE, PENDING_PROGRESS_STORE, CONFLICT_STORE].forEach((name) => {
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

export class IndexedDbReaderStorage implements ReaderStorage, ReaderBookCache {
  async getBookFile(identity: ReaderBookCacheIdentity) {
    return withTransaction(BOOK_FILES_STORE, 'readonly', async (stores) => {
      const value = await requestResult(stores(BOOK_FILES_STORE).get(readerBookCacheKey(identity))) as CachedReaderBookFile | undefined;
      return value?.blob instanceof Blob && value.blob.size > 0 ? value : null;
    });
  }
  async putBookFile(file: CachedReaderBookFile) {
    await withTransaction(BOOK_FILES_STORE, 'readwrite', async (stores) => {
      const store = stores(BOOK_FILES_STORE);
      const keys = await requestResult(store.index('by-user-volume').getAllKeys(file.userVolumeKey));
      await Promise.all(keys.filter((key) => key !== file.key).map((key) => requestResult(store.delete(key))));
      await requestResult(store.put(file));
    });
  }
  async deleteBookFile(identity: ReaderBookCacheIdentity) {
    await withTransaction(BOOK_FILES_STORE, 'readwrite', async (stores) => { await requestResult(stores(BOOK_FILES_STORE).delete(readerBookCacheKey(identity))); });
  }
  async getPreference(userId: string, workId: string) {
    return withTransaction(PREFERENCES_STORE, 'readonly', async (stores) => {
      const stored = record(await requestResult(stores(PREFERENCES_STORE).get(preferenceKey(userId, workId))));
      return stored.preferences ? {
        key: preferenceKey(userId, workId), userId, workId, schemaVersion: READER_SCHEMA_VERSION,
        preferences: normalizeReaderPreferences(stored.preferences),
        updatedAt: typeof stored.updatedAt === 'number' ? stored.updatedAt : Date.now()
      } : null;
    });
  }
  async putPreference(userId: string, workId: string, preferences: ReaderPreferences, updatedAt = Date.now()) {
    const value = { key: preferenceKey(userId, workId), userId, workId, schemaVersion: READER_SCHEMA_VERSION, preferences, updatedAt };
    await withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => { await requestResult(stores(PREFERENCES_STORE).put(value)); });
    return value;
  }
  async deletePreference(userId: string, workId: string) { await withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => { await requestResult(stores(PREFERENCES_STORE).delete(preferenceKey(userId, workId))); }); }
  async getClientId() {
    return withTransaction(META_STORE, 'readwrite', async (stores) => {
      const store = stores(META_STORE); const current = record(await requestResult(store.get('client')));
      const clientId = typeof current.clientId === 'string' && current.clientId ? current.clientId : createId('web');
      if (current.clientId !== clientId) await requestResult(store.put({ key: 'client', clientId } satisfies ClientMeta));
      return clientId;
    });
  }
  async getExactProgress(identity: ExactProgressIdentity) { return withTransaction(EXACT_PROGRESS_STORE, 'readonly', async (stores) => (await requestResult(stores(EXACT_PROGRESS_STORE).get(exactProgressKey(identity))) as ExactProgressRecord | undefined) ?? null); }
  async putExactProgress(progress: ExactProgressRecord) { await withTransaction(EXACT_PROGRESS_STORE, 'readwrite', async (stores) => { await requestResult(stores(EXACT_PROGRESS_STORE).put(progress)); }); return progress; }
  async putExactAndPending(progress: ExactProgressRecord, mutation: PendingProgressMutation) { await withTransaction([EXACT_PROGRESS_STORE, PENDING_PROGRESS_STORE], 'readwrite', async (stores) => { await requestResult(stores(EXACT_PROGRESS_STORE).put(progress)); await requestResult(stores(PENDING_PROGRESS_STORE).put(mutation)); }); }
  async putPendingProgress(mutation: PendingProgressMutation) { await withTransaction(PENDING_PROGRESS_STORE, 'readwrite', async (stores) => { await requestResult(stores(PENDING_PROGRESS_STORE).put(mutation)); }); }
  async getPendingProgress(key: string) { return withTransaction(PENDING_PROGRESS_STORE, 'readonly', async (stores) => (await requestResult(stores(PENDING_PROGRESS_STORE).get(key)) as PendingProgressMutation | undefined) ?? null); }
  async listPendingProgress(userId: string) { return withTransaction(PENDING_PROGRESS_STORE, 'readonly', async (stores) => await requestResult(stores(PENDING_PROGRESS_STORE).index('by-user').getAll(userId)) as PendingProgressMutation[]); }
  async deletePendingProgress(key: string, mutationId?: string) { await withTransaction(PENDING_PROGRESS_STORE, 'readwrite', async (stores) => { const store = stores(PENDING_PROGRESS_STORE); const current = await requestResult(store.get(key)) as PendingProgressMutation | undefined; if (!mutationId || current?.mutationId === mutationId) await requestResult(store.delete(key)); }); }
  async putProgressConflict(conflict: PersistedProgressConflict) { await withTransaction(CONFLICT_STORE, 'readwrite', async (stores) => { await requestResult(stores(CONFLICT_STORE).put(conflict)); }); }
  async getProgressConflict(key: string) { return withTransaction(CONFLICT_STORE, 'readonly', async (stores) => (await requestResult(stores(CONFLICT_STORE).get(key)) as PersistedProgressConflict | undefined) ?? null); }
  async deleteProgressConflict(key: string) { await withTransaction(CONFLICT_STORE, 'readwrite', async (stores) => { await requestResult(stores(CONFLICT_STORE).delete(key)); }); }
  async addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) { const value = { ...diagnostic, id: createId('diagnostic'), createdAt: now }; await withTransaction(DIAGNOSTICS_STORE, 'readwrite', async (stores) => { await requestResult(stores(DIAGNOSTICS_STORE).put(value)); }); return value; }
  async listDiagnostics(limit = 100) { return withTransaction(DIAGNOSTICS_STORE, 'readonly', async (stores) => ((await requestResult(stores(DIAGNOSTICS_STORE).getAll())) as ReaderSyncDiagnostic[]).sort((a, b) => b.createdAt - a.createdAt).slice(0, limit)); }
  async clearAll() { const names: ReaderStoreName[] = [PREFERENCES_STORE, EXACT_PROGRESS_STORE, PENDING_PROGRESS_STORE, CONFLICT_STORE, META_STORE, DIAGNOSTICS_STORE, BOOK_FILES_STORE]; await withTransaction(names, 'readwrite', async (stores) => { await Promise.all(names.map((name) => requestResult(stores(name).clear()))); }); }
}

export { syncStateKey };
