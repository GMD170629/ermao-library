import { READER_SCHEMA_VERSION, type ReaderPreferences } from '@shuku/reader-core';
import {
  exactProgressKey,
  preferenceKey,
  type ExactProgressIdentity,
  type ExactProgressRecord,
  type ReaderPreferenceSnapshot,
  type ReaderSyncDiagnostic
} from './model';
import type { ReaderStorage } from './storage';
import {
  readerBookCacheKey,
  type CachedReaderBookFile,
  type ReaderBookCache,
  type ReaderBookCacheIdentity
} from './book-cache';

function createId(prefix: string) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
}

/** In-memory implementation used by policy tests and non-browser previews. */
export class MemoryReaderStorage implements ReaderStorage, ReaderBookCache {
  private readonly preferences = new Map<string, ReaderPreferenceSnapshot>();
  private readonly exactProgress = new Map<string, ExactProgressRecord>();
  private readonly diagnostics: ReaderSyncDiagnostic[] = [];
  private readonly bookFiles = new Map<string, CachedReaderBookFile>();
  private clientId = createId('web');

  async getBookFile(identity: ReaderBookCacheIdentity) {
    return this.bookFiles.get(readerBookCacheKey(identity)) ?? null;
  }

  async putBookFile(file: CachedReaderBookFile) {
    for (const [key, current] of this.bookFiles) {
      if (current.userId === file.userId && current.volumeId === file.volumeId && key !== file.key) {
        this.bookFiles.delete(key);
      }
    }
    this.bookFiles.set(file.key, file);
  }

  async deleteBookFile(identity: ReaderBookCacheIdentity) {
    this.bookFiles.delete(readerBookCacheKey(identity));
  }

  async getPreference(userId: string, workId: string) {
    return this.preferences.get(preferenceKey(userId, workId)) ?? null;
  }

  async putPreference(userId: string, workId: string, preferences: ReaderPreferences, updatedAt = Date.now()) {
    const snapshot: ReaderPreferenceSnapshot = {
      key: preferenceKey(userId, workId),
      userId,
      workId,
      schemaVersion: READER_SCHEMA_VERSION,
      preferences,
      updatedAt
    };
    this.preferences.set(snapshot.key, snapshot);
    return snapshot;
  }

  async deletePreference(userId: string, workId: string) {
    this.preferences.delete(preferenceKey(userId, workId));
  }

  async getClientId() {
    return this.clientId;
  }

  async getExactProgress(identity: ExactProgressIdentity) {
    return this.exactProgress.get(exactProgressKey(identity)) ?? null;
  }

  async putExactProgress(progress: ExactProgressRecord) {
    this.exactProgress.set(progress.key, progress);
    return progress;
  }

  async addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) {
    const value: ReaderSyncDiagnostic = { ...diagnostic, id: createId('diagnostic'), createdAt: now };
    this.diagnostics.push(value);
    return value;
  }

  async listDiagnostics(limit = 100) {
    return [...this.diagnostics].sort((left, right) => right.createdAt - left.createdAt).slice(0, limit);
  }

  async clearAll() {
    this.preferences.clear();
    this.exactProgress.clear();
    this.diagnostics.length = 0;
    this.bookFiles.clear();
    this.clientId = createId('web');
  }
}
