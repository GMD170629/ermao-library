import type { ReaderKind } from '@shuku/reader-core';

import {
  decodeReaderLocation,
  type ReaderProgressLocation,
} from './reader-location';

const SAFE_RUNTIME_ID = /^[A-Za-z0-9-]{1,128}$/;
const MAXIMUM_IDENTIFIER_LENGTH = 191;
export const MAXIMUM_READER_PROGRESS_ENTRIES = 128;

export type ProgressOwner =
  | Readonly<{ kind: 'local' }>
  | Readonly<{ kind: 'user'; userId: string }>;

export type ProgressConnection = Readonly<{
  profileId: string;
  baseUrl: string;
}>;

export type LocalProgressEntry = Readonly<{
  mutationId: string;
  clientSequence: number;
  owner: ProgressOwner;
  workId: string;
  mediaVersionId: string;
  volumeId: string;
  contentFingerprint: string;
  location: ReaderProgressLocation;
  percent: number;
  createdAtMs: number;
  updatedAtMs: number;
}>;

export type ReaderProgressDocument = Readonly<{
  format: 'shuku.reader-progress';
  schemaVersion: 3;
  generation: number;
  connection: ProgressConnection;
  client: Readonly<{
    id: string;
    lastSequence: number;
  }>;
  updatedAtMs: number;
  entries: readonly LocalProgressEntry[];
}>;

export type RecordReaderProgressCommand = Readonly<{
  connection: ProgressConnection;
  owner: ProgressOwner;
  workId: string;
  mediaVersionId: string;
  volumeId: string;
  contentFingerprint: string;
  location: ReaderProgressLocation;
  percent: number;
  nowMs: number;
  proposedClientId: string;
  mutationId: string;
}>;

export type FindReaderProgressQuery = Readonly<{
  connection: ProgressConnection;
  owner: ProgressOwner;
  workId: string;
  mediaVersionId: string;
  volumeId: string;
  contentFingerprint: string;
  readerKind: ReaderKind;
}>;

export type RecordReaderProgressResult = Readonly<{
  document: ReaderProgressDocument;
  entry: LocalProgressEntry;
}>;

export type ReaderProgressInvariantErrorCode =
  | 'CONNECTION_MISMATCH'
  | 'INVALID_PROGRESS'
  | 'SEQUENCE_EXHAUSTED';

export class ReaderProgressInvariantError extends Error {
  constructor(readonly code: ReaderProgressInvariantErrorCode) {
    super(`Reader progress invariant failed: ${code}`);
    this.name = 'ReaderProgressInvariantError';
  }
}

export function isSafeRuntimeId(value: string): boolean {
  return SAFE_RUNTIME_ID.test(value);
}

function isIdentifier(value: string): boolean {
  return (
    value.length > 0 &&
    value.length <= MAXIMUM_IDENTIFIER_LENGTH &&
    value.trim() === value
  );
}

function ownerIsValid(owner: ProgressOwner): boolean {
  return (
    owner.kind === 'local' ||
    (owner.kind === 'user' && isIdentifier(owner.userId))
  );
}

function ownersEqual(
  left: ProgressOwner,
  right: ProgressOwner,
): boolean {
  return (
    left.kind === right.kind &&
    (left.kind === 'local' ||
      (right.kind === 'user' && left.userId === right.userId))
  );
}

type ReaderProgressSlot = Readonly<{
  owner: ProgressOwner;
  workId: string;
  mediaVersionId: string;
  volumeId: string;
  contentFingerprint: string;
  location: Readonly<{ kind: ReaderProgressLocation['kind'] }>;
}>;

export function readerProgressSlotKey(
  slot: ReaderProgressSlot,
): string {
  return JSON.stringify([
    slot.owner.kind,
    slot.owner.kind === 'user' ? slot.owner.userId : null,
    slot.workId,
    slot.mediaVersionId,
    slot.volumeId,
    slot.contentFingerprint,
    slot.location.kind,
  ]);
}

function sameSlot(
  entry: LocalProgressEntry,
  command: RecordReaderProgressCommand,
): boolean {
  return readerProgressSlotKey(entry) === readerProgressSlotKey(command);
}

function retainEntriesForNewSlot(
  entries: readonly LocalProgressEntry[],
): readonly LocalProgressEntry[] {
  if (entries.length < MAXIMUM_READER_PROGRESS_ENTRIES) {
    return entries;
  }

  const oldest = entries.reduce((currentOldest, candidate) =>
    candidate.updatedAtMs < currentOldest.updatedAtMs ||
    (candidate.updatedAtMs === currentOldest.updatedAtMs &&
      candidate.clientSequence < currentOldest.clientSequence)
      ? candidate
      : currentOldest,
  );
  return entries.filter(
    (entry) => entry.mutationId !== oldest.mutationId,
  );
}

function commandIsValid(
  command: RecordReaderProgressCommand,
  location: ReaderProgressLocation,
): boolean {
  return (
    isSafeRuntimeId(command.connection.profileId) &&
    command.connection.baseUrl.length > 0 &&
    command.connection.baseUrl.length <= 2_048 &&
    ownerIsValid(command.owner) &&
    isIdentifier(command.workId) &&
    isIdentifier(command.mediaVersionId) &&
    isIdentifier(command.volumeId) &&
    isIdentifier(command.contentFingerprint) &&
    Number.isFinite(command.percent) &&
    command.percent >= 0 &&
    command.percent <= 100 &&
    Number.isSafeInteger(command.nowMs) &&
    command.nowMs >= 0 &&
    isSafeRuntimeId(command.proposedClientId) &&
    isSafeRuntimeId(command.mutationId) &&
    (location.kind !== 'comic' ||
      command.volumeId === location.volumeId)
  );
}

export function recordReaderProgress(
  current: ReaderProgressDocument | null,
  command: RecordReaderProgressCommand,
): RecordReaderProgressResult {
  const decodedLocation = decodeReaderLocation(command.location);
  if (
    !decodedLocation.ok ||
    !commandIsValid(command, decodedLocation.value)
  ) {
    throw new ReaderProgressInvariantError('INVALID_PROGRESS');
  }
  const normalizedCommand: RecordReaderProgressCommand = {
    ...command,
    location: decodedLocation.value,
  };
  if (
    current !== null &&
    (current.connection.profileId !== command.connection.profileId ||
      current.connection.baseUrl !== command.connection.baseUrl)
  ) {
    throw new ReaderProgressInvariantError('CONNECTION_MISMATCH');
  }
  if (
    (current?.entries.length ?? 0) >
    MAXIMUM_READER_PROGRESS_ENTRIES
  ) {
    throw new ReaderProgressInvariantError('INVALID_PROGRESS');
  }

  const lastSequence = current?.client.lastSequence ?? 0;
  if (lastSequence >= Number.MAX_SAFE_INTEGER) {
    throw new ReaderProgressInvariantError('SEQUENCE_EXHAUSTED');
  }

  const sequence = lastSequence + 1;
  const updatedAtMs = Math.max(
    command.nowMs,
    current?.updatedAtMs ?? command.nowMs,
  );
  const previousEntry = current?.entries.find((entry) =>
    sameSlot(entry, normalizedCommand),
  );
  const entry: LocalProgressEntry = {
    mutationId: command.mutationId,
    clientSequence: sequence,
    owner: command.owner,
    workId: command.workId,
    mediaVersionId: command.mediaVersionId,
    volumeId: command.volumeId,
    contentFingerprint: command.contentFingerprint,
    location: decodedLocation.value,
    percent: command.percent,
    createdAtMs: previousEntry?.createdAtMs ?? updatedAtMs,
    updatedAtMs,
  };
  const currentEntries = current?.entries ?? [];
  const entries =
    previousEntry === undefined
      ? [...retainEntriesForNewSlot(currentEntries), entry]
      : currentEntries.map((candidate) =>
          candidate === previousEntry ? entry : candidate,
        );
  const document: ReaderProgressDocument = {
    format: 'shuku.reader-progress',
    schemaVersion: 3,
    generation: (current?.generation ?? 0) + 1,
    connection: command.connection,
    client: {
      id: current?.client.id ?? command.proposedClientId,
      lastSequence: sequence,
    },
    updatedAtMs,
    entries,
  };
  return { document, entry };
}

export function findReaderProgress(
  document: ReaderProgressDocument,
  query: FindReaderProgressQuery,
): LocalProgressEntry | null {
  if (
    document.connection.profileId !== query.connection.profileId ||
    document.connection.baseUrl !== query.connection.baseUrl
  ) {
    throw new ReaderProgressInvariantError('CONNECTION_MISMATCH');
  }
  if (
    !isSafeRuntimeId(query.connection.profileId) ||
    !ownerIsValid(query.owner) ||
    !isIdentifier(query.workId) ||
    !isIdentifier(query.mediaVersionId) ||
    !isIdentifier(query.volumeId) ||
    !isIdentifier(query.contentFingerprint)
  ) {
    throw new ReaderProgressInvariantError('INVALID_PROGRESS');
  }

  return (
    document.entries.find(
      (entry) =>
        ownersEqual(entry.owner, query.owner) &&
        entry.workId === query.workId &&
        entry.mediaVersionId === query.mediaVersionId &&
        entry.volumeId === query.volumeId &&
        entry.contentFingerprint === query.contentFingerprint &&
        entry.location.kind === query.readerKind,
    ) ?? null
  );
}
