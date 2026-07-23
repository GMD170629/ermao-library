import {
  inheritReaderPreferences,
  normalizeReaderPreferences,
  type ReaderPreferences
} from '@shuku/reader-core';
import { emitReaderDebug } from './debug';
import type { ReaderV2Storage } from './storage';

export type ResolvedReaderPreferences = {
  preferences: ReaderPreferences;
  source: 'local' | 'inherited';
};

export class ReaderPreferenceRepository {
  constructor(private readonly storage: ReaderV2Storage) {}

  async resolve(userId: string, workId: string, serverDefault: unknown): Promise<ResolvedReaderPreferences> {
    const local = await this.storage.getPreference(userId, workId);
    if (local) return { preferences: normalizeReaderPreferences(local.preferences), source: 'local' };
    return { preferences: inheritReaderPreferences(serverDefault), source: 'inherited' };
  }

  async save(userId: string, workId: string, value: ReaderPreferences, inheritedDefault?: unknown) {
    const base = inheritReaderPreferences(inheritedDefault);
    const preferences = normalizeReaderPreferences(value, base);
    const snapshot = await this.storage.putPreference(userId, workId, preferences);
    emitReaderDebug('info', '已保存本书本机阅读偏好', { workId, schemaVersion: snapshot.schemaVersion });
    return snapshot;
  }

  async update(
    userId: string,
    workId: string,
    serverDefault: unknown,
    update: (current: ReaderPreferences) => unknown
  ) {
    const current = await this.resolve(userId, workId, serverDefault);
    const next = normalizeReaderPreferences(update(current.preferences), current.preferences);
    return this.save(userId, workId, next, serverDefault);
  }

  async reset(userId: string, workId: string, serverDefault: unknown) {
    await this.storage.deletePreference(userId, workId);
    emitReaderDebug('info', '已恢复本书当前设备默认阅读偏好', { workId });
    return inheritReaderPreferences(serverDefault);
  }
}
