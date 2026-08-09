import assert from 'node:assert/strict';
import test from 'node:test';

import { readerProgressDocumentCodec } from './reader-progress-document-codec';
import { decodeReaderLocation } from '../model/reader-location';
import { recordReaderProgress } from '../model/reader-progress';

const connection = {
  profileId: 'profile-000001',
  baseUrl: 'http://192.168.1.20:3000',
} as const;

function reflowableDocument() {
  return recordReaderProgress(null, {
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    mediaVersionId: 'media-version-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    location: {
      kind: 'reflowable',
      format: 'epub',
      cfi: 'epubcfi(/6/2)',
      href: 'chapter-2.xhtml',
      progression: 0.42,
      foliate: {
        continuous: { sectionFraction: 0.375 },
        toc: {
          index: 2,
          title: 'Chapter 2',
          href: 'chapter-2.xhtml',
          navigationKey: 'chapter-2',
        },
        navigationFingerprint: 'navigation-fingerprint-1',
        section: { current: 2, total: 12 },
        location: { current: 42, next: 43, total: 100 },
        remainingSeconds: { section: 125.5, total: 1_250.75 },
      },
    },
    percent: 42,
    nowMs: 1_000,
    proposedClientId: 'client-000001',
    mutationId: 'mutation-000001',
  });
}

test('round-trips the complete Reader v3 reflowable progress document', () => {
  const recorded = reflowableDocument();
  const decoded = readerProgressDocumentCodec.decode(
    readerProgressDocumentCodec.encode(recorded.document),
  );

  assert.equal(decoded.ok, true);
  if (decoded.ok) {
    assert.deepEqual(decoded.value, recorded.document);
    assert.deepEqual(
      decoded.value.entries[0]?.location,
      recorded.entry.location,
    );
  }
});

test('rejects prior schemas and edition-scoped entries', () => {
  const recorded = reflowableDocument();

  for (const schemaVersion of [1, 2]) {
    assert.equal(
      readerProgressDocumentCodec.decode({
        ...recorded.document,
        schemaVersion,
      }).ok,
      false,
    );
  }
  assert.equal(
    readerProgressDocumentCodec.decode({
      ...recorded.document,
      entries: [
        {
          ...recorded.entry,
          editionId: 'edition-1',
        },
      ],
    }).ok,
    false,
  );
});

test('accepts only current reflowable, comic and PDF locations', () => {
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

  assert.equal(
    decodeReaderLocation({ kind: 'epub', progression: 0.5 }).ok,
    false,
  );
  assert.equal(
    decodeReaderLocation({
      kind: 'reflowable',
      format: 'docx',
      progression: 0.5,
    }).ok,
    false,
  );
  assert.equal(
    decodeReaderLocation({
      kind: 'reflowable',
      format: 'epub',
      progression: 42,
    }).ok,
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

test('strictly validates every Foliate snapshot field', () => {
  const valid = reflowableDocument().entry.location;
  assert.equal(decodeReaderLocation(valid).ok, true);
  if (valid.kind !== 'reflowable' || valid.foliate === undefined) {
    assert.fail('Expected a reflowable Foliate location');
  }

  assert.equal(
    decodeReaderLocation({
      ...valid,
      foliate: {
        ...valid.foliate,
        continuous: { sectionFraction: 1.01 },
      },
    }).ok,
    false,
  );
  assert.equal(
    decodeReaderLocation({
      ...valid,
      foliate: {
        ...valid.foliate,
        section: { current: 12, total: 12 },
      },
    }).ok,
    false,
  );
  assert.equal(
    decodeReaderLocation({
      ...valid,
      foliate: {
        ...valid.foliate,
        location: { current: 42, next: 101, total: 100 },
      },
    }).ok,
    false,
  );
  assert.equal(
    decodeReaderLocation({
      ...valid,
      foliate: { ...valid.foliate, unsupportedMetric: 1 },
    }).ok,
    false,
  );
});

test('rejects a comic entry whose top-level volume does not match', () => {
  const recorded = recordReaderProgress(null, {
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    mediaVersionId: 'media-version-1',
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
