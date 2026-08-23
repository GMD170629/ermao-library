import { emitReaderDebug } from './debug';
import type { ReaderStorage } from './storage';

export async function clearPrivateReaderData(storage: ReaderStorage) {
  try {
    await storage.clearAll();
  } catch (error) {
    emitReaderDebug('error', 'Reader v4 私有数据清除失败', {
      error: error instanceof Error ? error.message : String(error)
    });
  }
  emitReaderDebug('info', '已清除 Reader v4 私有数据');
}
