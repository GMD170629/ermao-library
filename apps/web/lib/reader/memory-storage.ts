import {
  READER_SCHEMA_VERSION,
  pdfRangeChunkKey,
  pdfRangeNamespaceKey,
  type PdfRangeCacheIdentity,
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
import { readerBookCacheKey, type CachedReaderBookFile, type ReaderBookCache, type ReaderBookCacheIdentity } from './book-cache';
import type { CachedPdfRangeChunk, PdfRangeCache } from './pdf-range-cache';

function createId(prefix: string) { return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`; }

export class MemoryReaderStorage implements ReaderStorage, ReaderBookCache, PdfRangeCache {
  private readonly preferences = new Map<string, ReaderPreferenceSnapshot>();
  private readonly exactProgress = new Map<string, ExactProgressRecord>();
  private readonly pending = new Map<string, PendingProgressMutation>();
  private readonly diagnostics: ReaderSyncDiagnostic[] = [];
  private readonly bookFiles = new Map<string, CachedReaderBookFile>();
  private readonly pdfRangeChunks = new Map<string, CachedPdfRangeChunk & { namespaceKey: string }>();
  private clientId = createId('web');
  async getBookFile(identity: ReaderBookCacheIdentity) { return this.bookFiles.get(readerBookCacheKey(identity)) ?? null; }
  async putBookFile(file: CachedReaderBookFile) { for (const [key, current] of this.bookFiles) if (current.userId === file.userId && current.volumeId === file.volumeId && key !== file.key) this.bookFiles.delete(key); this.bookFiles.set(file.key, file); }
  async deleteBookFile(identity: ReaderBookCacheIdentity) { this.bookFiles.delete(readerBookCacheKey(identity)); }
  async getPdfRangeChunk(identity: PdfRangeCacheIdentity, chunkIndex: number) {
    const key = pdfRangeChunkKey(identity, chunkIndex);
    const value = this.pdfRangeChunks.get(key);
    if (!value) return null;
    const updated = { ...value, bytes: value.bytes.slice(), lastAccessedAt: Date.now() };
    this.pdfRangeChunks.set(key, updated);
    return { bytes: updated.bytes, lastAccessedAt: updated.lastAccessedAt };
  }
  async putPdfRangeChunk(identity: PdfRangeCacheIdentity, chunkIndex: number, bytes: Uint8Array) {
    this.pdfRangeChunks.set(pdfRangeChunkKey(identity, chunkIndex), {
      bytes: bytes.slice(),
      lastAccessedAt: Date.now(),
      namespaceKey: pdfRangeNamespaceKey(identity)
    });
  }
  async deletePdfRangeNamespace(identity: Omit<PdfRangeCacheIdentity, 'volumeId'>) {
    const namespaceKey = pdfRangeNamespaceKey(identity);
    for (const [key, chunk] of this.pdfRangeChunks) {
      if (chunk.namespaceKey === namespaceKey) this.pdfRangeChunks.delete(key);
    }
  }
  async getPreference(userId: string, workId: string) { return this.preferences.get(preferenceKey(userId, workId)) ?? null; }
  async putPreference(userId: string, workId: string, preferences: ReaderPreferences, updatedAt = Date.now()) { const value = { key: preferenceKey(userId, workId), userId, workId, schemaVersion: READER_SCHEMA_VERSION, preferences, updatedAt }; this.preferences.set(value.key, value); return value; }
  async deletePreference(userId: string, workId: string) { this.preferences.delete(preferenceKey(userId, workId)); }
  async getClientId() { return this.clientId; }
  async getExactProgress(identity: ExactProgressIdentity) {
    const key = exactProgressKey(identity);
    const current = this.exactProgress.get(key);
    if (current) return current;
    const legacy = [...this.exactProgress.values()]
      .filter((candidate) => candidate.serverIdentity === identity.serverIdentity
        && candidate.userId === identity.userId
        && candidate.clientId === identity.clientId
        && candidate.workId === identity.workId
        && candidate.volumeId === identity.volumeId)
      .sort((left, right) => right.capturedAtEpochMillis - left.capturedAtEpochMillis)[0];
    if (!legacy) return null;
    const migrated = { ...legacy, ...identity, key };
    this.exactProgress.set(key, migrated);
    if (legacy.key !== key) this.exactProgress.delete(legacy.key);
    return migrated;
  }
  async putExactProgress(progress: ExactProgressRecord) { this.exactProgress.set(progress.key, progress); return progress; }
  async putExactAndPending(progress: ExactProgressRecord, mutation: PendingProgressMutation) { this.exactProgress.set(progress.key, progress); this.pending.set(mutation.key, mutation); }
  async putPendingProgress(mutation: PendingProgressMutation) { this.pending.set(mutation.key, mutation); }
  async getPendingProgress(key: string) { return this.pending.get(key) ?? null; }
  async getPendingProgressForIdentity(identity: ExactProgressIdentity) {
    const key = syncStateKey(identity);
    const current = this.pending.get(key);
    if (current) return current;
    const legacy = [...this.pending.values()]
      .filter((candidate) => candidate.serverIdentity === identity.serverIdentity
        && candidate.userId === identity.userId
        && candidate.clientId === identity.clientId
        && candidate.workId === identity.workId
        && candidate.volumeId === identity.volumeId)
      .sort((left, right) => right.capturedAtEpochMillis - left.capturedAtEpochMillis)[0];
    if (!legacy) return null;
    const migrated = { ...legacy, key };
    this.pending.set(key, migrated);
    if (legacy.key !== key) this.pending.delete(legacy.key);
    return migrated;
  }
  async listPendingProgress(userId: string) { return [...this.pending.values()].filter((item) => item.userId === userId); }
  async deletePendingProgress(key: string, mutationId?: string) { const current = this.pending.get(key); if (!mutationId || current?.mutationId === mutationId) this.pending.delete(key); }
  async putExactAndDeletePending(progress: ExactProgressRecord, pendingKey: string) { this.exactProgress.set(progress.key, progress); this.pending.delete(pendingKey); }
  async addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) { const value = { ...diagnostic, id: createId('diagnostic'), createdAt: now }; this.diagnostics.push(value); return value; }
  async listDiagnostics(limit = 100) { return [...this.diagnostics].sort((a, b) => b.createdAt - a.createdAt).slice(0, limit); }
  async clearAll() { this.preferences.clear(); this.exactProgress.clear(); this.pending.clear(); this.diagnostics.length = 0; this.bookFiles.clear(); this.pdfRangeChunks.clear(); this.clientId = createId('web'); }
}
