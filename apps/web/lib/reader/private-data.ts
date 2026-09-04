import { emitReaderDebug } from './debug';
import type { ReaderV5Storage } from './v5-storage';

export async function clearPrivateReaderData(storage: ReaderV5Storage) {
  try {
    await storage.clearAll();
  } catch (error) {
    emitReaderDebug('error', 'Reader v5 私有数据清除失败', {
      error: error instanceof Error ? error.message : String(error)
    });
  }
  emitReaderDebug('info', '已清除 Reader v5 私有数据');
}
