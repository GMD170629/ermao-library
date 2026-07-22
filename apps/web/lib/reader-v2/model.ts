import { READER_SCHEMA_VERSION, type ReaderLocation, type ReaderPreferences } from '@shuku/reader-core';

export const READER_V2_DB_NAME = 'shuku-reader-v2';
export const READER_V2_DB_VERSION = 1;
export const READER_PROGRESS_DEBOUNCE_MS = 1_500;

/**
 * Playback progress is part of the shared Reader V2 persistence/sync domain,
 * but audio is deliberately not a visual reader kind. Keeping the location
 * here avoids widening `ReaderKind` or letting audio enter `/reader` adapter
 * APIs while still giving the durable progress pipeline one typed contract.
 */
export type AudioProgressLocation = {
  kind: 'audio';
  volumeId: string | null;
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
  editionId: string;
  volumeId?: string | null;
  contentFingerprint: string;
  location: ReaderProgressLocation;
  percent: number;
};

export type ProgressMutation = ProgressMutationInput & {
  schemaVersion: 2;
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
  'schemaVersion' | 'mutationId' | 'userId' | 'clientId' | 'clientSequence' | 'contentFingerprint' | 'volumeId' | 'location' | 'percent'
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
  return [input.userId, input.editionId, input.volumeId ?? '', input.contentFingerprint]
    .map(encodeURIComponent)
    .join('::');
}

export function toProgressPutBody(mutation: ProgressMutation): ProgressPutBody {
  return {
    schemaVersion: mutation.schemaVersion,
    mutationId: mutation.mutationId,
    userId: mutation.userId,
    clientId: mutation.clientId,
    clientSequence: mutation.clientSequence,
    contentFingerprint: mutation.contentFingerprint,
    volumeId: mutation.volumeId,
    location: mutation.location,
    percent: mutation.percent
  };
}
