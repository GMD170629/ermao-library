import {
  READER_SCHEMA_VERSION,
  normalizeReaderPreferences,
  type FoliateProgressSnapshot,
  type ReaderPreferences,
  type ReflowableFormat
} from '@shuku/reader-core';
import {
  READER_PROGRESS_DB_NAME,
  READER_DB_SCHEMA_VERSION,
  currentReaderServerIdentity,
  exactProgressKey,
  localContentFingerprintKey,
  normalizedPercent,
  preferenceKey,
  type AudioProgressLocation,
  type ExactProgressIdentity,
  type ExactProgressRecord,
  type ReaderPreferenceSnapshot,
  type ReaderProgressLocation,
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
const META_STORE = 'meta';
const DIAGNOSTICS_STORE = 'diagnostics';
const BOOK_FILES_STORE = 'book-files';

// These stores only exist long enough for the v3 -> v4 versionchange
// transaction to copy the latest exact position and remove durable syncing.
const LEGACY_OUTBOX_STORE = 'progress-outbox';
const LEGACY_LEASES_STORE = 'leases';
const LEGACY_QUARANTINE_STORE = 'quarantine';

type ReaderStoreName =
  | typeof PREFERENCES_STORE
  | typeof EXACT_PROGRESS_STORE
  | typeof META_STORE
  | typeof DIAGNOSTICS_STORE
  | typeof BOOK_FILES_STORE;

type ClientMeta = { key: 'client'; clientId: string };

export interface ReaderStorage {
  getPreference(userId: string, workId: string): Promise<ReaderPreferenceSnapshot | null>;
  putPreference(userId: string, workId: string, preferences: ReaderPreferences, updatedAt?: number): Promise<ReaderPreferenceSnapshot>;
  deletePreference(userId: string, workId: string): Promise<void>;
  getClientId(): Promise<string>;
  getExactProgress(identity: ExactProgressIdentity): Promise<ExactProgressRecord | null>;
  putExactProgress(progress: ExactProgressRecord): Promise<ExactProgressRecord>;
  addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now?: number): Promise<ReaderSyncDiagnostic>;
  listDiagnostics(limit?: number): Promise<ReaderSyncDiagnostic[]>;
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

function finiteNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function nonEmptyString(value: unknown) {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function optionalProgressPair(value: unknown): { current: number; total: number } | undefined {
  const item = record(value);
  const current = finiteNumber(item.current);
  const total = finiteNumber(item.total);
  if (current === undefined || total === undefined || current < 0 || total < 0) return undefined;
  return { current, total };
}

function optionalFoliateProgress(value: unknown): FoliateProgressSnapshot | undefined {
  const item = record(value);
  const continuous = record(item.continuous);
  const sectionFraction = finiteNumber(continuous.sectionFraction);
  const section = optionalProgressPair(item.section);
  const locationValue = record(item.location);
  const locationCurrent = finiteNumber(locationValue.current);
  const locationNext = finiteNumber(locationValue.next);
  const locationTotal = finiteNumber(locationValue.total);
  const location = locationCurrent !== undefined && locationNext !== undefined && locationTotal !== undefined
    ? { current: locationCurrent, next: locationNext, total: locationTotal }
    : undefined;
  const tocValue = record(item.toc);
  const tocIndex = finiteNumber(tocValue.index);
  const tocTitle = nonEmptyString(tocValue.title);
  const toc = tocIndex !== undefined && tocTitle
    ? {
        index: tocIndex,
        title: tocTitle,
        ...(nonEmptyString(tocValue.href) ? { href: nonEmptyString(tocValue.href) } : {}),
        ...(nonEmptyString(tocValue.navigationKey) ? { navigationKey: nonEmptyString(tocValue.navigationKey) } : {})
      }
    : undefined;
  const parsed: FoliateProgressSnapshot = {
    ...(sectionFraction !== undefined && sectionFraction >= 0 && sectionFraction <= 1
      ? { continuous: { sectionFraction } }
      : {}),
    ...(section ? { section } : {}),
    ...(location ? { location } : {}),
    ...(toc ? { toc } : {}),
    ...(nonEmptyString(item.navigationFingerprint)
      ? { navigationFingerprint: nonEmptyString(item.navigationFingerprint) }
      : {})
  };
  return Object.keys(parsed).length ? parsed : undefined;
}

function reflowableFormat(value: unknown): ReflowableFormat | undefined {
  return value === 'epub' || value === 'mobi' || value === 'azw' || value === 'azw3'
    || value === 'prc' || value === 'fb2' || value === 'txt'
    ? value
    : undefined;
}

function parseProgressLocation(value: unknown): ReaderProgressLocation | null {
  const item = record(value);
  if (item.kind === 'audio') {
    const volumeId = nonEmptyString(item.volumeId);
    const fileId = nonEmptyString(item.fileId);
    const positionMs = finiteNumber(item.positionMs);
    if (!volumeId || !fileId || positionMs === undefined || positionMs < 0) return null;
    return {
      kind: 'audio',
      volumeId,
      fileId,
      chapterId: nonEmptyString(item.chapterId) ?? null,
      positionMs
    } satisfies AudioProgressLocation;
  }
  if (item.kind === 'comic') {
    const volumeId = nonEmptyString(item.volumeId);
    const pageIndex = finiteNumber(item.pageIndex);
    return volumeId && pageIndex !== undefined && pageIndex >= 1
      ? { kind: 'comic', volumeId, pageIndex }
      : null;
  }
  if (item.kind === 'pdf') {
    const pageNumber = finiteNumber(item.pageNumber);
    return pageNumber !== undefined && pageNumber >= 1 ? { kind: 'pdf', pageNumber } : null;
  }
  if (item.kind === 'epub') {
    const cfi = nonEmptyString(item.cfi);
    const href = nonEmptyString(item.href);
    const spineIndex = finiteNumber(item.spineIndex);
    const progression = finiteNumber(item.progression);
    if (!cfi && !href && spineIndex === undefined && progression === undefined) return null;
    return { kind: 'epub', cfi, href, spineIndex, progression };
  }
  if (item.kind === 'reflowable') {
    const format = reflowableFormat(item.format);
    if (!format) return null;
    const cfi = nonEmptyString(item.cfi);
    const href = nonEmptyString(item.href);
    const progression = finiteNumber(item.progression);
    const foliate = optionalFoliateProgress(item.foliate);
    if (!cfi && !href && progression === undefined && !foliate) return null;
    return { kind: 'reflowable', format, cfi, href, progression, ...(foliate ? { foliate } : {}) };
  }
  return null;
}

function structurallyEqual(left: unknown, right: unknown) {
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
}

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
  return { snapshot, needsRewrite: !structurallyEqual(value, snapshot) };
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

function parseExactProgress(value: unknown, identity: ExactProgressIdentity): ExactProgressRecord | null {
  const item = record(value);
  const location = parseProgressLocation(item.location);
  const workId = nonEmptyString(item.workId);
  const updatedAtEpochMillis = finiteNumber(item.updatedAtEpochMillis);
  if (!location || !workId || updatedAtEpochMillis === undefined || updatedAtEpochMillis < 0) return null;
  if (
    item.key !== exactProgressKey(identity)
    || item.serverIdentity !== identity.serverIdentity
    || item.userId !== identity.userId
    || item.clientId !== identity.clientId
    || item.volumeId !== identity.volumeId
    || item.localContentFingerprint !== identity.localContentFingerprint
  ) return null;
  return {
    ...identity,
    key: exactProgressKey(identity),
    schemaVersion: 1,
    workId,
    location,
    percent: normalizedPercent(finiteNumber(item.percent) ?? null),
    updatedAtEpochMillis
  };
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

function deleteLegacySyncStores(database: IDBDatabase) {
  for (const storeName of [LEGACY_OUTBOX_STORE, LEGACY_LEASES_STORE, LEGACY_QUARANTINE_STORE]) {
    if (database.objectStoreNames.contains(storeName)) database.deleteObjectStore(storeName);
  }
}

function migrateLegacyOutbox(database: IDBDatabase, transaction: IDBTransaction) {
  if (!database.objectStoreNames.contains(LEGACY_OUTBOX_STORE)) {
    deleteLegacySyncStores(database);
    return;
  }
  const outbox = transaction.objectStore(LEGACY_OUTBOX_STORE);
  const exactStore = transaction.objectStore(EXACT_PROGRESS_STORE);
  const cursorRequest = outbox.openCursor();
  cursorRequest.onerror = () => transaction.abort();
  cursorRequest.onsuccess = () => {
    const cursor = cursorRequest.result;
    if (!cursor) {
      deleteLegacySyncStores(database);
      return;
    }
    const legacy = record(cursor.value);
    const serverIdentity = currentReaderServerIdentity();
    const userId = nonEmptyString(legacy.userId);
    const clientId = nonEmptyString(legacy.clientId);
    const workId = nonEmptyString(legacy.workId);
    const volumeId = nonEmptyString(legacy.volumeId);
    const serverContentFingerprint = nonEmptyString(legacy.contentFingerprint);
    const rawLocationFingerprint = record(record(legacy.location).contentFingerprint);
    const originalFileHash = nonEmptyString(rawLocationFingerprint.originalFileHash);
    const parserVersion = nonEmptyString(rawLocationFingerprint.parserVersion);
    const normalizationVersion = nonEmptyString(rawLocationFingerprint.normalizationVersion);
    const localContentFingerprint = serverContentFingerprint
      ? localContentFingerprintKey(
          originalFileHash && parserVersion && normalizationVersion
            ? { originalFileHash, parserVersion, normalizationVersion }
            : undefined,
          serverContentFingerprint
        )
      : undefined;
    const location = parseProgressLocation(legacy.location);
    const updatedAtEpochMillis = finiteNumber(legacy.updatedAt);
    if (!userId || !clientId || !workId || !volumeId || !localContentFingerprint || !location || updatedAtEpochMillis === undefined) {
      cursor.continue();
      return;
    }
    const identity = { serverIdentity, userId, clientId, volumeId, localContentFingerprint };
    const candidate: ExactProgressRecord = {
      ...identity,
      key: exactProgressKey(identity),
      schemaVersion: 1,
      workId,
      location,
      percent: normalizedPercent(finiteNumber(legacy.percent) ?? null),
      updatedAtEpochMillis
    };
    const getRequest = exactStore.get(candidate.key);
    getRequest.onerror = () => transaction.abort();
    getRequest.onsuccess = () => {
      const existing = record(getRequest.result);
      const existingUpdatedAt = finiteNumber(existing.updatedAtEpochMillis) ?? -1;
      if (candidate.updatedAtEpochMillis >= existingUpdatedAt) exactStore.put(candidate);
      cursor.continue();
    };
  };
}

function openDatabase() {
  if (typeof indexedDB === 'undefined') return Promise.reject(new Error('IndexedDB is not available'));
  if (databasePromise) return databasePromise;
  databasePromise = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(READER_PROGRESS_DB_NAME, READER_DB_SCHEMA_VERSION);
    request.onupgradeneeded = (event) => {
      const database = request.result;
      const transaction = request.transaction;
      if (!transaction) return;
      if (!database.objectStoreNames.contains(PREFERENCES_STORE)) database.createObjectStore(PREFERENCES_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(EXACT_PROGRESS_STORE)) database.createObjectStore(EXACT_PROGRESS_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(META_STORE)) database.createObjectStore(META_STORE, { keyPath: 'key' });
      if (!database.objectStoreNames.contains(DIAGNOSTICS_STORE)) database.createObjectStore(DIAGNOSTICS_STORE, { keyPath: 'id' });
      if (!database.objectStoreNames.contains(BOOK_FILES_STORE)) {
        const bookFiles = database.createObjectStore(BOOK_FILES_STORE, { keyPath: 'key' });
        bookFiles.createIndex('by-user-volume', 'userVolumeKey', { unique: false });
      }
      if (event.oldVersion > 0 && event.oldVersion < 4) migrateLegacyOutbox(database, transaction);
      else deleteLegacySyncStores(database);
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
      reject(request.error ?? new Error('Reader v4 IndexedDB open failed'));
    };
    request.onblocked = () => {
      databasePromise = null;
      reject(new Error('Reader v4 IndexedDB upgrade is blocked'));
    };
  });
  return databasePromise;
}

async function withTransaction<T>(
  storeNames: ReaderStoreName | ReaderStoreName[],
  mode: IDBTransactionMode,
  action: (stores: (name: ReaderStoreName) => IDBObjectStore) => Promise<T>
) {
  const database = await openDatabase();
  const transaction = database.transaction(storeNames, mode);
  const completed = transactionComplete(transaction);
  const stores = (name: ReaderStoreName) => transaction.objectStore(name);
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

export class IndexedDbReaderStorage implements ReaderStorage, ReaderBookCache {
  async getBookFile(identity: ReaderBookCacheIdentity) {
    return withTransaction(BOOK_FILES_STORE, 'readonly', async (stores) => {
      const value = await requestResult(stores(BOOK_FILES_STORE).get(readerBookCacheKey(identity))) as CachedReaderBookFile | undefined;
      if (!value || !(value.blob instanceof Blob) || value.blob.size <= 0) return null;
      return value;
    });
  }

  async putBookFile(file: CachedReaderBookFile) {
    await withTransaction(BOOK_FILES_STORE, 'readwrite', async (stores) => {
      const store = stores(BOOK_FILES_STORE);
      const oldKeys = await requestResult(store.index('by-user-volume').getAllKeys(file.userVolumeKey));
      await Promise.all(oldKeys.filter((key) => key !== file.key).map((key) => requestResult(store.delete(key))));
      await requestResult(store.put(file));
    });
  }

  async deleteBookFile(identity: ReaderBookCacheIdentity) {
    await withTransaction(BOOK_FILES_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(BOOK_FILES_STORE).delete(readerBookCacheKey(identity)));
    });
  }

  async getPreference(userId: string, workId: string) {
    return withTransaction(PREFERENCES_STORE, 'readwrite', async (stores) => {
      const store = stores(PREFERENCES_STORE);
      const value: unknown = await requestResult(store.get(preferenceKey(userId, workId)));
      return readStoredPreferenceSnapshot(value, userId, workId, (snapshot) => requestResult(store.put(snapshot)));
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

  async getClientId() {
    return withTransaction(META_STORE, 'readwrite', async (stores) => {
      const store = stores(META_STORE);
      const current = record(await requestResult(store.get('client')));
      const clientId = nonEmptyString(current.clientId) ?? createId('web');
      if (current.clientId !== clientId || current.key !== 'client') {
        await requestResult(store.put({ key: 'client', clientId } satisfies ClientMeta));
      }
      return clientId;
    });
  }

  async getExactProgress(identity: ExactProgressIdentity) {
    return withTransaction(EXACT_PROGRESS_STORE, 'readonly', async (stores) => {
      const value: unknown = await requestResult(stores(EXACT_PROGRESS_STORE).get(exactProgressKey(identity)));
      return parseExactProgress(value, identity);
    });
  }

  async putExactProgress(progress: ExactProgressRecord) {
    if (progress.key !== exactProgressKey(progress)) throw new Error('Exact progress key does not match its identity');
    await withTransaction(EXACT_PROGRESS_STORE, 'readwrite', async (stores) => {
      await requestResult(stores(EXACT_PROGRESS_STORE).put(progress));
    });
    return progress;
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

  async clearAll() {
    const storeNames: ReaderStoreName[] = [PREFERENCES_STORE, EXACT_PROGRESS_STORE, META_STORE, DIAGNOSTICS_STORE, BOOK_FILES_STORE];
    await withTransaction(storeNames, 'readwrite', async (stores) => {
      await Promise.all(storeNames.map((name) => requestResult(stores(name).clear())));
    });
  }
}
