import type { ReaderSource } from '@shuku/reader-core';

const DATABASE_NAME = 'shuku-reader-epub-v2';
const DATABASE_VERSION = 1;
const STORE_NAME = 'locations';
export const EPUB_LOCATION_CACHE_VERSION = 2;

export const EPUB_LOCATION_BREAK = 1200;
export const EPUB_SHARED_LOCATION_WAIT_LIMIT_MS = 3_000;

type EpubLocationsRecord = {
  key: string;
  fingerprint: string;
  breakSize: number;
  serialized: string;
  savedAt: number;
};

export function epubLocationsCacheKey(fingerprint: string, breakSize = EPUB_LOCATION_BREAK) {
  return `v${EPUB_LOCATION_CACHE_VERSION}:${fingerprint}:${breakSize}`;
}

export type SharedEpubLocationsClaim =
  | { status: 'ready'; serialized: string }
  | { status: 'claimed'; leaseToken: string; leaseExpiresAt: number }
  | { status: 'generating'; leaseExpiresAt: number; retryAfterMs: number };

export function sharedEpubLocationsWaitMs(
  retryAfterMs: number,
  waitStartedAt: number,
  now = Date.now(),
  waitLimitMs = EPUB_SHARED_LOCATION_WAIT_LIMIT_MS
) {
  const remaining = Math.max(0, waitLimitMs - Math.max(0, now - waitStartedAt));
  return Math.min(Math.max(250, retryAfterMs), remaining);
}

function sharedLocationsUrl(source: ReaderSource, suffix = '') {
  const query = new URLSearchParams();
  if (source.volumeId) query.set('volume', source.volumeId);
  return `/api/reader/v2/editions/${encodeURIComponent(source.editionId)}/epub-locations${suffix}${query.size ? `?${query}` : ''}`;
}

async function sharedLocationsPayload(response: Response) {
  const payload = await response.json().catch(() => null) as {
    ok?: boolean;
    data?: SharedEpubLocationsClaim;
    error?: { message?: string };
  } | null;
  if (!response.ok || !payload?.ok || !payload.data) {
    throw new Error(payload?.error?.message ?? `EPUB 位置索引服务不可用（${response.status}）`);
  }
  const data = payload.data;
  const valid = data.status === 'ready'
    ? typeof data.serialized === 'string' && data.serialized.length > 0
    : data.status === 'claimed'
      ? typeof data.leaseToken === 'string'
        && data.leaseToken.length > 0
        && Number.isFinite(data.leaseExpiresAt)
      : data.status === 'generating'
        && Number.isFinite(data.leaseExpiresAt)
        && Number.isFinite(data.retryAfterMs)
        && data.retryAfterMs >= 0;
  if (!valid) throw new Error('EPUB 位置索引服务返回了无效状态');
  return data;
}

export async function claimSharedEpubLocations(
  source: ReaderSource,
  breakSize = EPUB_LOCATION_BREAK,
  signal?: AbortSignal
) {
  const response = await fetch(sharedLocationsUrl(source, '/claim'), {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cacheVersion: EPUB_LOCATION_CACHE_VERSION,
      contentFingerprint: source.contentFingerprint,
      breakSize
    })
  });
  return sharedLocationsPayload(response);
}

export async function saveSharedEpubLocations(
  source: ReaderSource,
  leaseToken: string,
  serialized: string,
  breakSize = EPUB_LOCATION_BREAK,
  signal?: AbortSignal
) {
  const response = await fetch(sharedLocationsUrl(source), {
    method: 'PUT',
    credentials: 'same-origin',
    cache: 'no-store',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cacheVersion: EPUB_LOCATION_CACHE_VERSION,
      contentFingerprint: source.contentFingerprint,
      breakSize,
      leaseToken,
      serialized
    })
  });
  return sharedLocationsPayload(response);
}

function openDatabase() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: 'key' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('EPUB pagination cache unavailable'));
  });
}

export async function loadEpubLocations(fingerprint: string, breakSize = EPUB_LOCATION_BREAK) {
  if (typeof indexedDB === 'undefined') return null;
  const database = await openDatabase();
  try {
    return await new Promise<string | null>((resolve, reject) => {
      const request = database.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(epubLocationsCacheKey(fingerprint, breakSize));
      request.onsuccess = () => resolve((request.result as EpubLocationsRecord | undefined)?.serialized ?? null);
      request.onerror = () => reject(request.error ?? new Error('EPUB pagination cache read failed'));
    });
  } finally {
    database.close();
  }
}

export async function saveEpubLocations(fingerprint: string, serialized: string, breakSize = EPUB_LOCATION_BREAK) {
  if (typeof indexedDB === 'undefined' || !serialized) return;
  const database = await openDatabase();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, 'readwrite');
      transaction.objectStore(STORE_NAME).put({
        key: epubLocationsCacheKey(fingerprint, breakSize),
        fingerprint,
        breakSize,
        serialized,
        savedAt: Date.now()
      } satisfies EpubLocationsRecord);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error ?? new Error('EPUB pagination cache write failed'));
      transaction.onabort = () => reject(transaction.error ?? new Error('EPUB pagination cache write aborted'));
    });
  } finally {
    database.close();
  }
}
