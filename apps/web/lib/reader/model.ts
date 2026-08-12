import { READER_SCHEMA_VERSION, type ReaderLocation, type ReaderPreferences } from '@shuku/reader-core';

// Keep the physical database name so the v4 upgrader can atomically migrate
// exact positions out of the former durable progress outbox.
export const READER_PROGRESS_DB_NAME = 'shuku-reader-v2';
export const READER_DB_SCHEMA_VERSION = 4;
export const READER_PROGRESS_DEBOUNCE_MS = 500;
export const READER_ENGINE_PAYLOAD_MAX_BYTES = 64 * 1024;

export type AudioProgressLocation = {
  kind: 'audio';
  volumeId: string;
  fileId: string;
  chapterId: string | null;
  positionMs: number;
};

export type ReaderProgressLocation = ReaderLocation | AudioProgressLocation;

export type ReaderTextQuote = Readonly<{
  exact: string;
  prefix?: string;
  suffix?: string;
}>;

export type ReaderLocationContentFingerprint = Readonly<{
  originalFileHash: string;
  parserVersion: string;
  normalizationVersion: string;
}>;

export type ReaderEngineLocator = Readonly<{
  engine: 'readium' | 'foliate';
  platform: 'android' | 'ios' | 'web';
  version: string;
  payload: Readonly<Record<string, unknown>>;
}>;

export type ReaderV4Location =
  | Readonly<{
    kind: 'reflow';
    resourceKey?: string;
    progression?: number;
    position?: number;
    textQuote?: ReaderTextQuote;
    contentFingerprint?: ReaderLocationContentFingerprint;
    engineLocator?: ReaderEngineLocator;
  }>
  | Readonly<{
    kind: 'comic';
    pageIndex: number;
    engineLocator?: ReaderEngineLocator;
  }>
  | Readonly<{
    kind: 'pdf';
    pageNumber: number;
    engineLocator?: ReaderEngineLocator;
  }>
  | Readonly<{
    kind: 'audio';
    fileId: string;
    chapterId: string | null;
    positionMs: number;
    engineLocator?: ReaderEngineLocator;
  }>;

export type ReaderProgressSnapshot = Readonly<{
  schemaVersion: 4;
  clientId: string;
  updatedAtEpochMillis: number;
  percent: number;
  location: ReaderV4Location | null;
  contentFingerprint: string;
}>;

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
  volumeId: string;
  localContentFingerprint: string;
}>;

export type ExactProgressRecord = ExactProgressIdentity & Readonly<{
  key: string;
  schemaVersion: 1;
  workId: string;
  location: ReaderProgressLocation;
  percent: number | null;
  updatedAtEpochMillis: number;
}>;

export type ProgressSaveInput = Readonly<{
  serverIdentity: string;
  userId: string;
  workId: string;
  volumeId: string;
  /** Stable fingerprint of the locally opened publication, not the server version token. */
  localContentFingerprint: string;
  /** Current server volume version token used to validate the uploaded location. */
  contentFingerprint: string;
  location: ReaderProgressLocation;
  percent: number | null;
  locationContentFingerprint?: ReaderLocationContentFingerprint;
}>;

export type ProgressUpload = Readonly<{
  volumeId: string;
  snapshot: ReaderProgressSnapshot;
}>;

export type ProgressSyncTransport = (
  upload: ProgressUpload,
  signal: AbortSignal
) => Promise<ReaderProgressSnapshot>;

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
  return [
    identity.serverIdentity,
    identity.userId,
    identity.clientId,
    identity.volumeId,
    identity.localContentFingerprint
  ].map(encodeKeyPart).join('|');
}

export function localContentFingerprintKey(
  fingerprint: ReaderLocationContentFingerprint | undefined,
  fallbackServerFingerprint: string
) {
  if (!fingerprint) return fallbackServerFingerprint;
  return [
    fingerprint.originalFileHash,
    fingerprint.parserVersion,
    fingerprint.normalizationVersion
  ].map(encodeKeyPart).join('|');
}

export function currentReaderServerIdentity() {
  if (typeof window !== 'undefined' && window.location.origin) return window.location.origin;
  return 'same-origin';
}

export function normalizedPercent(value: number | null) {
  if (value === null || !Number.isFinite(value) || value < 0 || value > 100) return null;
  return value;
}
