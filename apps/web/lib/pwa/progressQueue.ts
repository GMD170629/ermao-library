'use client';

/** Clears the current private PWA caches; Reader storage owns local progress. */
export async function clearPrivatePwaData() {
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
