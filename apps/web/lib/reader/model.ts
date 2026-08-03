import { READER_SCHEMA_VERSION, type ReaderLocation, type ReaderPreferences } from '@shuku/reader-core';

// Keep the physical IndexedDB name so the v3 upgrader can quarantine or migrate legacy local records.
export const READER_PROGRESS_DB_NAME = 'shuku-reader-v2';
export const READER_DB_SCHEMA_VERSION = 3;
export const READER_PROGRESS_DEBOUNCE_MS = 1_500;

/**
 * Playback progress is part of the shared Reader v3 persistence/sync domain,
 * but audio is deliberately not a visual reader kind. Keeping the location
 * here avoids widening `ReaderKind` or letting audio enter `/reader` adapter
 * APIs while still giving the durable progress pipeline one typed contract.
 */
export type AudioProgressLocation = {
  kind: 'audio';
  volumeId: string;
  fileId: string;
  chapterId: string | null;
  positionMs: number;
};

export type ReaderProgressLocation = ReaderLocation | AudioProgressLocation;

export type ReaderPreferenceSnapshot = {
  key: string;
  userId: string;
  workId: string;
  schemaVersion: typeof READER_SCHEMA_VERSION;
  preferences: ReaderPreferences;
  updatedAt: number;
};

export type ProgressMutationInput = {
  userId: string;
  workId: string;
  volumeId: string;
  contentFingerprint: string;
  location: ReaderProgressLocation;
  percent: number;
};

export type ProgressMutation = ProgressMutationInput & {
  schemaVersion: 3;
  mutationId: string;
  clientId: string;
  clientSequence: number;
  slotKey: string;
  createdAt: number;
  updatedAt: number;
  retryCount: number;
  nextAttemptAt: number;
};

export type ProgressPutBody = Pick<
  ProgressMutation,
  'schemaVersion' | 'mutationId' | 'clientId' | 'clientSequence' | 'contentFingerprint' | 'location' | 'percent'
>;

export type ProgressSyncResult =
  | { outcome: 'accepted' }
  | { outcome: 'stale' }
  | { outcome: 'fingerprint-conflict'; message?: string }
  | { outcome: 'terminal'; message: string };

export type ProgressSyncTransport = (mutation: Readonly<ProgressMutation>, signal: AbortSignal) => Promise<ProgressSyncResult>;

export type ReaderSyncLease = {
  key: 'progress-sync';
  ownerId: string;
  expiresAt: number;
  updatedAt: number;
};

export type ReaderSyncDiagnostic = {
  id: string;
  level: 'info' | 'warning' | 'error';
  code: string;
  message: string;
  createdAt: number;
  data?: Record<string, unknown>;
};

export type QuarantinedProgress = {
  id: string;
  mutation: ProgressMutation;
  reason: 'fingerprint-conflict' | 'terminal' | 'unsafe-legacy';
  message: string;
  createdAt: number;
};

export function preferenceKey(userId: string, workId: string) {
  return `${encodeURIComponent(userId)}::${encodeURIComponent(workId)}`;
}

export function progressSlotKey(input: ProgressMutationInput) {
  return [input.userId, input.volumeId, input.contentFingerprint]
    .map(encodeURIComponent)
    .join('::');
}

export function toProgressPutBody(mutation: ProgressMutation): ProgressPutBody {
  return {
    schemaVersion: mutation.schemaVersion,
    mutationId: mutation.mutationId,
    clientId: mutation.clientId,
    clientSequence: mutation.clientSequence,
    contentFingerprint: mutation.contentFingerprint,
    location: mutation.location,
    percent: mutation.percent
  };
}
