import type { JsonDocumentCodec } from '../../../shared/files/snapshot-document-store';
import {
  type ValidationResult,
  finiteNumberInRange,
  hasOnlyKeys,
  isRecord,
  nonEmptyString,
  nonNegativeSafeInteger,
} from '../../../shared/validation/unknown';
import { parseServerAddress } from '../../server-connection/public';
import {
  isSafeRuntimeId,
  MAXIMUM_READER_PROGRESS_ENTRIES,
  readerProgressSlotKey,
  type LocalProgressEntry,
  type ProgressConnection,
  type ProgressOwner,
  type ReaderProgressDocument,
} from '../model/reader-progress';
import {
  decodeReaderLocation,
  encodeReaderLocation,
} from '../model/reader-location';

const DOCUMENT_KEYS = new Set([
  'format',
  'schemaVersion',
  'generation',
  'connection',
  'client',
  'updatedAtMs',
  'entries',
]);
const CONNECTION_KEYS = new Set(['profileId', 'baseUrl']);
const CLIENT_KEYS = new Set(['id', 'lastSequence']);
const ENTRY_KEYS = new Set([
  'mutationId',
  'clientSequence',
  'owner',
  'workId',
  'mediaVersionId',
  'volumeId',
  'contentFingerprint',
  'location',
  'percent',
  'createdAtMs',
  'updatedAtMs',
]);
const LOCAL_OWNER_KEYS = new Set(['kind']);
const USER_OWNER_KEYS = new Set(['kind', 'userId']);

function decodeConnection(value: unknown): ProgressConnection | null {
  if (!isRecord(value) || !hasOnlyKeys(value, CONNECTION_KEYS)) {
    return null;
  }
  const profileId = nonEmptyString(value.profileId, 128);
  const baseUrl = nonEmptyString(value.baseUrl, 2_048);
  if (
    profileId === null ||
    !isSafeRuntimeId(profileId) ||
    baseUrl === null
  ) {
    return null;
  }
  const parsed = parseServerAddress(baseUrl);
  if (!parsed.ok || parsed.baseUrl.value !== baseUrl) {
    return null;
  }
  return { profileId, baseUrl };
}

function decodeOwner(value: unknown): ProgressOwner | null {
  if (!isRecord(value)) {
    return null;
  }
  if (value.kind === 'local' && hasOnlyKeys(value, LOCAL_OWNER_KEYS)) {
    return { kind: 'local' };
  }
  if (value.kind === 'user' && hasOnlyKeys(value, USER_OWNER_KEYS)) {
    const userId = nonEmptyString(value.userId, 191);
    return userId === null ? null : { kind: 'user', userId };
  }
  return null;
}

function decodeEntry(value: unknown): LocalProgressEntry | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ENTRY_KEYS)) {
    return null;
  }

  const mutationId = nonEmptyString(value.mutationId, 128);
  const clientSequence = nonNegativeSafeInteger(value.clientSequence);
  const owner = decodeOwner(value.owner);
  const workId = nonEmptyString(value.workId, 191);
  const mediaVersionId = nonEmptyString(value.mediaVersionId, 191);
  const volumeId = nonEmptyString(value.volumeId, 191);
  const contentFingerprint = nonEmptyString(
    value.contentFingerprint,
    191,
  );
  const location = decodeReaderLocation(value.location);
  const percent = finiteNumberInRange(value.percent, 0, 100);
  const createdAtMs = nonNegativeSafeInteger(value.createdAtMs);
  const updatedAtMs = nonNegativeSafeInteger(value.updatedAtMs);
  if (
    mutationId === null ||
    !isSafeRuntimeId(mutationId) ||
    clientSequence === null ||
    clientSequence < 1 ||
    owner === null ||
    workId === null ||
    mediaVersionId === null ||
    volumeId === null ||
    contentFingerprint === null ||
    !location.ok ||
    percent === null ||
    createdAtMs === null ||
    updatedAtMs === null ||
    updatedAtMs < createdAtMs ||
    (location.value.kind === 'comic' &&
      volumeId !== location.value.volumeId)
  ) {
    return null;
  }

  return {
    mutationId,
    clientSequence,
    owner,
    workId,
    mediaVersionId,
    volumeId,
    contentFingerprint,
    location: location.value,
    percent,
    createdAtMs,
    updatedAtMs,
  };
}

function encodeOwner(owner: ProgressOwner): unknown {
  return owner.kind === 'local'
    ? { kind: owner.kind }
    : { kind: owner.kind, userId: owner.userId };
}

function encodeEntry(entry: LocalProgressEntry): unknown {
  return {
    mutationId: entry.mutationId,
    clientSequence: entry.clientSequence,
    owner: encodeOwner(entry.owner),
    workId: entry.workId,
    mediaVersionId: entry.mediaVersionId,
    volumeId: entry.volumeId,
    contentFingerprint: entry.contentFingerprint,
    location: encodeReaderLocation(entry.location),
    percent: entry.percent,
    createdAtMs: entry.createdAtMs,
    updatedAtMs: entry.updatedAtMs,
  };
}

export const readerProgressDocumentCodec: JsonDocumentCodec<ReaderProgressDocument> =
  {
    decode(value: unknown): ValidationResult<ReaderProgressDocument> {
      if (
        !isRecord(value) ||
        !hasOnlyKeys(value, DOCUMENT_KEYS) ||
        value.format !== 'shuku.reader-progress' ||
        value.schemaVersion !== 3 ||
        !Array.isArray(value.entries) ||
        value.entries.length > MAXIMUM_READER_PROGRESS_ENTRIES ||
        !isRecord(value.client) ||
        !hasOnlyKeys(value.client, CLIENT_KEYS)
      ) {
        return { ok: false, reason: 'INVALID_READER_PROGRESS_DOCUMENT' };
      }

      const generation = nonNegativeSafeInteger(value.generation);
      const connection = decodeConnection(value.connection);
      const clientId = nonEmptyString(value.client.id, 128);
      const lastSequence = nonNegativeSafeInteger(
        value.client.lastSequence,
      );
      const updatedAtMs = nonNegativeSafeInteger(value.updatedAtMs);
      const entries = value.entries.map(decodeEntry);
      if (
        generation === null ||
        generation < 1 ||
        connection === null ||
        clientId === null ||
        !isSafeRuntimeId(clientId) ||
        lastSequence === null ||
        updatedAtMs === null ||
        entries.some((entry) => entry === null)
      ) {
        return { ok: false, reason: 'INVALID_READER_PROGRESS_DOCUMENT' };
      }

      const validEntries = entries.filter(
        (entry): entry is LocalProgressEntry => entry !== null,
      );
      const sequences = new Set(
        validEntries.map((entry) => entry.clientSequence),
      );
      const mutationIds = new Set(
        validEntries.map((entry) => entry.mutationId),
      );
      const slotKeys = new Set(
        validEntries.map(readerProgressSlotKey),
      );
      const maximumSequence = validEntries.reduce(
        (maximum, entry) => Math.max(maximum, entry.clientSequence),
        0,
      );
      const maximumUpdatedAt = validEntries.reduce(
        (maximum, entry) => Math.max(maximum, entry.updatedAtMs),
        0,
      );
      if (
        sequences.size !== validEntries.length ||
        mutationIds.size !== validEntries.length ||
        slotKeys.size !== validEntries.length ||
        lastSequence < maximumSequence ||
        updatedAtMs < maximumUpdatedAt
      ) {
        return { ok: false, reason: 'INVALID_READER_PROGRESS_DOCUMENT' };
      }

      return {
        ok: true,
        value: {
          format: 'shuku.reader-progress',
          schemaVersion: 3,
          generation,
          connection,
          client: { id: clientId, lastSequence },
          updatedAtMs,
          entries: validEntries,
        },
      };
    },

    encode(document: ReaderProgressDocument): unknown {
      return {
        format: document.format,
        schemaVersion: document.schemaVersion,
        generation: document.generation,
        connection: document.connection,
        client: document.client,
        updatedAtMs: document.updatedAtMs,
        entries: document.entries.map(encodeEntry),
      };
    },
  };
