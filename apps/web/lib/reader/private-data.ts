import { emitReaderDebug } from './debug';
import type { ReaderStorage } from './storage';

const LEGACY_MIGRATION_MARKER_PREFIX = 'shuku:reader:v2:migration:';

export async function clearPrivateReaderData(storage: ReaderStorage) {
  try {
    await storage.clearAll();
  } catch (error) {
    emitReaderDebug('error', 'Reader v3 私有数据清除失败', {
      error: error instanceof Error ? error.message : String(error)
    });
  }
  if (typeof window !== 'undefined') {
    try {
      const keys: string[] = [];
      for (let index = 0; index < window.localStorage.length; index += 1) {
        const key = window.localStorage.key(index);
        if (key?.startsWith(LEGACY_MIGRATION_MARKER_PREFIX)) keys.push(key);
      }
      keys.forEach((key) => window.localStorage.removeItem(key));
    } catch {
      // Private browsing can expose localStorage while rejecting access.
    }
  }
  emitReaderDebug('info', '已清除 Reader v3 私有数据');
}

export { LEGACY_MIGRATION_MARKER_PREFIX };
