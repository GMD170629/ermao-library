import {
  READER_PREFERENCES_VERSION,
  type ReaderPreferences
} from '@shuku/reader-core';
import {
  exactProgressKey,
  preferenceKey,
  syncStateKey,
  type ExactProgressIdentity,
  type ExactProgressRecord,
  type PendingProgressMutation,
  type ReaderPreferenceSnapshot,
  type ReaderSyncDiagnostic
} from './model';
import type { ReaderStorage } from './storage';

function createId(prefix: string) { return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`; }

export class MemoryReaderStorage implements ReaderStorage {
  private readonly preferences = new Map<string, ReaderPreferenceSnapshot>();
  private readonly exactProgress = new Map<string, ExactProgressRecord>();
  private readonly pending = new Map<string, PendingProgressMutation>();
  private readonly diagnostics: ReaderSyncDiagnostic[] = [];
  private clientId = createId('web');
  async getPreference(userId: string, bookId: string) { return this.preferences.get(preferenceKey(userId, bookId)) ?? null; }
  async putPreference(userId: string, bookId: string, preferences: ReaderPreferences, updatedAt = Date.now()) { const value = { key: preferenceKey(userId, bookId), userId, bookId, schemaVersion: READER_PREFERENCES_VERSION, preferences, updatedAt }; this.preferences.set(value.key, value); return value; }
  async deletePreference(userId: string, bookId: string) { this.preferences.delete(preferenceKey(userId, bookId)); }
  async getClientId() { return this.clientId; }
  async getExactProgress(identity: ExactProgressIdentity) {
    const key = exactProgressKey(identity);
    return this.exactProgress.get(key) ?? null;
  }
  async putExactProgress(progress: ExactProgressRecord) { this.exactProgress.set(progress.key, progress); return progress; }
  async putExactAndPending(progress: ExactProgressRecord, mutation: PendingProgressMutation) { this.exactProgress.set(progress.key, progress); this.pending.set(mutation.key, mutation); }
  async putPendingProgress(mutation: PendingProgressMutation) { this.pending.set(mutation.key, mutation); }
  async getPendingProgress(key: string) { return this.pending.get(key) ?? null; }
  async getPendingProgressForIdentity(identity: ExactProgressIdentity) {
    const key = syncStateKey(identity);
    return this.pending.get(key) ?? null;
  }
  async listPendingProgress(userId: string) { return [...this.pending.values()].filter((item) => item.userId === userId); }
  async deletePendingProgress(key: string, mutationId?: string) { const current = this.pending.get(key); if (!mutationId || current?.mutationId === mutationId) this.pending.delete(key); }
  async putExactAndDeletePending(progress: ExactProgressRecord, pendingKey: string) { this.exactProgress.set(progress.key, progress); this.pending.delete(pendingKey); }
  async addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) { const value = { ...diagnostic, id: createId('diagnostic'), createdAt: now }; this.diagnostics.push(value); return value; }
  async listDiagnostics(limit = 100) { return [...this.diagnostics].sort((a, b) => b.createdAt - a.createdAt).slice(0, limit); }
  async clearAll() { this.preferences.clear(); this.exactProgress.clear(); this.pending.clear(); this.diagnostics.length = 0; this.clientId = createId('web'); }
}
