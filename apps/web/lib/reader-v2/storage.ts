import { READER_SCHEMA_VERSION, normalizeReaderPreferences, type ReaderPreferences } from '@shuku/reader-core';
import {
  READER_V2_DB_NAME,
  READER_V2_DB_VERSION,
  preferenceKey,
  progressSlotKey,
  type ProgressMutation,
  type ProgressMutationInput,
  type QuarantinedProgress,
  type ReaderPreferenceSnapshot,
  type ReaderSyncDiagnostic,
  type ReaderSyncLease
} from './model';

const PREFERENCES_STORE = 'preferences';
const OUTBOX_STORE = 'progress-outbox';
const META_STORE = 'meta';
const LEASES_STORE = 'leases';
const QUARANTINE_STORE = 'quarantine';
const DIAGNOSTICS_STORE = 'diagnostics';

type ReaderV2StoreName =
  | typeof PREFERENCES_STORE
  | typeof OUTBOX_STORE
  | typeof META_STORE
  | typeof LEASES_STORE
  | typeof QUARANTINE_STORE
  | typeof DIAGNOSTICS_STORE;

type ClientMeta = { key: 'client'; clientId: string; sequence: number };

export interface ReaderV2Storage {
  getPreference(userId: string, workId: string): Promise<ReaderPreferenceSnapshot | null>;
  putPreference(userId: string, workId: string, preferences: ReaderPreferences, updatedAt?: number): Promise<ReaderPreferenceSnapshot>;
  deletePreference(userId: string, workId: string): Promise<void>;
  enqueueProgress(input: ProgressMutationInput, now?: number): Promise<ProgressMutation>;
  listProgress(): Promise<ProgressMutation[]>;
  compareDeleteProgress(mutationId: string): Promise<boolean>;
  markProgressRetry(mutationId: string, nextAttemptAt: number, now?: number): Promise<boolean>;
  quarantineProgress(mutation: ProgressMutation, reason: QuarantinedProgress['reason'], message: string, now?: number): Promise<void>;
  acquireProgressLease(ownerId: string, ttlMs: number, now?: number): Promise<boolean>;
  renewProgressLease(ownerId: string, ttlMs: number, now?: number): Promise<boolean>;
  releaseProgressLease(ownerId: string): Promise<void>;
  getProgressLease(): Promise<ReaderSyncLease | null>;
  addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now?: number): Promise<ReaderSyncDiagnostic>;
  listDiagnostics(limit?: number): Promise<ReaderSyncDiagnostic[]>;
  listQuarantine(limit?: number): Promise<QuarantinedProgress[]>;
  clearAll(): Promise<void>;
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

function structurallyEqual(left: unknown, right: unknown) {
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
}

/**
 * Converts the untyped IndexedDB boundary into the complete current snapshot.
 * `needsRewrite` is true for V2, partial, malformed, or non-canonical records.
 */
export function canonicalizeStoredPreferenceSnapshot(
  value: unknown,
  userId: string,
  workId: string,
  now = Date.now()
): { snapshot: ReaderPreferenceSnapshot; needsRewrite: boolean } | null {
  if (typeof value === 'undefined') return null;
  const stored = record(value);
  const storedUpdatedAt = stored.updatedAt;
  const updatedAt = typeof storedUpdatedAt === 'number' && Number.isFinite(storedUpdatedAt) && storedUpdatedAt >= 0
    ? storedUpdatedAt
    : now;
  const snapshot: ReaderPreferenceSnapshot = {
    key: preferenceKey(userId, workId),
    userId,
    workId,
    schemaVersion: READER_SCHEMA_VERSION,
    preferences: normalizeReaderPreferences(stored.preferences),
    updatedAt
  };
  return {
    snapshot,
    needsRewrite: !structurallyEqual(value, snapshot)
  };
}

export async function readStoredPreferenceSnapshot(
  value: unknown,
  userId: string,
  workId: string,
  rewrite: (snapshot: ReaderPreferenceSnapshot) => Promise<unknown>,
  now = Date.now()
) {
  const canonical = canonicalizeStoredPreferenceSnapshot(value, userId, workId, now);
  if (!canonical) return null;
  if (canonical.needsRewrite) await rewrite(canonical.snapshot);
  return canonical.snapshot;
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
    const request = indexedDB.open(READER_V2_DB_NAME, READER_V2_DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(PREFERENCES_STORE)) {
        database.createObjectStore(PREFERENCES_STORE, { keyPath: 'key' });
      }
      if (!database.objectStoreNames.contains(OUTBOX_STORE)) {
        const outbox = database.createObjectStore(OUTBOX_STORE, { keyPath: 'mutationId' });
        outbox.createIndex('by-sequence', 'clientSequence', { unique: false });
        outbox.createIndex('by-slot', 'slotKey', { unique: true });
      }
      if (!database.objectStoreNames.contains(META_STORE)) database.createObjectStore(META_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(LEASES_STORE)) database.createObjectStore(LEASES_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(QUARANTINE_STORE)) database.createObjectStore(QUARANTINE_STORE, { keyPath: 'id' });
      if (!database.objectStoreNames.contains(DIAGNOSTICS_STORE)) database.createObjectStore(DIAGNOSTICS_STORE, { keyPath: 'id' });
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
      reject(request.error ?? new Error('Reader V2 IndexedDB open failed'));
    };
    request.onblocked = () => {
      databasePromise = null;
      reject(new Error('Reader V2 IndexedDB upgrade is blocked'));
    };
  });
  return databasePromise;
}

async function withTransaction<T>(
  storeNames: ReaderV2StoreName | ReaderV2StoreName[],
  mode: IDBTransactionMode,
  action: (stores: (name: ReaderV2StoreName) => IDBObjectStore) => Promise<T>
) {
  const database = await openDatabase();
  const transaction = database.transaction(storeNames, mode);
  const completed = transactionComplete(transaction);
  const stores = (name: ReaderV2StoreName) => transaction.objectStore(name);
  try {
    const result = await action(stores);
    await completed;
    return result;
  } catch (error) {
    try {
      transaction.abort();
    } catch {
      // The transaction may already have completed or aborted.
    }
    await completed.catch(() => undefined);
    throw error;
  }
}

export class IndexedDbReaderV2Storage implements ReaderV2Storage {
  async getPreference(userId: string, workId: string) {
    return withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => {
      const store = stores(PREFERENCES_STORE);
      const value: unknown = await requestResult(store.get(preferenceKey(userId, workId)));
      return readStoredPreferenceSnapshot(
        value,
        userId,
        workId,
        (snapshot) => requestResult(store.put(snapshot))
      );
    });
  }

  async putPreference(userId: string, workId: string, preferences: ReaderPreferences, updatedAt = Date.now()) {
    const snapshot: ReaderPreferenceSnapshot = {
      key: preferenceKey(userId, workId),
      userId,
      workId,
      schemaVersion: READER_SCHEMA_VERSION,
      preferences,
      updatedAt
    };
    await withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(PREFERENCES_STORE).put(snapshot));
    });
    return snapshot;
  }

  async deletePreference(userId: string, workId: string) {
    await withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(PREFERENCES_STORE).delete(preferenceKey(userId, workId)));
    });
  }

  async enqueueProgress(input: ProgressMutationInput, now = Date.now()) {
    return withTransaction([META_STORE, OUTBOX_STORE], 'readwrite', async (stores) => {
      const metaStore = stores(META_STORE);
      const current = await requestResult(metaStore.get('client')) as ClientMeta | undefined;
      const clientId = current?.clientId ?? createId('client');
      const clientSequence = (current?.sequence ?? 0) + 1;
      await requestResult(metaStore.put({ key: 'client', clientId, sequence: clientSequence } satisfies ClientMeta));

      const outbox = stores(OUTBOX_STORE);
      const slotKey = progressSlotKey(input);
      const existing = await requestResult(outbox.index('by-slot').get(slotKey)) as ProgressMutation | undefined;
      if (existing) await requestResult(outbox.delete(existing.mutationId));

      const mutation: ProgressMutation = {
        ...input,
        schemaVersion: 2,
        mutationId: createId('progress'),
        clientId,
        clientSequence,
        slotKey,
        percent: Math.max(0, Math.min(100, Number.isFinite(input.percent) ? input.percent : 0)),
        createdAt: existing?.createdAt ?? now,
        updatedAt: now,
        retryCount: 0,
        nextAttemptAt: now
      };
      await requestResult(outbox.put(mutation));
      return mutation;
    });
  }

  async listProgress() {
    return withTransaction(OUTBOX_STORE, 'readonly', async (stores) => {
      const values = await requestResult(stores(OUTBOX_STORE).index('by-sequence').getAll()) as ProgressMutation[];
      return values.sort((left, right) => left.clientSequence - right.clientSequence);
    });
  }

  async compareDeleteProgress(mutationId: string) {
    return withTransaction(OUTBOX_STORE, 'readwrite', async (stores) => {
      const store = stores(OUTBOX_STORE);
      const current = await requestResult(store.get(mutationId)) as ProgressMutation | undefined;
      if (!current || current.mutationId !== mutationId) return false;
      await requestResult(store.delete(mutationId));
      return true;
    });
  }

  async markProgressRetry(mutationId: string, nextAttemptAt: number, now = Date.now()) {
    return withTransaction(OUTBOX_STORE, 'readwrite', async (stores) => {
      const store = stores(OUTBOX_STORE);
      const current = await requestResult(store.get(mutationId)) as ProgressMutation | undefined;
      if (!current || current.mutationId !== mutationId) return false;
      await requestResult(store.put({
        ...current,
        retryCount: current.retryCount + 1,
        nextAttemptAt,
        updatedAt: now
      }));
      return true;
    });
  }

  async quarantineProgress(mutation: ProgressMutation, reason: QuarantinedProgress['reason'], message: string, now = Date.now()) {
    await withTransaction([OUTBOX_STORE, QUARANTINE_STORE], 'readwrite', async (stores) => {
      const quarantine: QuarantinedProgress = {
        id: createId('quarantine'),
        mutation,
        reason,
        message,
        createdAt: now
      };
      await requestResult(stores(QUARANTINE_STORE).put(quarantine));
      const current = await requestResult(stores(OUTBOX_STORE).get(mutation.mutationId)) as ProgressMutation | undefined;
      if (current?.mutationId === mutation.mutationId) await requestResult(stores(OUTBOX_STORE).delete(mutation.mutationId));
    });
  }

  async acquireProgressLease(ownerId: string, ttlMs: number, now = Date.now()) {
    return withTransaction(LEASES_STORE, 'readwrite', async (stores) => {
      const store = stores(LEASES_STORE);
      const current = await requestResult(store.get('progress-sync')) as ReaderSyncLease | undefined;
      if (current && current.ownerId !== ownerId && current.expiresAt > now) return false;
      await requestResult(store.put({ key: 'progress-sync', ownerId, expiresAt: now + ttlMs, updatedAt: now } satisfies ReaderSyncLease));
      return true;
    });
  }

  async renewProgressLease(ownerId: string, ttlMs: number, now = Date.now()) {
    return withTransaction(LEASES_STORE, 'readwrite', async (stores) => {
      const store = stores(LEASES_STORE);
      const current = await requestResult(store.get('progress-sync')) as ReaderSyncLease | undefined;
      if (!current || current.ownerId !== ownerId || current.expiresAt <= now) return false;
      await requestResult(store.put({ ...current, expiresAt: now + ttlMs, updatedAt: now }));
      return true;
    });
  }

  async releaseProgressLease(ownerId: string) {
    await withTransaction(LEASES_STORE, 'readwrite', async (stores) => {
      const store = stores(LEASES_STORE);
      const current = await requestResult(store.get('progress-sync')) as ReaderSyncLease | undefined;
      if (current?.ownerId === ownerId) await requestResult(store.delete('progress-sync'));
    });
  }

  async getProgressLease() {
    return withTransaction(LEASES_STORE, 'readonly', async (stores) => {
      const value = await requestResult(stores(LEASES_STORE).get('progress-sync')) as ReaderSyncLease | undefined;
      return value ?? null;
    });
  }

  async addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) {
    const value: ReaderSyncDiagnostic = { ...diagnostic, id: createId('diagnostic'), createdAt: now };
    await withTransaction(DIAGNOSTICS_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(DIAGNOSTICS_STORE).put(value));
    });
    return value;
  }

  async listDiagnostics(limit = 100) {
    return withTransaction(DIAGNOSTICS_STORE, 'readonly', async (stores) => {
      const values = await requestResult(stores(DIAGNOSTICS_STORE).getAll()) as ReaderSyncDiagnostic[];
      return values.sort((left, right) => right.createdAt - left.createdAt).slice(0, limit);
    });
  }

  async listQuarantine(limit = 100) {
    return withTransaction(QUARANTINE_STORE, 'readonly', async (stores) => {
      const values = await requestResult(stores(QUARANTINE_STORE).getAll()) as QuarantinedProgress[];
      return values.sort((left, right) => right.createdAt - left.createdAt).slice(0, limit);
    });
  }

  async clearAll() {
    const storeNames: ReaderV2StoreName[] = [
      PREFERENCES_STORE,
      OUTBOX_STORE,
      META_STORE,
      LEASES_STORE,
      QUARANTINE_STORE,
      DIAGNOSTICS_STORE
    ];
    await withTransaction(
      storeNames,
      'readwrite',
      async (stores) => {
        await Promise.all(storeNames.map((name) => requestResult(stores(name).clear())));
      }
    );
  }
}
