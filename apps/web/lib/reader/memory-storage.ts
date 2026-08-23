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
import { readerResourceCacheKey, type CachedReaderResource, type ReaderResourceCache, type ReaderResourceCacheIdentity } from './resource-cache';
import type { CachedPdfRangeChunk, PdfRangeCache } from './pdf-range-cache';

function createId(prefix: string) { return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`; }

export class MemoryReaderStorage implements ReaderStorage, ReaderResourceCache, PdfRangeCache {
  private readonly preferences = new Map<string, ReaderPreferenceSnapshot>();
  private readonly exactProgress = new Map<string, ExactProgressRecord>();
  private readonly pending = new Map<string, PendingProgressMutation>();
  private readonly diagnostics: ReaderSyncDiagnostic[] = [];
  private readonly resourceCache = new Map<string, CachedReaderResource>();
  private readonly pdfRangeChunks = new Map<string, CachedPdfRangeChunk & { namespaceKey: string }>();
  private clientId = createId('web');
  async getResource(identity: ReaderResourceCacheIdentity) { return this.resourceCache.get(readerResourceCacheKey(identity)) ?? null; }
  async putResource(resource: CachedReaderResource) { for (const [key, current] of this.resourceCache) if (current.userId === resource.userId && current.resourceId === resource.resourceId && key !== resource.key) this.resourceCache.delete(key); this.resourceCache.set(resource.key, resource); }
  async deleteResource(identity: ReaderResourceCacheIdentity) { this.resourceCache.delete(readerResourceCacheKey(identity)); }
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
  async deletePdfRangeNamespace(identity: Omit<PdfRangeCacheIdentity, 'resourceId' | 'assetId'>) {
    const namespaceKey = pdfRangeNamespaceKey(identity);
    for (const [key, chunk] of this.pdfRangeChunks) {
      if (chunk.namespaceKey === namespaceKey) this.pdfRangeChunks.delete(key);
    }
  }
  async getPreference(userId: string, bookId: string) { return this.preferences.get(preferenceKey(userId, bookId)) ?? null; }
  async putPreference(userId: string, bookId: string, preferences: ReaderPreferences, updatedAt = Date.now()) { const value = { key: preferenceKey(userId, bookId), userId, bookId, schemaVersion: READER_SCHEMA_VERSION, preferences, updatedAt }; this.preferences.set(value.key, value); return value; }
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
  async clearAll() { this.preferences.clear(); this.exactProgress.clear(); this.pending.clear(); this.diagnostics.length = 0; this.resourceCache.clear(); this.pdfRangeChunks.clear(); this.clientId = createId('web'); }
}
