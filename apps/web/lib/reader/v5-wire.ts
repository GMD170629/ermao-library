import type {
  ReaderChapterPresentation,
  ReaderOpaqueLocator,
  ReaderPagePresentation,
  ReaderPlaybackPresentation,
  ReaderPositionPresentation,
  ReaderPositionReport
} from '@shuku/reader-core';

export const READER_V5_SCHEMA_VERSION = 5 as const;
export const READER_V5_LOCATOR_MAX_BYTES = 64 * 1024;

export type ReaderV5ProgressIdentity = Readonly<{
  serverIdentity: string;
  userId: string;
  clientId: string;
  bookId: string;
  resourceId: string;
}>;

export type ReaderV5ProgressPut = Readonly<{
  schemaVersion: typeof READER_V5_SCHEMA_VERSION;
  clientId: string;
  mutationId: string;
  capturedAtEpochMillis: number;
  position: ReaderPositionReport;
}>;

export type ReaderV5ProgressSnapshot = Readonly<{
  schemaVersion: typeof READER_V5_SCHEMA_VERSION;
  revision: number;
  clientId: string;
  mutationId: string;
  capturedAtEpochMillis: number;
  receivedAtEpochMillis: number;
  position: ReaderPositionReport;
}>;

export type ReaderV5ProgressWriteResult = Readonly<{
  acceptedMutationId: string;
  acceptedRevision: number;
  currentSnapshot: ReaderV5ProgressSnapshot;
}>;

export type ReaderV5ProgressRecord = ReaderV5ProgressIdentity & Readonly<{
  key: string;
  schemaVersion: typeof READER_V5_SCHEMA_VERSION;
  mutationId: string;
  revision: number;
  capturedAtEpochMillis: number;
  position: ReaderPositionReport;
}>;

export type ReaderV5PendingMutation = ReaderV5ProgressIdentity & Readonly<{
  key: string;
  schemaVersion: typeof READER_V5_SCHEMA_VERSION;
  mutationId: string;
  capturedAtEpochMillis: number;
  position: ReaderPositionReport;
}>;

export type ReaderV5ProgressSaveInput = Omit<ReaderV5ProgressIdentity, 'clientId'> & Readonly<{
  position: ReaderPositionReport;
}>;

export type ReaderV5ProgressUpload = Readonly<{
  resourceId: string;
  request: ReaderV5ProgressPut;
}>;

export type ReaderV5RemoteProgressNotice = Readonly<{
  revision: number;
  sourceClientId: string;
  mutationId: string;
  position: ReaderPositionReport;
  receivedAtEpochMillis: number;
  capturedAtEpochMillis: number;
}>;

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

function isJsonValue(value: unknown, seen: Set<object> = new Set()): boolean {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value !== 'object') return false;
  if (seen.has(value)) return false;
  let prototype: object | null;
  try {
    prototype = Object.getPrototypeOf(value);
  } catch {
    return false;
  }
  if (Array.isArray(value)) {
    if (prototype !== Array.prototype) return false;
  } else if (prototype !== Object.prototype && prototype !== null) {
    return false;
  }
  try {
    if (Object.getOwnPropertySymbols(value).length > 0) return false;
  } catch {
    return false;
  }
  seen.add(value);
  try {
    if (Array.isArray(value)) return value.every((item) => isJsonValue(item, seen));
    return Object.keys(value as UnknownRecord).every((key) => isJsonValue((value as UnknownRecord)[key], seen));
  } catch {
    return false;
  } finally {
    seen.delete(value);
  }
}

function hasOnlyKeys(value: UnknownRecord, keys: readonly string[]) {
  const allowed = new Set(keys);
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasKeys(value: UnknownRecord, keys: readonly string[]) {
  return keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}

function jsonByteLength(value: unknown): number | null {
  try {
    const encoded = JSON.stringify(value);
    return typeof encoded === 'string' ? new TextEncoder().encode(encoded).byteLength : null;
  } catch {
    return null;
  }
}

function nonEmptyString(value: unknown, maxLength: number): string | null {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= maxLength
    ? value
    : null;
}

function nullableString(value: unknown, maxLength: number): string | null | undefined {
  if (value === null) return null;
  if (typeof value === 'string' && value.length <= maxLength) return value;
  return undefined;
}

function boundedNumber(value: unknown, minimum: number, maximum: number): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= minimum && value <= maximum
    ? value
    : null;
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function nullableNonNegativeInteger(value: unknown): number | null | undefined {
  if (value === null) return null;
  return nonNegativeInteger(value);
}

function parseChapter(value: unknown): ReaderChapterPresentation | null | undefined {
  if (value === null) return null;
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['href', 'title', 'index']) || !hasKeys(item, ['href', 'title', 'index'])) return undefined;
  const href = nullableString(item.href, 8192);
  const title = nullableString(item.title, 4096);
  const index = nullableNonNegativeInteger(item.index);
  if (href === undefined || title === undefined || index === undefined) return undefined;
  return { href, title, index };
}

function parsePage(value: unknown): ReaderPagePresentation | null | undefined {
  if (value === null) return null;
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['number', 'total']) || !hasKeys(item, ['number', 'total'])) return undefined;
  const number = nonNegativeInteger(item.number);
  const total = nullableNonNegativeInteger(item.total);
  if (number === null || number < 1 || total === undefined || (total !== null && total < 1)) return undefined;
  return { number, total };
}

function parsePlayback(value: unknown): ReaderPlaybackPresentation | null | undefined {
  if (value === null) return null;
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['positionMillis', 'durationMillis']) || !hasKeys(item, ['positionMillis', 'durationMillis'])) return undefined;
  const positionMillis = nonNegativeInteger(item.positionMillis);
  const durationMillis = nullableNonNegativeInteger(item.durationMillis);
  if (positionMillis === null || durationMillis === undefined) return undefined;
  return { positionMillis, durationMillis };
}

function parsePresentation(value: unknown): ReaderPositionPresentation | null {
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['displayPercent', 'totalProgression', 'currentHref', 'chapter', 'page', 'playback'])
    || !hasKeys(item, ['displayPercent', 'totalProgression', 'currentHref', 'chapter', 'page', 'playback'])) return null;
  const displayPercent = boundedNumber(item.displayPercent, 0, 100);
  const totalProgression = boundedNumber(item.totalProgression, 0, 1);
  const currentHref = nullableString(item.currentHref, 8192);
  const chapter = parseChapter(item.chapter);
  const page = parsePage(item.page);
  const playback = parsePlayback(item.playback);
  if (displayPercent === null || totalProgression === null || currentHref === undefined
    || chapter === undefined || page === undefined || playback === undefined) return null;
  return { displayPercent, totalProgression, currentHref, chapter, page, playback };
}

/**
 * Parses only the v5 envelope and presentation. The Locator is intentionally
 * not traversed or normalized; the original object is returned unchanged.
 */
export function parseReaderV5PositionReport(value: unknown): ReaderPositionReport | null {
  if (!isJsonValue(value)) return null;
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['locator', 'presentation']) || !hasKeys(item, ['locator', 'presentation'])) return null;
  const locator = record(item.locator);
  if (!locator || !isJsonValue(locator)) return null;
  const locatorBytes = jsonByteLength(locator);
  const presentation = parsePresentation(item.presentation);
  if (!locator || locatorBytes === null || locatorBytes > READER_V5_LOCATOR_MAX_BYTES || !presentation) return null;
  return { locator: locator as ReaderOpaqueLocator, presentation };
}

function validMutationId(value: unknown): value is string {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(value);
}

function validClientId(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= 256;
}

function validTimestamp(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function validRevision(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1;
}

export function parseReaderV5ProgressPut(value: unknown): ReaderV5ProgressPut | null {
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['schemaVersion', 'clientId', 'mutationId', 'capturedAtEpochMillis', 'position'])
    || item.schemaVersion !== READER_V5_SCHEMA_VERSION || !validClientId(item.clientId)
    || !validMutationId(item.mutationId) || !validTimestamp(item.capturedAtEpochMillis)) return null;
  const position = parseReaderV5PositionReport(item.position);
  return position ? {
    schemaVersion: READER_V5_SCHEMA_VERSION,
    clientId: item.clientId,
    mutationId: item.mutationId,
    capturedAtEpochMillis: item.capturedAtEpochMillis,
    position
  } : null;
}

export function parseReaderV5ProgressSnapshot(value: unknown): ReaderV5ProgressSnapshot | null {
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['schemaVersion', 'revision', 'clientId', 'mutationId', 'capturedAtEpochMillis', 'receivedAtEpochMillis', 'position'])
    || item.schemaVersion !== READER_V5_SCHEMA_VERSION || !validRevision(item.revision)
    || !validClientId(item.clientId) || !validMutationId(item.mutationId)
    || !validTimestamp(item.capturedAtEpochMillis) || !validTimestamp(item.receivedAtEpochMillis)) return null;
  const position = parseReaderV5PositionReport(item.position);
  return position ? {
    schemaVersion: READER_V5_SCHEMA_VERSION,
    revision: item.revision,
    clientId: item.clientId,
    mutationId: item.mutationId,
    capturedAtEpochMillis: item.capturedAtEpochMillis,
    receivedAtEpochMillis: item.receivedAtEpochMillis,
    position
  } : null;
}

export function parseReaderV5ProgressWriteResult(value: unknown): ReaderV5ProgressWriteResult | null {
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['acceptedMutationId', 'acceptedRevision', 'currentSnapshot'])
    || !validMutationId(item.acceptedMutationId) || !validRevision(item.acceptedRevision)) return null;
  const currentSnapshot = parseReaderV5ProgressSnapshot(item.currentSnapshot);
  return currentSnapshot ? {
    acceptedMutationId: item.acceptedMutationId,
    acceptedRevision: item.acceptedRevision,
    currentSnapshot
  } : null;
}

export function positionReportsEqual(left: ReaderPositionReport | null, right: ReaderPositionReport | null) {
  if (!left || !right) return left === right;
  try {
    return canonicalJson(left) === canonicalJson(right);
  } catch {
    return false;
  }
}

/** Canonical JSON comparison keeps JSON object key order from changing dedupe semantics. */
function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'undefined';
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  const object = value as Record<string, unknown>;
  return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(object[key])}`).join(',')}}`;
}

/** Stable, bounded bookmark identity for a complete JSON-semantic position. */
export function readerPositionDigest(position: ReaderPositionReport) {
  const canonical = canonicalJson(position);
  let first = 2166136261;
  let second = 2166136261;
  for (let index = 0; index < canonical.length; index += 1) {
    const code = canonical.charCodeAt(index);
    first = Math.imul(first ^ code, 16777619);
    second = Math.imul(second ^ (code + index), 16777619);
  }
  return `v5:${canonical.length}:${(first >>> 0).toString(16).padStart(8, '0')}${(second >>> 0).toString(16).padStart(8, '0')}`;
}
