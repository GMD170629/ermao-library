import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../testing/fakes';
import {
  hasOnlyKeys,
  isRecord,
  nonNegativeSafeInteger,
} from '../validation/unknown';
import {
  SnapshotDocumentStore,
  type JsonDocumentCodec,
} from './snapshot-document-store';
import { InProcessSnapshotOperationCoordinator } from './snapshot-operation-coordinator';

type CoordinatedDocument = Readonly<{
  generation: number;
  value: string;
}>;

const DOCUMENT_KEYS = new Set(['generation', 'value']);
const codec: JsonDocumentCodec<CoordinatedDocument> = {
  decode(value: unknown) {
    if (!isRecord(value) || !hasOnlyKeys(value, DOCUMENT_KEYS)) {
      return { ok: false, reason: 'INVALID_COORDINATED_DOCUMENT' };
    }
    const generation = nonNegativeSafeInteger(value.generation);
    if (
      generation === null ||
      generation < 1 ||
      typeof value.value !== 'string'
    ) {
      return { ok: false, reason: 'INVALID_COORDINATED_DOCUMENT' };
    }
    return { ok: true, value: { generation, value: value.value } };
  },
  encode(value: CoordinatedDocument): unknown {
    return value;
  },
};

test('coordinates writes from separate stores sharing one directory', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const coordinator = new InProcessSnapshotOperationCoordinator();
  const idGenerator = new SequenceIdGenerator();
  const firstStore = new SnapshotDocumentStore(
    fileSystem,
    'test/shared-coordinator',
    codec,
    idGenerator,
    coordinator,
  );
  const secondStore = new SnapshotDocumentStore(
    fileSystem,
    'test/shared-coordinator',
    codec,
    idGenerator,
    coordinator,
  );

  const [firstWrite, secondWrite] = await Promise.all([
    firstStore.update((current) => ({
      document: {
        generation: (current?.generation ?? 0) + 1,
        value: 'first-instance',
      },
      result: null,
    })),
    secondStore.update((current) => ({
      document: {
        generation: (current?.generation ?? 0) + 1,
        value: 'second-instance',
      },
      result: null,
    })),
  ]);

  assert.equal(firstWrite.value.generation, 1);
  assert.equal(secondWrite.value.generation, 2);
  const restored = await firstStore.read();
  assert.equal(restored.status, 'loaded');
  if (restored.status === 'loaded') {
    assert.equal(restored.value.value, 'second-instance');
  }
});
