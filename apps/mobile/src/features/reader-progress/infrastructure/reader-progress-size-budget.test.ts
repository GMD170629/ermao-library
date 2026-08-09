import assert from 'node:assert/strict';
import test from 'node:test';

import { InProcessSnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import {
  IncrementingClock,
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../../../shared/testing/fakes';
import { SaveReaderProgress } from '../application/save-reader-progress';
import {
  MAXIMUM_READER_PROGRESS_ENTRIES,
  type LocalProgressEntry,
  type ProgressConnection,
  type ReaderProgressDocument,
} from '../model/reader-progress';
import { SnapshotReaderProgressDocumentStore } from './snapshot-reader-progress-document-store';

const ESCAPED_CHARACTER = '\u0001';
const MAXIMUM_IDENTIFIER_LENGTH = 191;
const MAXIMUM_CFI_LENGTH = 4_096;
const MAXIMUM_HREF_LENGTH = 2_048;
const connection: ProgressConnection = {
  profileId: 'profile-000001',
  baseUrl: 'https://library.example',
};

function maximumIdentifier(prefix: string, index: number): string {
  const uniquePrefix = `${prefix}-${String(index).padStart(3, '0')}-`;
  return `${uniquePrefix}${ESCAPED_CHARACTER.repeat(
    MAXIMUM_IDENTIFIER_LENGTH - uniquePrefix.length,
  )}`;
}

function maximumSafeRuntimeId(prefix: string, index: number): string {
  const uniquePrefix = `${prefix}-${String(index).padStart(3, '0')}-`;
  return `${uniquePrefix}${'x'.repeat(128 - uniquePrefix.length)}`;
}

function maximumEntry(index: number): LocalProgressEntry {
  return {
    mutationId: maximumSafeRuntimeId('mutation', index),
    clientSequence: index + 1,
    owner: {
      kind: 'user',
      userId: maximumIdentifier('user', index),
    },
    workId: maximumIdentifier('work', index),
    mediaVersionId: maximumIdentifier('media-version', index),
    volumeId: maximumIdentifier('volume', index),
    contentFingerprint: maximumIdentifier('fingerprint', index),
    location: {
      kind: 'reflowable',
      format: 'epub',
      cfi: ESCAPED_CHARACTER.repeat(MAXIMUM_CFI_LENGTH),
      href: ESCAPED_CHARACTER.repeat(MAXIMUM_HREF_LENGTH),
    },
    percent: 50,
    createdAtMs: index,
    updatedAtMs: index,
  };
}

function maximumDocument(): ReaderProgressDocument {
  return {
    format: 'shuku.reader-progress',
    schemaVersion: 3,
    generation: 1,
    connection,
    client: {
      id: maximumSafeRuntimeId('client', 0),
      lastSequence: MAXIMUM_READER_PROGRESS_ENTRIES,
    },
    updatedAtMs: MAXIMUM_READER_PROGRESS_ENTRIES - 1,
    entries: Array.from(
      { length: MAXIMUM_READER_PROGRESS_ENTRIES },
      (_value, index) => maximumEntry(index),
    ),
  };
}

test('persists and rotates a worst-case full progress snapshot below its file budget', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const idGenerator = new SequenceIdGenerator();
  const store = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    idGenerator,
    new InProcessSnapshotOperationCoordinator(),
  );
  await store.update(connection, () => ({
    document: maximumDocument(),
    result: null,
  }));

  const nextIndex = MAXIMUM_READER_PROGRESS_ENTRIES;
  await new SaveReaderProgress(
    store,
    new IncrementingClock(20_000),
    idGenerator,
  ).execute({
    connection,
    owner: {
      kind: 'user',
      userId: maximumIdentifier('user', nextIndex),
    },
    workId: maximumIdentifier('work', nextIndex),
    mediaVersionId: maximumIdentifier('media-version', nextIndex),
    volumeId: maximumIdentifier('volume', nextIndex),
    contentFingerprint: maximumIdentifier(
      'fingerprint',
      nextIndex,
    ),
    location: {
      kind: 'reflowable',
      format: 'epub',
      cfi: ESCAPED_CHARACTER.repeat(MAXIMUM_CFI_LENGTH),
      href: ESCAPED_CHARACTER.repeat(MAXIMUM_HREF_LENGTH),
    },
    percent: 75,
  });

  const restored = await store.read(connection);
  assert.equal(
    restored.document?.entries.length,
    MAXIMUM_READER_PROGRESS_ENTRIES,
  );
  assert.equal(
    restored.document?.entries.some(
      (entry) => entry.workId === maximumIdentifier('work', 0),
    ),
    false,
  );
  assert.equal(
    restored.document?.entries.some(
      (entry) =>
        entry.workId === maximumIdentifier('work', nextIndex),
    ),
    true,
  );
});
