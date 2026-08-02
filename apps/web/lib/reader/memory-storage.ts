import { READER_SCHEMA_VERSION, type ReaderPreferences } from '@shuku/reader-core';
import {
  preferenceKey,
  progressSlotKey,
  type ProgressMutation,
  type ProgressMutationInput,
  type QuarantinedProgress,
  type ReaderPreferenceSnapshot,
  type ReaderSyncDiagnostic,
  type ReaderSyncLease
} from './model';
import type { ReaderStorage } from './storage';

function createId(prefix: string) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
}

/** Deterministic-enough in-memory implementation for Node tests and non-browser previews. */
export class MemoryReaderStorage implements ReaderStorage {
  private readonly preferences = new Map<string, ReaderPreferenceSnapshot>();
  private readonly progress = new Map<string, ProgressMutation>();
  private readonly slotMutationIds = new Map<string, string>();
  private readonly diagnostics: ReaderSyncDiagnostic[] = [];
  private readonly quarantine: QuarantinedProgress[] = [];
  private clientId = createId('client');
  private sequence = 0;
  private lease: ReaderSyncLease | null = null;

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

  async enqueueProgress(input: ProgressMutationInput, now = Date.now()) {
    this.sequence += 1;
    const slotKey = progressSlotKey(input);
    const previousId = this.slotMutationIds.get(slotKey);
    const previous = previousId ? this.progress.get(previousId) : undefined;
    if (previousId) this.progress.delete(previousId);

    const mutation: ProgressMutation = {
      ...input,
      schemaVersion: 3,
      mutationId: createId('progress'),
      clientId: this.clientId,
      clientSequence: this.sequence,
      slotKey,
      percent: Math.max(0, Math.min(100, Number.isFinite(input.percent) ? input.percent : 0)),
      createdAt: previous?.createdAt ?? now,
      updatedAt: now,
      retryCount: 0,
      nextAttemptAt: now
    };
    this.progress.set(mutation.mutationId, mutation);
    this.slotMutationIds.set(slotKey, mutation.mutationId);
    return mutation;
  }

  async listProgress() {
    return [...this.progress.values()].sort((left, right) => left.clientSequence - right.clientSequence);
  }

  async compareDeleteProgress(mutationId: string) {
    const current = this.progress.get(mutationId);
    if (!current || current.mutationId !== mutationId) return false;
    this.progress.delete(mutationId);
    if (this.slotMutationIds.get(current.slotKey) === mutationId) this.slotMutationIds.delete(current.slotKey);
    return true;
  }

  async markProgressRetry(mutationId: string, nextAttemptAt: number, now = Date.now()) {
    const current = this.progress.get(mutationId);
    if (!current || current.mutationId !== mutationId) return false;
    this.progress.set(mutationId, { ...current, retryCount: current.retryCount + 1, nextAttemptAt, updatedAt: now });
    return true;
  }

  async quarantineProgress(mutation: ProgressMutation, reason: QuarantinedProgress['reason'], message: string, now = Date.now()) {
    this.quarantine.push({ id: createId('quarantine'), mutation, reason, message, createdAt: now });
    await this.compareDeleteProgress(mutation.mutationId);
  }

  async acquireProgressLease(ownerId: string, ttlMs: number, now = Date.now()) {
    if (this.lease && this.lease.ownerId !== ownerId && this.lease.expiresAt > now) return false;
    this.lease = { key: 'progress-sync', ownerId, expiresAt: now + ttlMs, updatedAt: now };
    return true;
  }

  async renewProgressLease(ownerId: string, ttlMs: number, now = Date.now()) {
    if (!this.lease || this.lease.ownerId !== ownerId || this.lease.expiresAt <= now) return false;
    this.lease = { ...this.lease, expiresAt: now + ttlMs, updatedAt: now };
    return true;
  }

  async releaseProgressLease(ownerId: string) {
    if (this.lease?.ownerId === ownerId) this.lease = null;
  }

  async getProgressLease() {
    return this.lease;
  }

  async addDiagnostic(diagnostic: Omit<ReaderSyncDiagnostic, 'id' | 'createdAt'>, now = Date.now()) {
    const value: ReaderSyncDiagnostic = { ...diagnostic, id: createId('diagnostic'), createdAt: now };
    this.diagnostics.push(value);
    return value;
  }

  async listDiagnostics(limit = 100) {
    return [...this.diagnostics].sort((left, right) => right.createdAt - left.createdAt).slice(0, limit);
  }

  async listQuarantine(limit = 100) {
    return [...this.quarantine].sort((left, right) => right.createdAt - left.createdAt).slice(0, limit);
  }

  async clearAll() {
    this.preferences.clear();
    this.progress.clear();
    this.slotMutationIds.clear();
    this.diagnostics.length = 0;
    this.quarantine.length = 0;
    this.clientId = createId('client');
    this.sequence = 0;
    this.lease = null;
  }
}
