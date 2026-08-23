import {
  inheritReaderPreferences,
  normalizeReaderPreferences,
  type ReaderPreferences
} from '@shuku/reader-core';
import { emitReaderDebug } from './debug';
import type { ReaderStorage } from './storage';

export type ResolvedReaderPreferences = {
  preferences: ReaderPreferences;
  source: 'local' | 'inherited';
};

export class ReaderPreferenceRepository {
  constructor(private readonly storage: ReaderStorage) {}

  async resolve(userId: string, bookId: string, serverDefault: unknown): Promise<ResolvedReaderPreferences> {
    const local = await this.storage.getPreference(userId, bookId);
    if (local) return { preferences: normalizeReaderPreferences(local.preferences), source: 'local' };
    return { preferences: inheritReaderPreferences(serverDefault), source: 'inherited' };
  }

  async save(userId: string, bookId: string, value: ReaderPreferences, inheritedDefault?: unknown) {
    const base = inheritReaderPreferences(inheritedDefault);
    const preferences = normalizeReaderPreferences(value, base);
    const snapshot = await this.storage.putPreference(userId, bookId, preferences);
    emitReaderDebug('info', '已保存本书本机阅读偏好', { bookId, schemaVersion: snapshot.schemaVersion });
    return snapshot;
  }

  async update(
    userId: string,
    bookId: string,
    serverDefault: unknown,
    update: (current: ReaderPreferences) => unknown
  ) {
    const current = await this.resolve(userId, bookId, serverDefault);
    const next = normalizeReaderPreferences(update(current.preferences), current.preferences);
    return this.save(userId, bookId, next, serverDefault);
  }

  async reset(userId: string, bookId: string, serverDefault: unknown) {
    await this.storage.deletePreference(userId, bookId);
    emitReaderDebug('info', '已恢复本书当前设备默认阅读偏好', { bookId });
    return inheritReaderPreferences(serverDefault);
  }
}
