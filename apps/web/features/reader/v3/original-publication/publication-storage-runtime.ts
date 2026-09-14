import { emitReaderDebug } from '../../../../lib/reader/debug';
import { PRIVATE_CACHE_PREFIX } from '../../../../lib/pwa/private-cache-namespace';
import { IndexedDbPublicationStorage } from './indexeddb-publication-storage';

export const originalPublicationStorage = new IndexedDbPublicationStorage();

async function clearLegacyOriginalCaches(): Promise<void> {
  if (typeof window === 'undefined') return;
  try {
    if (!window.caches) return;
    const names = await window.caches.keys();
    await Promise.all(names.filter((name) => name.startsWith(PRIVATE_CACHE_PREFIX)
      && name.endsWith('-reader-original-v1')).map((name) => window.caches.delete(name)));
  } catch {
    // No success marker: the next activation retries cleanup. Reading uses IndexedDB regardless.
    emitReaderDebug('warning', 'READER_LEGACY_CACHE_CLEANUP_FAILED');
  }
}

export async function activateOriginalPublicationUser(namespace: string): Promise<void> {
  await originalPublicationStorage.activate(namespace);
  await clearLegacyOriginalCaches();
}

export async function clearOriginalPublicationData(): Promise<void> {
  await originalPublicationStorage.activate(null);
  await clearLegacyOriginalCaches();
}
