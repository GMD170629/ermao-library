import {
  normalizeReaderPreferences,
  READER_PREFERENCES_VERSION,
  type ReaderPreferences
} from '@shuku/reader-core';
import {
  parseReaderV5PositionReport,
  type ReaderV5PendingMutation,
  type ReaderV5ProgressIdentity,
  type ReaderV5ProgressRecord
} from './v5-wire';

/**
 * v5 owns a separate database. Opening it never opens, enumerates, migrates,
 * or clears any legacy database/stores.
 */
export const READER_V5_DB_NAME = 'shuku-reader-v5';
export const READER_V5_DB_SCHEMA_VERSION = 1;

const PREFERENCES_STORE = 'preferences';
const META_STORE = 'meta';
const DIAGNOSTICS_STORE = 'diagnostics';
const POSITION_STORE = 'position';
const PENDING_POSITION_STORE = 'pending-position';

type V5StoreName = typeof PREFERENCES_STORE | typeof META_STORE | typeof DIAGNOSTICS_STORE
  | typeof POSITION_STORE | typeof PENDING_POSITION_STORE;
type ClientMeta = { key: 'client'; clientId: string };

export type ReaderV5PreferenceSnapshot = Readonly<{
  key: string;
  userId: string;
  bookId: string;
  schemaVersion: typeof READER_PREFERENCES_VERSION;
  preferences: ReaderPreferences;
  updatedAt: number;
}>;

export type ReaderV5SyncDiagnostic = Readonly<{
  id: string;
  level: 'info' | 'warning' | 'error';
  code: string;
  message: string;
  createdAt: number;
  data?: Record<string, unknown>;
}>;

/** The v5 key codec is deliberately owned by the v5 persistence boundary. */
function encodeKeyPart(value: string) {
  return `${value.length}:${value}`;
}

export function readerV5ProgressKey(identity: ReaderV5ProgressIdentity) {
  return [identity.serverIdentity, identity.userId, identity.clientId, identity.bookId, identity.resourceId]
    .map(encodeKeyPart)
    .join('|');
}

export function readerV5PendingKey(identity: ReaderV5ProgressIdentity) {
  return readerV5ProgressKey(identity);
}

export function readerV5PreferenceKey(userId: string, bookId: string) {
  return `${encodeURIComponent(userId)}::${encodeURIComponent(bookId)}`;
}

export function currentReaderServerIdentity() {
  if (typeof window !== 'undefined' && window.location.origin) return window.location.origin;
  return 'same-origin';
}

function createId(prefix: string) {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}_${suffix}`;
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function requestResult<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Reader v5 IndexedDB request failed'));
  });
}

function transactionComplete(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error('Reader v5 IndexedDB transaction failed'));
    transaction.onabort = () => reject(transaction.error ?? new Error('Reader v5 IndexedDB transaction aborted'));
  });
}

function storedIdentity(value: unknown): ReaderV5ProgressIdentity | null {
  const item = record(value);
  if (typeof item.serverIdentity !== 'string' || !item.serverIdentity
    || typeof item.userId !== 'string' || !item.userId
    || typeof item.clientId !== 'string' || !item.clientId
    || typeof item.bookId !== 'string' || !item.bookId
    || typeof item.resourceId !== 'string' || !item.resourceId) return null;
  return {
    serverIdentity: item.serverIdentity,
    userId: item.userId,
    clientId: item.clientId,
    bookId: item.bookId,
    resourceId: item.resourceId
  };
}

function isIdentity(value: unknown, identity: ReaderV5ProgressIdentity) {
  const stored = storedIdentity(value);
  return stored !== null
    && stored.serverIdentity === identity.serverIdentity
    && stored.userId === identity.userId
    && stored.clientId === identity.clientId
    && stored.bookId === identity.bookId
    && stored.resourceId === identity.resourceId;
}

function validMutationId(value: unknown): value is string {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(value);
}

function parseStoredProgress(value: unknown, identity?: ReaderV5ProgressIdentity): ReaderV5ProgressRecord | null {
  const item = record(value);
  const stored = storedIdentity(value);
  const position = parseReaderV5PositionReport(item.position);
  if (!position || !stored || item.schemaVersion !== 5
    || item.key !== readerV5ProgressKey(stored)
    || !validMutationId(item.mutationId)
    || typeof item.revision !== 'number' || !Number.isSafeInteger(item.revision) || item.revision < 0
    || typeof item.capturedAtEpochMillis !== 'number'
    || !Number.isSafeInteger(item.capturedAtEpochMillis) || item.capturedAtEpochMillis < 0
    || (identity && !isIdentity(stored, identity))) return null;
  return {
    ...stored,
    key: item.key,
    schemaVersion: 5,
    mutationId: item.mutationId,
    revision: item.revision,
    capturedAtEpochMillis: item.capturedAtEpochMillis,
    position
  };
}

function parseStoredPending(value: unknown): ReaderV5PendingMutation | null {
  const item = record(value);
  const stored = storedIdentity(value);
  const position = parseReaderV5PositionReport(item.position);
  if (!position || !stored || item.schemaVersion !== 5
    || item.key !== readerV5PendingKey(stored)
    || !validMutationId(item.mutationId)
    || typeof item.capturedAtEpochMillis !== 'number'
    || !Number.isSafeInteger(item.capturedAtEpochMillis) || item.capturedAtEpochMillis < 0) return null;
  return {
    ...stored,
    key: item.key,
    schemaVersion: 5,
    mutationId: item.mutationId,
    capturedAtEpochMillis: item.capturedAtEpochMillis,
    position
  };
}

let databasePromise: Promise<IDBDatabase> | null = null;

function openDatabase() {
  if (typeof indexedDB === 'undefined') return Promise.reject(new Error('IndexedDB is not available'));
  if (databasePromise) return databasePromise;
  databasePromise = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(READER_V5_DB_NAME, READER_V5_DB_SCHEMA_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(PREFERENCES_STORE)) database.createObjectStore(PREFERENCES_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(META_STORE)) database.createObjectStore(META_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(DIAGNOSTICS_STORE)) database.createObjectStore(DIAGNOSTICS_STORE, { keyPath: 'id' });
      if (!database.objectStoreNames.contains(POSITION_STORE)) database.createObjectStore(POSITION_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(PENDING_POSITION_STORE)) {
        const store = database.createObjectStore(PENDING_POSITION_STORE, { keyPath: 'key' });
        store.createIndex('by-user', 'userId', { unique: false });
      }
    };
    request.onsuccess = () => {
      const database = request.result;
      database.onversionchange = () => {
        database.close();
        databasePromise = null;
      };
      resolve(database);
    };
    request.onerror = () => {
      databasePromise = null;
      reject(request.error ?? new Error('Reader v5 IndexedDB open failed'));
    };
    request.onblocked = () => {
      databasePromise = null;
      reject(new Error('Reader v5 IndexedDB upgrade is blocked'));
    };
  });
  return databasePromise;
}

async function withTransaction<T>(
  stores: V5StoreName | V5StoreName[],
  mode: IDBTransactionMode,
  action: (store: (name: V5StoreName) => IDBObjectStore) => Promise<T>
) {
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

export interface ReaderV5Storage {
  getClientId(): Promise<string>;
  getV5Progress(identity: ReaderV5ProgressIdentity): Promise<ReaderV5ProgressRecord | null>;
  putV5Progress(progress: ReaderV5ProgressRecord): Promise<ReaderV5ProgressRecord>;
  putV5ExactAndPending(progress: ReaderV5ProgressRecord, mutation: ReaderV5PendingMutation): Promise<void>;
  putV5PendingProgress(mutation: ReaderV5PendingMutation): Promise<void>;
  getV5PendingProgress(key: string): Promise<ReaderV5PendingMutation | null>;
  getV5PendingProgressForIdentity(identity: ReaderV5ProgressIdentity): Promise<ReaderV5PendingMutation | null>;
  listV5PendingProgress(userId: string): Promise<ReaderV5PendingMutation[]>;
  deleteV5PendingProgress(key: string, mutationId?: string): Promise<void>;
  putV5ExactAndDeletePending(progress: ReaderV5ProgressRecord, pendingKey: string, mutationId: string): Promise<boolean>;
  getPreference(userId: string, bookId: string): Promise<ReaderV5PreferenceSnapshot | null>;
  putPreference(userId: string, bookId: string, preferences: ReaderPreferences, updatedAt?: number): Promise<ReaderV5PreferenceSnapshot>;
  deletePreference(userId: string, bookId: string): Promise<void>;
  addDiagnostic(diagnostic: Omit<ReaderV5SyncDiagnostic, 'id' | 'createdAt'>, now?: number): Promise<ReaderV5SyncDiagnostic>;
  listDiagnostics(limit?: number): Promise<ReaderV5SyncDiagnostic[]>;
  clearAll(): Promise<void>;
}

export class ReaderV5IndexedDbStorage implements ReaderV5Storage {
  async getPreference(userId: string, bookId: string) {
    return withTransaction(PREFERENCES_STORE, 'readonly', async (stores) => {
      const stored = record(await requestResult(stores(PREFERENCES_STORE).get(readerV5PreferenceKey(userId, bookId))));
      const preferences = record(stored.preferences);
      if (stored.schemaVersion !== READER_PREFERENCES_VERSION || preferences.schemaVersion !== READER_PREFERENCES_VERSION) return null;
      return {
        key: readerV5PreferenceKey(userId, bookId),
        userId,
        bookId,
        schemaVersion: READER_PREFERENCES_VERSION,
        preferences: normalizeReaderPreferences(preferences),
        updatedAt: typeof stored.updatedAt === 'number' ? stored.updatedAt : Date.now()
      };
    });
  }

  async putPreference(userId: string, bookId: string, preferences: ReaderPreferences, updatedAt = Date.now()) {
    const value: ReaderV5PreferenceSnapshot = {
      key: readerV5PreferenceKey(userId, bookId),
      userId,
      bookId,
      schemaVersion: READER_PREFERENCES_VERSION,
      preferences,
      updatedAt
    };
    await withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(PREFERENCES_STORE).put(value));
    });
    return value;
  }

  async deletePreference(userId: string, bookId: string) {
    await withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(PREFERENCES_STORE).delete(readerV5PreferenceKey(userId, bookId)));
    });
  }

  async getClientId() {
    return withTransaction(META_STORE, 'readwrite', async (stores) => {
      const store = stores(META_STORE);
      const current = record(await requestResult(store.get('client')));
      const clientId = typeof current.clientId === 'string' && current.clientId ? current.clientId : createId('web');
      if (current.clientId !== clientId) await requestResult(store.put({ key: 'client', clientId } satisfies ClientMeta));
      return clientId;
    });
  }

  async getV5Progress(identity: ReaderV5ProgressIdentity) {
    return withTransaction(POSITION_STORE, 'readonly', async (stores) => (
      parseStoredProgress(await requestResult(stores(POSITION_STORE).get(readerV5ProgressKey(identity))), identity)
    ));
  }

  async putV5Progress(progress: ReaderV5ProgressRecord) {
    await withTransaction(POSITION_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(POSITION_STORE).put(progress));
    });
    return progress;
  }

  async putV5ExactAndPending(progress: ReaderV5ProgressRecord, mutation: ReaderV5PendingMutation) {
    await withTransaction([POSITION_STORE, PENDING_POSITION_STORE], 'readwrite', async (stores) => {
      await requestResult(stores(POSITION_STORE).put(progress));
      await requestResult(stores(PENDING_POSITION_STORE).put(mutation));
    });
  }

  async putV5PendingProgress(mutation: ReaderV5PendingMutation) {
    await withTransaction(PENDING_POSITION_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(PENDING_POSITION_STORE).put(mutation));
    });
  }

  async getV5PendingProgress(key: string) {
    return withTransaction(PENDING_POSITION_STORE, 'readonly', async (stores) => (
      parseStoredPending(await requestResult(stores(PENDING_POSITION_STORE).get(key)))
    ));
  }

  async getV5PendingProgressForIdentity(identity: ReaderV5ProgressIdentity) {
    return withTransaction(PENDING_POSITION_STORE, 'readonly', async (stores) => {
      const pending = parseStoredPending(await requestResult(stores(PENDING_POSITION_STORE).get(readerV5PendingKey(identity))));
      return pending && isIdentity(pending, identity) ? pending : null;
    });
  }

  async listV5PendingProgress(userId: string) {
    return withTransaction(PENDING_POSITION_STORE, 'readonly', async (stores) => {
      const stored = await requestResult(stores(PENDING_POSITION_STORE).index('by-user').getAll(userId));
      return (stored as unknown[]).map(parseStoredPending).filter((item): item is ReaderV5PendingMutation => item !== null);
    });
  }

  async deleteV5PendingProgress(key: string, mutationId?: string) {
    await withTransaction(PENDING_POSITION_STORE, 'readwrite', async (stores) => {
      const store = stores(PENDING_POSITION_STORE);
      const current = parseStoredPending(await requestResult(store.get(key)));
      if (!mutationId || current?.mutationId === mutationId) await requestResult(store.delete(key));
    });
  }

  async putV5ExactAndDeletePending(progress: ReaderV5ProgressRecord, pendingKey: string, mutationId: string) {
    return withTransaction([POSITION_STORE, PENDING_POSITION_STORE], 'readwrite', async (stores) => {
      const pendingStore = stores(PENDING_POSITION_STORE);
      const current = parseStoredPending(await requestResult(pendingStore.get(pendingKey)));
      if (current?.mutationId !== mutationId) return false;
      await requestResult(stores(POSITION_STORE).put(progress));
      await requestResult(pendingStore.delete(pendingKey));
      return true;
    });
  }

  async addDiagnostic(diagnostic: Omit<ReaderV5SyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) {
    const value = { ...diagnostic, id: createId('diagnostic'), createdAt: now };
    await withTransaction(DIAGNOSTICS_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(DIAGNOSTICS_STORE).put(value));
    });
    return value;
  }

  async listDiagnostics(limit = 100) {
    return withTransaction(DIAGNOSTICS_STORE, 'readonly', async (stores) => (
      (await requestResult(stores(DIAGNOSTICS_STORE).getAll()) as ReaderV5SyncDiagnostic[])
        .sort((left, right) => right.createdAt - left.createdAt)
        .slice(0, limit)
    ));
  }

  async clearAll() {
    const storesToClear: V5StoreName[] = [PREFERENCES_STORE, META_STORE, DIAGNOSTICS_STORE, POSITION_STORE, PENDING_POSITION_STORE];
    await withTransaction(storesToClear, 'readwrite', async (stores) => {
      await Promise.all(storesToClear.map((name) => requestResult(stores(name).clear())));
    });
  }
}
