import assert from 'node:assert/strict';
import test from 'node:test';

import {
  IncrementingClock,
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../../../shared/testing/fakes';
import { InProcessSnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import { SnapshotServerProfileRepository } from '../infrastructure/snapshot-server-profile-repository';
import { AbortSignalCancellationToken } from '../infrastructure/abort-signal-cancellation-token';
import { ConnectServer } from './connect-server';
import type { ServerHealthGateway } from './ports';

const healthyGateway: ServerHealthGateway = {
  async probe() {
    return { outcome: 'healthy', initialized: true };
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
  assert.equal(second.profile.initialized, true);
  assert.equal(second.profile.createdAtMs, 1_000);
  assert.equal(second.profile.lastVerifiedAtMs, 1_001);
  const loaded = await profiles.load();
  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected profiles to load');
  assert.equal(loaded.catalog.profiles.length, 1);

  const restoredProfiles = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    snapshotOperations,
  );
  const restored = await restoredProfiles.load();
  assert.equal(restored.ok, true);
  if (!restored.ok) assert.fail('Expected profiles to restore');
  assert.equal(restored.catalog.activeProfileId, second.profile.id);
  assert.deepEqual(restored.catalog.profiles[0], second.profile);
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
  const loaded = await profiles.load();
  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected profiles to load');
  assert.deepEqual(loaded.catalog.profiles, []);
  assert.deepEqual(
    fileSystem.fileNames('server-connection/profiles'),
    [],
  );
});

test('manual and QR candidates share the same address validation boundary', async () => {
  const profiles = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const connect = new ConnectServer(
    healthyGateway,
    profiles,
    new IncrementingClock(1_000),
    new SequenceIdGenerator(),
  );

  for (const source of ['manual', 'qr'] as const) {
    assert.deepEqual(
      await connect.execute({
        candidate: 'https://user:secret@books.example',
        source,
      }),
      { outcome: 'invalid-address', code: 'CREDENTIALS_NOT_ALLOWED' },
    );
    assert.deepEqual(
      await connect.execute({
        candidate: 'http://127.0.0.1:3000',
        source,
      }),
      { outcome: 'invalid-address', code: 'DEVICE_LOOPBACK_NOT_ALLOWED' },
    );
  }
});

test('pre-cancelled connection does not probe or persist', async () => {
  let probeCount = 0;
  const profiles = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const connect = new ConnectServer(
    {
      async probe() {
        probeCount += 1;
        return { outcome: 'healthy', initialized: true };
      },
    },
    profiles,
    new IncrementingClock(1_000),
    new SequenceIdGenerator(),
  );
  const controller = new AbortController();
  controller.abort();

  assert.deepEqual(
    await connect.execute({
      candidate: 'https://books.example',
      source: 'qr',
      cancellation: new AbortSignalCancellationToken(controller.signal),
    }),
    { outcome: 'cancelled' },
  );
  assert.equal(probeCount, 0);
  const loaded = await profiles.load();
  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected profiles to load');
  assert.deepEqual(loaded.catalog.profiles, []);
});

test('cancellation after health verification prevents profile persistence', async () => {
  const controller = new AbortController();
  const profiles = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const connect = new ConnectServer(
    {
      async probe() {
        controller.abort();
        return { outcome: 'healthy', initialized: true };
      },
    },
    profiles,
    new IncrementingClock(1_000),
    new SequenceIdGenerator(),
  );

  assert.deepEqual(
    await connect.execute({
      candidate: 'https://books.example',
      source: 'manual',
      cancellation: new AbortSignalCancellationToken(controller.signal),
    }),
    { outcome: 'cancelled' },
  );
  const loaded = await profiles.load();
  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected profiles to load');
  assert.deepEqual(loaded.catalog.profiles, []);
});
