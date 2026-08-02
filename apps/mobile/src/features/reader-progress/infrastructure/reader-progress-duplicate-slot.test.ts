import assert from 'node:assert/strict';
import test from 'node:test';

import { isRecord } from '../../../shared/validation/unknown';
import { recordReaderProgress } from '../model/reader-progress';
import { readerProgressDocumentCodec } from './reader-progress-document-codec';

test('rejects a persisted document containing the same logical slot twice', () => {
  const recorded = recordReaderProgress(null, {
    connection: {
      profileId: 'profile-000001',
      baseUrl: 'http://192.168.1.20:3000',
    },
    owner: { kind: 'local' },
    workId: 'work-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    location: { kind: 'epub', progression: 0.25 },
    percent: 25,
    nowMs: 1_000,
    proposedClientId: 'client-000001',
    mutationId: 'mutation-000001',
  });
  const firstEntry = recorded.document.entries.at(0);
  assert.notEqual(firstEntry, undefined);
  if (firstEntry === undefined) {
    assert.fail('Expected the recorded document to contain one entry');
  }

  const encoded = readerProgressDocumentCodec.encode(recorded.document);
  assert.equal(isRecord(encoded), true);
  if (!isRecord(encoded)) {
    assert.fail('Expected an encoded progress document object');
  }

  const tampered = {
    ...encoded,
    client: {
      id: recorded.document.client.id,
      lastSequence: 2,
    },
    updatedAtMs: 1_001,
    entries: [
      firstEntry,
      {
        ...firstEntry,
        mutationId: 'mutation-000002',
        clientSequence: 2,
        percent: 50,
        updatedAtMs: 1_001,
      },
    ],
  };

  assert.equal(readerProgressDocumentCodec.decode(tampered).ok, false);
});
