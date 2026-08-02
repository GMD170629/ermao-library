import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MAXIMUM_READER_PROGRESS_ENTRIES,
  recordReaderProgress,
  type LocalProgressEntryV2,
  type ProgressConnection,
  type ReaderProgressDocumentV2,
  type RecordReaderProgressCommand,
} from './reader-progress';

const connection: ProgressConnection = {
  profileId: 'profile-000001',
  baseUrl: 'https://library.example',
};

function progressEntry(index: number): LocalProgressEntryV2 {
  return {
    mutationId: `mutation-${index}`,
    clientSequence: index + 1,
    owner: { kind: 'local' },
    workId: `work-${index}`,
    volumeId: `volume-${index}`,
    contentFingerprint: `fingerprint-${index}`,
    location: { kind: 'epub', progression: index / 10_000 },
    percent: index / 100,
    createdAtMs: index,
    updatedAtMs: index,
  };
}

function fullDocument(): ReaderProgressDocumentV2 {
  return {
    format: 'shuku.reader-progress',
    schemaVersion: 2,
    generation: 1,
    connection,
    client: {
      id: 'client-1',
      lastSequence: MAXIMUM_READER_PROGRESS_ENTRIES,
    },
    updatedAtMs: MAXIMUM_READER_PROGRESS_ENTRIES - 1,
    entries: Array.from(
      { length: MAXIMUM_READER_PROGRESS_ENTRIES },
      (_value, index) => progressEntry(index),
    ),
  };
}

function recordCommand(
  workIndex: number,
): RecordReaderProgressCommand {
  return {
    connection,
    owner: { kind: 'local' },
    workId: `work-${workIndex}`,
    volumeId: `volume-${workIndex}`,
    contentFingerprint: `fingerprint-${workIndex}`,
    location: { kind: 'epub', progression: 0.5 },
    percent: 50,
    nowMs: 20_000,
    proposedClientId: 'unused-client',
    mutationId: `new-mutation-${workIndex}`,
  };
}

test('evicts the least recently updated slot before adding beyond capacity', () => {
  const recorded = recordReaderProgress(
    fullDocument(),
    recordCommand(MAXIMUM_READER_PROGRESS_ENTRIES),
  );

  assert.equal(
    recorded.document.entries.length,
    MAXIMUM_READER_PROGRESS_ENTRIES,
  );
  assert.equal(
    recorded.document.entries.some((entry) => entry.workId === 'work-0'),
    false,
  );
  assert.equal(
    recorded.document.entries.some(
      (entry) =>
        entry.workId ===
        `work-${MAXIMUM_READER_PROGRESS_ENTRIES}`,
    ),
    true,
  );
});

test('updates an existing slot at capacity without evicting another slot', () => {
  const recorded = recordReaderProgress(fullDocument(), recordCommand(0));

  assert.equal(
    recorded.document.entries.length,
    MAXIMUM_READER_PROGRESS_ENTRIES,
  );
  assert.equal(
    recorded.document.entries.some((entry) => entry.workId === 'work-1'),
    true,
  );
  assert.equal(recorded.entry.workId, 'work-0');
  assert.equal(
    recorded.entry.clientSequence,
    MAXIMUM_READER_PROGRESS_ENTRIES + 1,
  );
});
