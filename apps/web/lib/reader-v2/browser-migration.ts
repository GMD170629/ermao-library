import type { ReaderKind } from '@shuku/reader-core';
import { emitReaderDebug } from './debug';
import { migrateLegacyPreferenceCandidate, migrateLegacyProgressCandidate } from './migrations';
import type { ProgressMutationInput } from './model';
import { LEGACY_MIGRATION_MARKER_PREFIX } from './private-data';
import { ReaderPreferenceRepository } from './preferences';
import { getReaderProgressSyncCoordinator } from './sync-coordinator';
import { IndexedDbReaderV2Storage, type ReaderV2Storage } from './storage';

const LEGACY_DB_NAME = 'shuku-pwa-v0.3.1';
const LEGACY_PROGRESS_STORE = 'progressQueue';
const LEGACY_PREFERENCE_STORE = 'preferenceQueue';

export type LegacyBrowserReaderContext = {
  currentUserId: string;
  currentWorkId: string;
  currentEditionId: string;
  contentFingerprint: string;
  readerKind: ReaderKind;
  volumeId?: string | null;
};

export type LegacyBrowserMigrationSummary = {
  status: 'migrated' | 'skipped';
  migrated: number;
  quarantined: number;
};

type LegacyBrowserMigrationDependencies = {
  storage?: ReaderV2Storage;
  repository?: ReaderPreferenceRepository;
};

type LegacyEntry = { key: IDBValidKey; value: Record<string, unknown> };

function record(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try {
      return record(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function exactOwner(value: Record<string, unknown>, context: LegacyBrowserReaderContext) {
  const owner = record(value.owner);
  const payload = record(value.progress);
  const userId = value.userId ?? owner.userId ?? payload.userId;
  const workId = value.workId ?? owner.workId ?? payload.workId;
  return userId === context.currentUserId && workId === context.currentWorkId;
}

function storedFingerprint(value: Record<string, unknown>) {
  const payload = record(value.progress);
  const extra = record(payload.extra);
  return value.contentFingerprint ?? payload.contentFingerprint ?? extra.contentFingerprint;
}

function migrationMarker(context: LegacyBrowserReaderContext) {
  return `${LEGACY_MIGRATION_MARKER_PREFIX}${encodeURIComponent(context.currentUserId)}:${encodeURIComponent(context.currentWorkId)}:${encodeURIComponent(context.currentEditionId)}:${encodeURIComponent(context.volumeId ?? '')}`;
}

function legacyPreferenceType(kind: ReaderKind) {
  return kind === 'epub' ? 'ebook' : kind;
}

function idbRequest<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Legacy IndexedDB request failed'));
  });
}

function idbTransactionDone(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error('Legacy IndexedDB transaction failed'));
    transaction.onabort = () => reject(transaction.error ?? new Error('Legacy IndexedDB transaction aborted'));
  });
}

function localStorageGet(key: string) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function localStorageRemove(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Private browsing can expose localStorage while rejecting access.
  }
}

function localStorageSet(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A missing marker is safe: already-removed entries cannot be misattributed.
  }
}

async function openLegacyDatabase(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === 'undefined') return null;
  const factory = indexedDB as IDBFactory & { databases?: () => Promise<Array<{ name?: string }>> };
  if (factory.databases) {
    const databases = await factory.databases();
    if (!databases.some((database) => database.name === LEGACY_DB_NAME)) return null;
  }

  return new Promise((resolve, reject) => {
    let createdEmptyDatabase = false;
    const request = indexedDB.open(LEGACY_DB_NAME);
    request.onupgradeneeded = (event) => {
      createdEmptyDatabase = event.oldVersion === 0;
      if (createdEmptyDatabase) request.transaction?.abort();
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      if (createdEmptyDatabase) resolve(null);
      else reject(request.error ?? new Error('Legacy IndexedDB open failed'));
    };
  });
}

async function readLegacyEntries(database: IDBDatabase, storeName: string): Promise<LegacyEntry[]> {
  if (!database.objectStoreNames.contains(storeName)) return [];
  const transaction = database.transaction(storeName, 'readonly');
  const completed = idbTransactionDone(transaction);
  const store = transaction.objectStore(storeName);
  const [keys, values] = await Promise.all([idbRequest(store.getAllKeys()), idbRequest(store.getAll())]);
  await completed;
  return values.map((value, index) => ({ key: keys[index], value: record(value) }));
}

async function deleteLegacyEntries(database: IDBDatabase, storeName: string, keys: IDBValidKey[]) {
  if (keys.length === 0 || !database.objectStoreNames.contains(storeName)) return;
  const transaction = database.transaction(storeName, 'readwrite');
  const completed = idbTransactionDone(transaction);
  const store = transaction.objectStore(storeName);
  await Promise.all(keys.map((key) => idbRequest(store.delete(key))));
  await completed;
}

async function diagnoseUnsafe(storage: ReaderV2Storage, source: string, reason: string) {
  await storage.addDiagnostic({
    level: 'warning',
    code: 'unsafe-legacy',
    message: `旧阅读数据未迁移：${reason}`,
    data: { source }
  });
  emitReaderDebug('warning', '旧阅读数据因归属不明确而隔离', { source, reason });
}

/**
 * One-shot bridge from the unscoped V1 caches. Identity is never inferred from
 * the currently logged-in user: the legacy value itself must carry an exact
 * owner (and progress must also carry the exact content fingerprint).
 */
export async function migrateLegacyBrowserReaderState(
  context: LegacyBrowserReaderContext,
  dependencies: LegacyBrowserMigrationDependencies = {}
): Promise<LegacyBrowserMigrationSummary> {
  if (typeof window === 'undefined') return { status: 'skipped', migrated: 0, quarantined: 0 };
  const marker = migrationMarker(context);
  if (localStorageGet(marker) === 'complete') return { status: 'skipped', migrated: 0, quarantined: 0 };

  const storage = dependencies.storage ?? new IndexedDbReaderV2Storage();
  const repository = dependencies.repository ?? new ReaderPreferenceRepository(storage);
  const coordinator = getReaderProgressSyncCoordinator();
  const enqueuer = coordinator ?? { enqueue: (input: ProgressMutationInput) => storage.enqueueProgress(input) };
  let migrated = 0;
  let quarantined = 0;

  const preferenceType = legacyPreferenceType(context.readerKind);
  const localPreferenceKey = `shuku:reader:preferences:${preferenceType}`;
  const localProgressKeys = [
    `shuku:reader:progress:${context.currentEditionId}`,
    ...(context.volumeId ? [`shuku:reader:progress:${context.currentEditionId}:volume:${context.volumeId}`] : [])
  ];

  const localPreferenceRaw = localStorageGet(localPreferenceKey);
  if (localPreferenceRaw) {
    const value = record(localPreferenceRaw);
    if (exactOwner(value, context)) {
      const result = await migrateLegacyPreferenceCandidate({
        userId: context.currentUserId,
        workId: context.currentWorkId,
        settings: value.settings ?? value,
        sourceKey: localPreferenceKey
      }, repository, storage);
      if (result.status === 'migrated') migrated += 1;
    } else {
      await diagnoseUnsafe(storage, localPreferenceKey, '旧偏好没有同一用户和作品的明确归属');
      quarantined += 1;
    }
    localStorageRemove(localPreferenceKey);
  }

  for (const key of localProgressKeys) {
    const raw = localStorageGet(key);
    if (!raw) continue;
    const value = record(raw);
    if (exactOwner(value, context) && storedFingerprint(value) === context.contentFingerprint) {
      const result = await migrateLegacyProgressCandidate({
        userId: context.currentUserId,
        workId: context.currentWorkId,
        editionId: context.currentEditionId,
        contentFingerprint: context.contentFingerprint,
        volumeId: context.volumeId,
        readerType: context.readerKind,
        progress: value.progress ?? value,
        sourceKey: key
      }, enqueuer, storage);
      if (result.status === 'migrated') migrated += 1;
    } else {
      await diagnoseUnsafe(storage, key, '旧进度没有精确的用户、作品和内容指纹归属');
      quarantined += 1;
    }
    localStorageRemove(key);
  }

  const legacyDatabase = await openLegacyDatabase();
  if (legacyDatabase) {
    try {
      const preferenceEntries = await readLegacyEntries(legacyDatabase, LEGACY_PREFERENCE_STORE);
      const matchingPreferences = preferenceEntries.filter(({ value }) => value.type === preferenceType);
      for (const entry of matchingPreferences) {
        if (exactOwner(entry.value, context)) {
          const result = await migrateLegacyPreferenceCandidate({
            userId: context.currentUserId,
            workId: context.currentWorkId,
            settings: entry.value.settings,
            sourceKey: `${LEGACY_DB_NAME}/${LEGACY_PREFERENCE_STORE}`
          }, repository, storage);
          if (result.status === 'migrated') migrated += 1;
        } else {
          await diagnoseUnsafe(storage, `${LEGACY_DB_NAME}/${LEGACY_PREFERENCE_STORE}`, '旧偏好队列没有同一用户和作品的明确归属');
          quarantined += 1;
        }
      }
      await deleteLegacyEntries(legacyDatabase, LEGACY_PREFERENCE_STORE, matchingPreferences.map(({ key }) => key));

      const progressEntries = await readLegacyEntries(legacyDatabase, LEGACY_PROGRESS_STORE);
      const matchingProgress = progressEntries.filter(({ value }) => value.bookId === context.currentEditionId);
      for (const entry of matchingProgress) {
        if (exactOwner(entry.value, context) && storedFingerprint(entry.value) === context.contentFingerprint) {
          const result = await migrateLegacyProgressCandidate({
            userId: context.currentUserId,
            workId: context.currentWorkId,
            editionId: context.currentEditionId,
            contentFingerprint: context.contentFingerprint,
            volumeId: context.volumeId,
            readerType: context.readerKind,
            progress: entry.value.progress,
            sourceKey: `${LEGACY_DB_NAME}/${LEGACY_PROGRESS_STORE}`
          }, enqueuer, storage);
          if (result.status === 'migrated') migrated += 1;
        } else {
          await diagnoseUnsafe(storage, `${LEGACY_DB_NAME}/${LEGACY_PROGRESS_STORE}`, '旧进度队列没有精确的用户、作品和内容指纹归属');
          quarantined += 1;
        }
      }
      await deleteLegacyEntries(legacyDatabase, LEGACY_PROGRESS_STORE, matchingProgress.map(({ key }) => key));
    } finally {
      legacyDatabase.close();
    }
  }

  localStorageSet(marker, 'complete');
  emitReaderDebug('info', '旧阅读器浏览器状态迁移检查完成', { migrated, quarantined, editionId: context.currentEditionId });
  return { status: 'migrated', migrated, quarantined };
}
