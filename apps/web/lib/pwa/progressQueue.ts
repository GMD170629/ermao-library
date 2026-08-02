'use client';

const LEGACY_READER_DB_NAME = 'shuku-pwa-v0.3.1';

async function deleteLegacyReaderDatabase() {
  if (typeof indexedDB === 'undefined') return;
  await new Promise<void>((resolve) => {
    const request = indexedDB.deleteDatabase(LEGACY_READER_DB_NAME);
    request.onsuccess = () => resolve();
    request.onerror = () => resolve();
    request.onblocked = () => resolve();
  });
}

/** Clears V1 private state only. Reader v3 owns all current writes and sync. */
export async function clearPrivatePwaData() {
  await deleteLegacyReaderDatabase();
  if ('caches' in window) {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter((key) => key.includes('private') || key.includes('cover') || key.includes('api'))
        .map((key) => caches.delete(key))
    );
  }
  navigator.serviceWorker?.controller?.postMessage({ type: 'CLEAR_PRIVATE_CACHES' });
}
