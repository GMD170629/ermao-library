import assert from 'node:assert/strict';
import test from 'node:test';

import {
  IncrementingClock,
  SequenceIdGenerator,
} from '../../../shared/testing/fakes';
import { ConnectServer } from './connect-server';
import {
  ServerProfileWriteError,
  type ServerHealthGateway,
  type ServerProfileRepository,
} from './ports';

const healthyGateway: ServerHealthGateway = {
  async probe() {
    return { outcome: 'healthy' };
  },
};

test('returns a capability-level result when profile persistence fails', async () => {
  const profiles: ServerProfileRepository = {
    async activateHealthyServer() {
      return {
        ok: false,
        error: new ServerProfileWriteError(
          'storage-unavailable',
          new Error('Injected persistence failure'),
        ),
      };
    },
    async active() {
      return null;
    },
    async list() {
      return [];
    },
  };
  const connect = new ConnectServer(
    healthyGateway,
    profiles,
    new IncrementingClock(1_000),
    new SequenceIdGenerator(),
  );

  const result = await connect.execute({
    candidate: 'https://library.example',
    source: 'manual',
  });

  assert.deepEqual(result, {
    outcome: 'profile-save-failed',
    reason: 'storage-unavailable',
  });
});
