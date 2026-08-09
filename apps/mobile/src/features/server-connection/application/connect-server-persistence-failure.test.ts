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
    return { outcome: 'healthy', initialized: true };
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
    async activateExistingHealthyServer() {
      return { ok: true, activated: false, reason: 'not-found' };
    },
    async deleteProfile() {
      return { ok: true, deleted: false };
    },
    async load() {
      return {
        ok: true,
        catalog: {
          generation: 0,
          activeProfileId: null,
          profiles: [],
          updatedAtMs: 0,
        },
        warnings: [],
      };
    },
    async resetCorrupt() {
      return { ok: true, reset: false, deletedFileCount: 0 };
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
