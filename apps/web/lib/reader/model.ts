import {
  READER_SCHEMA_VERSION,
  comparePublicationLocations,
  type PublicationLocation,
  type ReaderLocation,
  type ReaderPreferences
} from '@shuku/reader-core';

export const READER_PROGRESS_DB_NAME = 'shuku-reader-v4';
export const READER_DB_SCHEMA_VERSION = 4;
export const READER_PROGRESS_DEBOUNCE_MS = 500;

export type AudioProgressLocation = Readonly<{ kind: 'audio'; volumeId: string; fileId: string; chapterId: string | null; positionMs: number }>;
export type ReaderProgressLocation = ReaderLocation | AudioProgressLocation;

export type ReaderPreferenceSnapshot = {
  key: string;
  userId: string;
  workId: string;
  schemaVersion: typeof READER_SCHEMA_VERSION;
  preferences: ReaderPreferences;
  updatedAt: number;
};

export type ExactProgressIdentity = Readonly<{
  serverIdentity: string;
  userId: string;
  clientId: string;
  workId: string;
  volumeId: string;
}>;

export type ExactProgressRecord = ExactProgressIdentity & Readonly<{
  key: string;
  schemaVersion: 1;
  locator: PublicationLocation;
  displayPercent: number | null;
  /** Compatibility alias for non-Reader audio presentation only. */
  percent?: number | null;
  revision: number;
  capturedAtEpochMillis: number;
  /** Compatibility alias for the separate audio player. */
  updatedAtEpochMillis?: number;
}>;

export type ReaderProgressConflict = Readonly<{
  clientId: string;
  revision: number;
  locator: PublicationLocation;
  displayPercent: number;
  receivedAtEpochMillis: number;
  capturedAtEpochMillis?: number;
}>;

export type PendingProgressMutation = Readonly<{
  key: string;
  schemaVersion: 1;
  serverIdentity: string;
  userId: string;
  workId: string;
  volumeId: string;
  clientId: string;
  mutationId: string;
  baseRevision: number;
  capturedAtEpochMillis: number;
  locator: PublicationLocation;
  displayPercent: number | null;
}>;

export type ExactProgressSaveInput = Readonly<{
  serverIdentity: string;
  userId: string;
  workId: string;
  volumeId: string;
  baseRevision: number;
  locator: PublicationLocation;
  displayPercent: number | null;
}>;

export type ProgressSaveInput = ExactProgressSaveInput;

export type ReaderProgressPut = Readonly<{
  schemaVersion: 4;
  clientId: string;
  mutationId: string;
  baseRevision: number;
  capturedAtEpochMillis: number;
  locator: PublicationLocation;
}>;

export type ReaderProgressSnapshot = Readonly<{
  schemaVersion: 4;
  clientId: string;
  revision: number;
  locator: PublicationLocation;
  displayPercent: number;
  receivedAtEpochMillis: number;
  capturedAtEpochMillis?: number;
}>;

export type RemoteProgressNotice = Readonly<{
  revision: number;
  sourceClientId: string;
  locator: PublicationLocation;
  displayPercent: number;
  receivedAtEpochMillis: number;
  capturedAtEpochMillis?: number;
}>;

/** Future device-directory seam; null keeps the localized “other device” fallback. */
export type ReaderDeviceLabelResolver = (clientId: string) => string | null;

export type PendingVsServerDecision =
  | Readonly<{ kind: 'server'; snapshot: ReaderProgressSnapshot | null; discardPending: boolean }>
  | Readonly<{ kind: 'local-pending'; pending: PendingProgressMutation; localExact: ExactProgressRecord }>
  | Readonly<{ kind: 'requires-choice'; pending: PendingProgressMutation; localExact: ExactProgressRecord; server: ReaderProgressSnapshot }>;

export type ProgressUpload = Readonly<{
  volumeId: string;
  request: ReaderProgressPut;
}>;

export class ReaderProgressConflictError extends Error {
  constructor(readonly conflict: ReaderProgressConflict) {
    super('Reader progress revision conflict');
    this.name = 'ReaderProgressConflictError';
  }
}

export type ProgressSyncTransport = (
  upload: ProgressUpload,
  signal: AbortSignal
) => Promise<ReaderProgressSnapshot>;

export type ProgressQueryResult =
  | Readonly<{ kind: 'unchanged'; etag: string | null }>
  | Readonly<{ kind: 'current'; snapshot: ReaderProgressSnapshot | null; etag: string | null }>;

export type ProgressQueryTransport = (
  volumeId: string,
  etag: string | null,
  signal: AbortSignal
) => Promise<ProgressQueryResult>;

export type ReaderSyncDiagnostic = {
  id: string;
  level: 'info' | 'warning' | 'error';
  code: string;
  message: string;
  createdAt: number;
  data?: Record<string, unknown>;
};

function encodeKeyPart(value: string) {
  return `${value.length}:${value}`;
}

export function preferenceKey(userId: string, workId: string) {
  return `${encodeURIComponent(userId)}::${encodeURIComponent(workId)}`;
}

export function exactProgressKey(identity: ExactProgressIdentity) {
  return [identity.serverIdentity, identity.userId, identity.clientId, identity.workId, identity.volumeId]
    .map(encodeKeyPart).join('|');
}

export function syncStateKey(identity: Pick<ExactProgressIdentity, 'serverIdentity' | 'userId' | 'clientId' | 'workId' | 'volumeId'>) {
  return [identity.serverIdentity, identity.userId, identity.clientId, identity.workId, identity.volumeId]
    .map(encodeKeyPart).join('|');
}

/** Progress belongs to work + volume. */
export function progressLocationsMatch(expected: PublicationLocation, actual: PublicationLocation) {
  return comparePublicationLocations(expected, actual).precision === 'exact';
}

export function currentReaderServerIdentity() {
  if (typeof window !== 'undefined' && window.location.origin) return window.location.origin;
  return 'same-origin';
}

export function normalizedPercent(value: number | null) {
  if (value === null || !Number.isFinite(value) || value < 0 || value > 100) return null;
  return value;
}
