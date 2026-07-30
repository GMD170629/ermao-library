import assert from 'node:assert/strict';
import test from 'node:test';

import {
  hasOnlyKeys,
  isRecord,
  nonNegativeSafeInteger,
} from '../validation/unknown';
import {
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../testing/fakes';
import type { PrivateFileEntry } from './private-file-system';
import {
  SnapshotDocumentStore,
  type JsonDocumentCodec,
} from './snapshot-document-store';
import { InProcessSnapshotOperationCoordinator } from './snapshot-operation-coordinator';

type TestDocument = Readonly<{
  generation: number;
  value: string;
}>;

const DOCUMENT_KEYS = new Set(['generation', 'value']);
const codec: JsonDocumentCodec<TestDocument> = {
  decode(value: unknown) {
    if (!isRecord(value) || !hasOnlyKeys(value, DOCUMENT_KEYS)) {
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

class MaintenanceFailureFileSystem extends MemoryPrivateFileSystem {
  private listCallCount = 0;

  override async list(
    relativeDirectory: string,
  ): Promise<readonly PrivateFileEntry[]> {
    this.listCallCount += 1;
    if (this.listCallCount === 2) {
      throw new Error('Injected post-commit maintenance failure');
    }
    return super.list(relativeDirectory);
  }
}

test('reports post-commit cleanup failure without rejecting the write', async () => {
  const fileSystem = new MaintenanceFailureFileSystem();
  const store = new SnapshotDocumentStore(
    fileSystem,
    'test/post-commit-maintenance',
    codec,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );

  const write = await store.update(() => ({
    document: { generation: 1, value: 'committed' },
    result: 'accepted',
  }));

  assert.equal(write.result, 'accepted');
  assert.deepEqual(write.maintenanceIssues, [
    {
      operation: 'list-directory',
      target: 'test/post-commit-maintenance',
    },
  ]);
  const restored = await store.read();
  assert.equal(restored.status, 'loaded');
  if (restored.status === 'loaded') {
    assert.equal(restored.value.value, 'committed');
  }
});
