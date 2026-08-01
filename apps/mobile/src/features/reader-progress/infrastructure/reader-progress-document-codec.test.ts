import assert from 'node:assert/strict';
import test from 'node:test';

import { readerProgressDocumentCodec } from './reader-progress-document-codec';
import { decodeReaderLocation } from '../model/reader-location';
import { recordReaderProgress } from '../model/reader-progress';

const connection = {
  profileId: 'profile-000001',
  baseUrl: 'http://192.168.1.20:3000',
} as const;

test('round-trips a validated EPUB progress document', () => {
  const recorded = recordReaderProgress(null, {
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    location: {
      kind: 'epub',
      cfi: 'epubcfi(/6/2)',
      progression: 0.42,
    },
    percent: 42,
    nowMs: 1_000,
    proposedClientId: 'client-000001',
    mutationId: 'mutation-000001',
  });

  const decoded = readerProgressDocumentCodec.decode(
    readerProgressDocumentCodec.encode(recorded.document),
  );
  assert.equal(decoded.ok, true);
  if (decoded.ok) {
    assert.deepEqual(decoded.value, recorded.document);
  }
});

test('migrates a legacy edition-scoped entry only when it has an explicit volume', () => {
  const legacy = {
    format: 'shuku.reader-progress',
    schemaVersion: 1,
    generation: 1,
    connection,
    client: { id: 'client-000001', lastSequence: 1 },
    updatedAtMs: 1_000,
    entries: [{
      mutationId: 'mutation-000001',
      clientSequence: 1,
      owner: { kind: 'local' },
      workId: 'work-1',
      editionId: 'edition-1',
      volumeId: 'volume-1',
      contentFingerprint: 'fingerprint-1',
      location: { kind: 'epub', progression: 0.42 },
      percent: 42,
      createdAtMs: 1_000,
      updatedAtMs: 1_000,
    }],
  };

  const migrated = readerProgressDocumentCodec.decode(legacy);
  assert.equal(migrated.ok, true);
  if (migrated.ok) {
    assert.equal(migrated.value.schemaVersion, 2);
    assert.equal(migrated.value.entries[0]?.volumeId, 'volume-1');
    assert.equal('editionId' in (migrated.value.entries[0] ?? {}), false);
  }

  const ambiguous = {
    ...legacy,
    entries: [{ ...legacy.entries[0], volumeId: null }],
  };
  assert.equal(readerProgressDocumentCodec.decode(ambiguous).ok, false);
});

test('validates reflowable, legacy EPUB, comic and PDF locations at the file boundary', () => {
  assert.equal(
    decodeReaderLocation({
      kind: 'reflowable',
      format: 'mobi',
      cfi: 'epubcfi(/6/4)',
      progression: 0.5,
    }).ok,
    true,
  );
  assert.equal(
    decodeReaderLocation({ kind: 'epub', progression: 0.5 }).ok,
    true,
  );
  assert.equal(
    decodeReaderLocation({
      kind: 'comic',
      volumeId: 'volume-1',
      pageIndex: 1,
    }).ok,
    true,
  );
  assert.equal(
    decodeReaderLocation({ kind: 'pdf', pageNumber: 1 }).ok,
    true,
  );

  assert.equal(decodeReaderLocation({ kind: 'epub' }).ok, false);
  assert.equal(
    decodeReaderLocation({
      kind: 'reflowable',
      format: 'docx',
      progression: 0.5,
    }).ok,
    false,
  );
  assert.equal(
    decodeReaderLocation({ kind: 'epub', progression: 42 }).ok,
    false,
  );
  assert.equal(
    decodeReaderLocation({
      kind: 'comic',
      volumeId: 'volume-1',
      pageIndex: 0,
    }).ok,
    false,
  );
  assert.equal(
    decodeReaderLocation({ kind: 'pdf', pageNumber: 0 }).ok,
    false,
  );
});

test('rejects a comic entry whose top-level volume does not match', () => {
  const recorded = recordReaderProgress(null, {
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    location: {
      kind: 'comic',
      volumeId: 'volume-1',
      pageIndex: 3,
    },
    percent: 30,
    nowMs: 1_000,
    proposedClientId: 'client-000001',
    mutationId: 'mutation-000001',
  });
  const encoded = readerProgressDocumentCodec.encode(recorded.document);
  assert.equal(typeof encoded, 'object');
  if (typeof encoded !== 'object' || encoded === null) {
    throw new Error('Encoded document must be an object');
  }
  const tampered = {
    ...encoded,
    entries: [
      {
        ...recorded.document.entries[0],
        volumeId: 'volume-2',
      },
    ],
  };
  assert.equal(readerProgressDocumentCodec.decode(tampered).ok, false);
});
