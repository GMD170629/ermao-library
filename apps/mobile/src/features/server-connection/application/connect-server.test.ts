import assert from 'node:assert/strict';
import test from 'node:test';

import {
  IncrementingClock,
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../../../shared/testing/fakes';
import { InProcessSnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import { SnapshotServerProfileRepository } from '../infrastructure/snapshot-server-profile-repository';
import { ConnectServer } from './connect-server';
import type { ServerHealthGateway } from './ports';

const healthyGateway: ServerHealthGateway = {
  async probe() {
    return { outcome: 'healthy' };
  },
};

test('persists a healthy server and reuses its profile after reconnecting', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const snapshotOperations =
    new InProcessSnapshotOperationCoordinator();
  const profiles = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    snapshotOperations,
  );
  const connect = new ConnectServer(
    healthyGateway,
    profiles,
    new IncrementingClock(1_000),
    new SequenceIdGenerator(),
  );

  const first = await connect.execute({
    candidate: '192.168.1.20:3000',
    source: 'manual',
  });
  assert.equal(first.outcome, 'connected');
  if (first.outcome !== 'connected') {
    assert.fail('Expected the manual connection to succeed');
  }

  const second = await connect.execute({
    candidate: 'http://192.168.1.20:3000/',
    source: 'qr',
  });
  assert.equal(second.outcome, 'connected');
  if (second.outcome !== 'connected') {
    assert.fail('Expected the QR connection to succeed');
  }

  assert.equal(second.profile.id, first.profile.id);
  assert.equal(second.profile.createdAtMs, 1_000);
  assert.equal(second.profile.lastVerifiedAtMs, 1_001);
  assert.equal((await profiles.list()).length, 1);

  const restoredProfiles = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    snapshotOperations,
  );
  assert.deepEqual(await restoredProfiles.active(), second.profile);
});

test('does not persist a server that reports an unhealthy state', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const snapshotOperations =
    new InProcessSnapshotOperationCoordinator();
  const profiles = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    snapshotOperations,
  );
  const unhealthyGateway: ServerHealthGateway = {
    async probe() {
      return { outcome: 'unhealthy', status: 'error' };
    },
  };
  const connect = new ConnectServer(
    unhealthyGateway,
    profiles,
    new IncrementingClock(1_000),
    new SequenceIdGenerator(),
  );

  const result = await connect.execute({
    candidate: 'http://192.168.1.20:3000',
    source: 'manual',
  });

  assert.deepEqual(result, { outcome: 'unhealthy', status: 'error' });
  assert.deepEqual(await profiles.list(), []);
  assert.deepEqual(
    fileSystem.fileNames('server-connection/profiles'),
    [],
  );
});
