import assert from 'node:assert/strict';
import test from 'node:test';

import {
  IncrementingClock,
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../../../shared/testing/fakes';
import { InProcessSnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import { SnapshotReaderProgressDocumentStore } from '../infrastructure/snapshot-reader-progress-document-store';
import { LoadReaderProgress } from './load-reader-progress';
import {
  SaveReaderProgress,
  type SaveReaderProgressCommand,
} from './save-reader-progress';

const connection = {
  profileId: 'profile-000001',
  baseUrl: 'http://192.168.1.20:3000',
} as const;

function reflowableProgress(
  percent: number,
  overrides: Partial<SaveReaderProgressCommand> = {},
): SaveReaderProgressCommand {
  return {
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    mediaVersionId: 'media-version-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    location: {
      kind: 'reflowable',
      format: 'epub',
      progression: percent / 100,
    },
    percent,
    ...overrides,
  };
}

test('saves the latest slot with a monotonic client sequence', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const ids = new SequenceIdGenerator();
  const store = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    ids,
    new InProcessSnapshotOperationCoordinator(),
  );
  const save = new SaveReaderProgress(
    store,
    new IncrementingClock(1_000),
    ids,
  );

  const first = await save.execute(reflowableProgress(10));
  const second = await save.execute(reflowableProgress(42));
  assert.equal(first.entry.clientSequence, 1);
  assert.equal(second.entry.clientSequence, 2);
  assert.equal(second.entry.percent, 42);
  assert.equal(second.entry.createdAtMs, first.entry.createdAtMs);

  const restartedStore = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const restored = await new LoadReaderProgress(
    restartedStore,
  ).execute({
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    mediaVersionId: 'media-version-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    readerKind: 'reflowable',
  });
  assert.equal(restored.outcome, 'found');
  if (restored.outcome === 'found') {
    assert.equal(restored.entry.percent, 42);
    assert.equal(restored.entry.clientSequence, 2);
  }
});

test('serializes concurrent progress writes without dropping another volume', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const ids = new SequenceIdGenerator();
  const store = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    ids,
    new InProcessSnapshotOperationCoordinator(),
  );
  const save = new SaveReaderProgress(
    store,
    new IncrementingClock(2_000),
    ids,
  );

  const [first, second] = await Promise.all([
    save.execute(reflowableProgress(10, { volumeId: 'volume-1' })),
    save.execute(reflowableProgress(20, { volumeId: 'volume-2' })),
  ]);
  assert.deepEqual(
    [first.entry.clientSequence, second.entry.clientSequence],
    [1, 2],
  );

  const document = await store.read(connection);
  assert.equal(document.document?.entries.length, 2);
});

test('falls back to the prior on-disk progress after latest corruption', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const ids = new SequenceIdGenerator();
  const store = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    ids,
    new InProcessSnapshotOperationCoordinator(),
  );
  const save = new SaveReaderProgress(
    store,
    new IncrementingClock(3_000),
    ids,
  );
  await save.execute(reflowableProgress(10));
  await save.execute(reflowableProgress(50));

  const directory = `reader-progress/${connection.profileId}`;
  const newest = fileSystem
    .fileNames(directory)
    .filter((name) => name.endsWith('.json'))
    .sort()
    .at(-1);
  assert.notEqual(newest, undefined);
  fileSystem.setFile(`${directory}/${newest}`, '{"truncated":');

  const restarted = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const restored = await new LoadReaderProgress(restarted).execute({
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    mediaVersionId: 'media-version-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    readerKind: 'reflowable',
  });
  assert.equal(restored.outcome, 'found');
  assert.equal(restored.recoveredFromCorruption, true);
  if (restored.outcome === 'found') {
    assert.equal(restored.entry.percent, 10);
  }
});

test('does not restore progress across a content fingerprint boundary', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const ids = new SequenceIdGenerator();
  const store = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    ids,
    new InProcessSnapshotOperationCoordinator(),
  );
  await new SaveReaderProgress(
    store,
    new IncrementingClock(4_000),
    ids,
  ).execute(reflowableProgress(25));

  const restored = await new LoadReaderProgress(store).execute({
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    mediaVersionId: 'media-version-1',
    volumeId: 'volume-1',
    contentFingerprint: 'different-fingerprint',
    readerKind: 'reflowable',
  });
  assert.equal(restored.outcome, 'not-found');
});

test('does not restore progress across a media version boundary', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const ids = new SequenceIdGenerator();
  const store = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    ids,
    new InProcessSnapshotOperationCoordinator(),
  );
  await new SaveReaderProgress(
    store,
    new IncrementingClock(5_000),
    ids,
  ).execute(reflowableProgress(25));

  const restored = await new LoadReaderProgress(store).execute({
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    mediaVersionId: 'media-version-2',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    readerKind: 'reflowable',
  });
  assert.equal(restored.outcome, 'not-found');
});

test('restores the complete Foliate snapshot after a process restart', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const ids = new SequenceIdGenerator();
  const store = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    ids,
    new InProcessSnapshotOperationCoordinator(),
  );
  const location = {
    kind: 'reflowable',
    format: 'azw3',
    cfi: 'epubcfi(/6/8)',
    href: 'text/chapter-4.xhtml',
    progression: 0.375,
    foliate: {
      continuous: { sectionFraction: 0.625 },
      toc: {
        index: 4,
        title: 'Chapter 4',
        href: 'text/chapter-4.xhtml',
        navigationKey: 'nav-chapter-4',
      },
      navigationFingerprint: 'navigation-fingerprint-1',
      section: { current: 4, total: 20 },
      location: { current: 375, next: 376, total: 1_000 },
      remainingSeconds: { section: 90.5, total: 2_400.25 },
    },
  } as const;

  await new SaveReaderProgress(
    store,
    new IncrementingClock(6_000),
    ids,
  ).execute(reflowableProgress(37.5, { location }));

  const restartedStore = new SnapshotReaderProgressDocumentStore(
    fileSystem,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const restored = await new LoadReaderProgress(restartedStore).execute({
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    mediaVersionId: 'media-version-1',
    volumeId: 'volume-1',
    contentFingerprint: 'fingerprint-1',
    readerKind: 'reflowable',
  });

  assert.equal(restored.outcome, 'found');
  if (restored.outcome === 'found') {
    assert.deepEqual(restored.entry.location, location);
  }
});
