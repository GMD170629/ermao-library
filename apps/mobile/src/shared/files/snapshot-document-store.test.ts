import assert from 'node:assert/strict';
import test from 'node:test';

import {
  SnapshotDocumentStore,
  type JsonDocumentCodec,
} from './snapshot-document-store';
import { InProcessSnapshotOperationCoordinator } from './snapshot-operation-coordinator';
import {
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../testing/fakes';
import {
  hasOnlyKeys,
  isRecord,
  nonNegativeSafeInteger,
} from '../validation/unknown';

type TestDocument = Readonly<{
  generation: number;
  value: string;
}>;

const TEST_DOCUMENT_KEYS = new Set(['generation', 'value']);
const testCodec: JsonDocumentCodec<TestDocument> = {
  decode(value: unknown) {
    if (!isRecord(value) || !hasOnlyKeys(value, TEST_DOCUMENT_KEYS)) {
      return { ok: false, reason: 'INVALID_TEST_DOCUMENT' };
    }
    const generation = nonNegativeSafeInteger(value.generation);
    if (
      generation === null ||
      generation < 1 ||
      typeof value.value !== 'string'
    ) {
      return { ok: false, reason: 'INVALID_TEST_DOCUMENT' };
    }
    return { ok: true, value: { generation, value: value.value } };
  },
  encode(value: TestDocument): unknown {
    return value;
  },
};

test('serializes concurrent updates without losing a generation', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const store = new SnapshotDocumentStore(
    fileSystem,
    'test/documents',
    testCodec,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );

  const first = store.update((current) => ({
    document: {
      generation: (current?.generation ?? 0) + 1,
      value: 'first',
    },
    result: 'first',
  }));
  const second = store.update((current) => ({
    document: {
      generation: (current?.generation ?? 0) + 1,
      value: 'second',
    },
    result: 'second',
  }));

  const [firstWrite, secondWrite] = await Promise.all([first, second]);
  assert.equal(firstWrite.value.generation, 1);
  assert.equal(secondWrite.value.generation, 2);
  const restored = await store.read();
  assert.equal(restored.status, 'loaded');
  if (restored.status === 'loaded') {
    assert.deepEqual(restored.value, {
      generation: 2,
      value: 'second',
    });
  }
});

test('falls back to the previous valid snapshot after corruption', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const store = new SnapshotDocumentStore(
    fileSystem,
    'test/recovery',
    testCodec,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  await store.update(() => ({
    document: { generation: 1, value: 'safe' },
    result: null,
  }));
  await store.update(() => ({
    document: { generation: 2, value: 'newest' },
    result: null,
  }));

  const newest = fileSystem
    .fileNames('test/recovery')
    .filter((name) => name.endsWith('.json'))
    .sort()
    .at(-1);
  assert.notEqual(newest, undefined);
  fileSystem.setFile(`test/recovery/${newest}`, '{"truncated":');

  const restored = await store.read();
  assert.equal(restored.status, 'loaded');
  if (restored.status === 'loaded') {
    assert.equal(restored.value.value, 'safe');
    assert.equal(restored.recoveredFromCorruption, true);
    assert.equal(restored.rejectedNewerSnapshots, 1);
  }
});

test('a failed publish leaves the last committed snapshot readable', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const store = new SnapshotDocumentStore(
    fileSystem,
    'test/failure',
    testCodec,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  await store.update(() => ({
    document: { generation: 1, value: 'committed' },
    result: null,
  }));

  fileSystem.failNextMove = true;
  await assert.rejects(
    store.update(() => ({
      document: { generation: 2, value: 'not-committed' },
      result: null,
    })),
    /Injected move failure/,
  );

  const restored = await store.read();
  assert.equal(restored.status, 'loaded');
  if (restored.status === 'loaded') {
    assert.equal(restored.value.value, 'committed');
  }
});
